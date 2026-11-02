#!/usr/bin/env python3
"""Standalone AMI-driven AllStarLink link transition watcher."""
import configparser
import logging
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LOG = logging.getLogger('asl3-node-watcher')
NODE = re.compile(r'(?<!\d)(\d{4,7})(?!\d)')
STOP = threading.Event()


def load_config(path):
    cfg = configparser.ConfigParser(interpolation=None)
    if not cfg.read(path):
        raise ValueError(f'Configuration not found: {path}')
    g = cfg['general']
    locals_ = [x.strip() for x in g.get('local_nodes', fallback='').split(',') if x.strip()]
    if not locals_ or any(not x.isdigit() for x in locals_):
        raise ValueError('general.local_nodes must contain numeric node IDs')
    watched = {}
    for section in cfg.sections():
        if section.startswith('node:'):
            node = section.split(':', 1)[1].strip()
            if not node.isdigit():
                raise ValueError(f'Invalid node section: {section}')
            watched[node] = {e: cfg.get(section, f'on_{e}', fallback='').strip() for e in ('connect', 'disconnect')}
    if not watched:
        LOG.warning('No watched nodes configured')
    return {
        'locals': locals_, 'watched': watched,
        'host': g.get('ami_host', '127.0.0.1'),
        'port': g.getint('ami_port', 5038),
        'user': g.get('ami_username', 'asl3-node-watcher'),
        'password': g.get('ami_password'),
        'poll': max(1, g.getfloat('poll_seconds', 3)),
        'timeout': max(1, g.getfloat('command_timeout_seconds', 30)),
        'workers': max(1, g.getint('max_parallel_scripts', 4)),
        'log_level': g.get('log_level', 'INFO'),
    }


def parse_links(output, local_node):
    """Parse established remote nodes from rpt lstats output."""
    links = set()
    for line in output.splitlines():
        fields = line.split()
        if not fields or not fields[0].isdigit():
            continue
        remote = fields[0]
        if remote == str(local_node):
            continue
        if fields[-1].upper() == "ESTABLISHED":
            links.add(remote)
    return links


class AMI:
    def __init__(self, host, port, user, password):
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sock = None
        self.stream = None
        self.lock = threading.Lock()
        self.counter = 0

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        self.sock.settimeout(20)
        self.stream = self.sock.makefile('rb')
        banner = self.stream.readline()
        if not banner.startswith(b'Asterisk Call Manager/'):
            raise RuntimeError(f'Unexpected AMI banner: {banner!r}')
        response, _ = self.action({'Action': 'Login', 'Username': self.user, 'Secret': self.password, 'Events': 'off'})
        if response.get('Response') != 'Success':
            raise RuntimeError(f'AMI login failed: {response}')

    def close(self):
        try:
            if self.stream:
                self.stream.close()
        except OSError:
            pass
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

    def _message(self):
        fields = {}
        while True:
            line = self.stream.readline()
            if not line:
                raise ConnectionError('AMI connection closed')
            if line == b'\r\n':
                return fields
            key, sep, value = line.decode('utf-8', 'replace').rstrip('\r\n').partition(':')
            if sep:
                if key == 'Output' and key in fields:
                    fields[key] += '\n' + value.strip()
                else:
                    fields[key] = value.strip()

    def action(self, fields):
        with self.lock:
            self.counter += 1
            action_id = f'watcher-{self.counter}'
            fields = {**fields, 'ActionID': action_id}
            payload = ''.join(f'{k}: {v}\r\n' for k, v in fields.items()) + '\r\n'
            self.sock.sendall(payload.encode())
            while True:
                response = self._message()
                if response.get('ActionID') != action_id:
                    continue
                if response.get('Response') == 'Follows':
                    lines = []
                    while True:
                        line = self.stream.readline()
                        if not line:
                            raise ConnectionError('AMI command truncated')
                        decoded = line.decode('utf-8', 'replace').rstrip('\r\n')
                        if decoded == '--END COMMAND--':
                            return response, '\n'.join(lines)
                        lines.append(decoded)
                return response, response.get('Output', '')

    def links(self, local_node):
        response, output = self.action({'Action': 'Command', 'Command': f'rpt lstats {local_node}'})
        if response.get('Response') not in ('Success', 'Follows'):
            raise RuntimeError(f'AMI command failed for {local_node}: {response}')
        return parse_links(output, local_node)


def execute(command, local, remote, event, timeout):
    args = shlex.split(command)
    if not args:
        return
    env = os.environ.copy()
    env.update(ASL_LOCAL_NODE=local, ASL_REMOTE_NODE=remote, ASL_EVENT=event)
    LOG.info('Executing %s for local=%s remote=%s', event, local, remote)
    try:
        result = subprocess.run(args + [local, remote, event], env=env, timeout=timeout,
                                capture_output=True, text=True, check=False)
        if result.stdout.strip():
            LOG.info('Script stdout: %s', result.stdout.strip()[:2000])
        if result.stderr.strip():
            LOG.warning('Script stderr: %s', result.stderr.strip()[:2000])
        if result.returncode:
            LOG.error('Script exited %d for remote %s', result.returncode, remote)
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.error('Script failed for remote %s: %s', remote, exc)


def transitions(old, new):
    return [('connect', n) for n in sorted(new - old)] + [('disconnect', n) for n in sorted(old - new)]


def run(cfg):
    delay = 1
    with ThreadPoolExecutor(max_workers=cfg['workers']) as pool:
        while not STOP.is_set():
            ami = AMI(cfg['host'], cfg['port'], cfg['user'], cfg['password'])
            try:
                ami.connect()
                LOG.info('Connected to AMI %s:%d', cfg['host'], cfg['port'])
                previous = {local: ami.links(local) for local in cfg['locals']}
                LOG.info('Initial link baseline: %s', previous)
                delay = 1
                while not STOP.wait(cfg['poll']):
                    for local in cfg['locals']:
                        current = ami.links(local)
                        for event, remote in transitions(previous[local], current):
                            LOG.info('Node %s %sed to %s', remote, event, local)
                            command = cfg['watched'].get(remote, {}).get(event)
                            if command:
                                pool.submit(execute, command, local, remote, event, cfg['timeout'])
                        previous[local] = current
            except (OSError, ConnectionError, RuntimeError, ValueError) as exc:
                LOG.warning('AMI monitoring interrupted: %s; retry in %ss', exc, delay)
                STOP.wait(delay)
                delay = min(delay * 2, 60)
            finally:
                ami.close()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else '/etc/asl3-node-watcher.conf'
    cfg = load_config(path)
    logging.basicConfig(level=getattr(logging, cfg['log_level'].upper(), logging.INFO),
                        format='%(asctime)s %(levelname)s %(message)s')
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    run(cfg)


if __name__ == '__main__':
    main()
