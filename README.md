# ASL3 Node Watcher

Standalone Python 3 service for AllStarLink 3. Monitors Asterisk AMI for connection state changes and launches per-node commands defined in an INI configuration file. Does not modify `rpt.conf` or the existing connection logger.

## Installation

On Debian/ASL3, unpack this project and run:

```bash
sudo ./install.sh
sudoedit /etc/asl3-node-watcher.conf
sudo systemctl enable --now asl3-node-watcher.service
journalctl -u asl3-node-watcher -f
```

The installer creates a dedicated AMI account in `/etc/asterisk/manager.d/asl3-node-watcher.conf` (or prints manual instructions if that directory is unavailable), and uses a random password in the application configuration. Asterisk Manager must be enabled and accessible on localhost. Review your Asterisk manager configuration before enabling.

## Event source

Uses AMI `RPT_ALINKS`/`RPT_LINKS`-style link state events where available, and `RPT` link events when supplied by the installed Asterisk/app_rpt build. Since event names and fields vary by ASL3 version, the service also periodically reconciles the authoritative `rpt lstats <local_node>` output via AMI `Command`. This allows it to detect connect/disconnect transitions even when unsolicited link events are unavailable. It never treats the initial snapshot as a new connection; after a service restart, existing links form the baseline.

## Configuration

See `asl3-node-watcher.conf.example`. Each `[node:NNNNNN]` section may specify `on_connect`, `on_disconnect`, or both. Commands are parsed with `shlex.split`, without a shell. The remote node and event name are appended as positional arguments. Environment variables `ASL_LOCAL_NODE`, `ASL_REMOTE_NODE`, `ASL_EVENT` are also provided. For multiple local nodes, use `local_nodes = 658860,651860`.

## Security

Run scripts as the `asterisk` user. Only configure trusted, executable scripts. No shell interpolation is performed. Scripts have a timeout and a bounded concurrency limit. AMI credentials are kept in a root-owned 0600 configuration file. The service does not require root.

## Behavior

- Initial scan establishes a baseline (no connect actions for pre-existing links).
- Each subsequent transition fires once; reconnects fire again.
- AMI disconnects cause reconnection with exponential backoff and a new baseline (no synthetic disconnects).
- Link checks use `rpt lstats` (the exact command may differ across installations); test `asterisk -rx 'rpt lstats 658860'` if no events appear.
- Local node-to-node links are tracked separately by `(local_node, remote_node)`.

## Testing

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile node_watcher.py
```
