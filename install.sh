#!/usr/bin/env bash
set -Eeuo pipefail
[[ $(id -u) -eq 0 ]] || { echo 'Run as root' >&2; exit 1; }
cd "$(dirname "$(readlink -f "$0")")"
install -d -m 755 /opt/asl3-node-watcher
install -m 755 node_watcher.py /opt/asl3-node-watcher/node_watcher.py
install -m 644 asl3-node-watcher.service /etc/systemd/system/asl3-node-watcher.service
if [[ ! -f /etc/asl3-node-watcher.conf ]]; then
  install -m 600 asl3-node-watcher.conf.example /etc/asl3-node-watcher.conf
  password=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  sed -i "s|REPLACE_ME|$password|" /etc/asl3-node-watcher.conf
else
  password=$(sed -n 's/^ami_password *= *//p' /etc/asl3-node-watcher.conf | head -1)
fi
if [[ -d /etc/asterisk/manager.d ]]; then
  cat > /etc/asterisk/manager.d/asl3-node-watcher.conf <<EOM
[asl3-node-watcher]
secret = $password
read = system,call,command,reporting
write = command
permit = 127.0.0.1/255.255.255.255
EOM
  chmod 640 /etc/asterisk/manager.d/asl3-node-watcher.conf
  chown root:asterisk /etc/asterisk/manager.d/asl3-node-watcher.conf
  echo 'Created AMI account; ensure manager.conf includes manager.d/*.conf and reload manager.'
else
  echo 'WARNING: /etc/asterisk/manager.d not present. Configure AMI account manually.'
fi
chown root:asterisk /etc/asl3-node-watcher.conf
chmod 640 /etc/asl3-node-watcher.conf
systemctl daemon-reload
echo 'Edit /etc/asl3-node-watcher.conf, then run: systemctl enable --now asl3-node-watcher'
