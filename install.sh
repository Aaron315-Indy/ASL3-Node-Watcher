#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || {
    echo "ERROR: Run as root" >&2
    exit 1
}

cd "$(dirname "$(readlink -f "$0")")"

APP_DIR=/opt/asl3-node-watcher
CONFIG=/etc/asl3-node-watcher.conf
MANAGER=/etc/asterisk/manager.conf
AMI_DIR=/etc/asterisk/manager.d
AMI_FILE="$AMI_DIR/asl3-node-watcher.conf"
SERVICE=/etc/systemd/system/asl3-node-watcher.service

echo "Installing ASL3 Node Watcher..."

# Identify local app_rpt node.
mapfile -t NODES < <(
    awk '
      /^\[[0-9]+\][[:space:]]*([;#].*)?$/ {
        gsub(/[\[\]]/, "", $1)
        print $1
      }
    ' /etc/asterisk/rpt.conf | sort -u
)

if [[ ! -f "$CONFIG" ]]; then
    if (( ${#NODES[@]} != 1 )); then
        echo "ERROR: Expected one local node in rpt.conf; found ${#NODES[@]}." >&2
        echo "Create $CONFIG manually for multi-node installations." >&2
        exit 1
    fi

    NODE="${NODES[0]}"
    PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

    install -m 600 asl3-node-watcher.conf.example "$CONFIG"
    sed -i \
        -e "s|local_nodes = AUTO|local_nodes = $NODE|" \
        -e "s|REPLACE_ME|$PASSWORD|" \
        "$CONFIG"

    echo "Created configuration for local node $NODE."
else
    echo "Preserving existing $CONFIG."
fi

# Read effective AMI credentials from the watcher configuration.
AMI_USER="$(sed -nE 's/^[[:space:]]*ami_username[[:space:]]*=[[:space:]]*(.*)/\1/p' "$CONFIG" | tail -1)"
PASSWORD="$(sed -nE 's/^[[:space:]]*ami_password[[:space:]]*=[[:space:]]*(.*)/\1/p' "$CONFIG" | tail -1)"

if [[ -z "$AMI_USER" || -z "$PASSWORD" || "$PASSWORD" == REPLACE_ME ]]; then
    echo "ERROR: Missing or invalid AMI credentials in $CONFIG" >&2
    exit 1
fi

install -d -m 755 "$AMI_DIR"

if [[ ! -f "$AMI_FILE" ]]; then
    cat > "$AMI_FILE" <<EOM
[$AMI_USER]
secret = $PASSWORD
read = system,call,command,reporting
write = command
permit = 127.0.0.1/255.255.255.255
EOM

    chown root:asterisk "$AMI_FILE"
    chmod 640 "$AMI_FILE"
    echo "Created AMI account."
else
    echo "Preserving existing AMI account."
fi

# Ensure manager.conf loads the watcher account.
if [[ ! -f "$MANAGER" ]]; then
    echo "ERROR: $MANAGER not found." >&2
    exit 1
fi

if ! grep -Eq \
    '^[[:space:]]*#include[[:space:]]+["'\'']?manager\.d/asl3-node-watcher\.conf' \
    "$MANAGER"; then

    printf '\n#include manager.d/asl3-node-watcher.conf\n' >> "$MANAGER"
    echo "Added AMI include to manager.conf."
fi

# Install application and service.
install -d -m 755 "$APP_DIR"
install -m 755 node_watcher.py "$APP_DIR/node_watcher.py"
install -m 644 asl3-node-watcher.service "$SERVICE"

chown root:asterisk "$CONFIG"
chmod 640 "$CONFIG"

systemctl daemon-reload

if systemctl is-active --quiet asterisk; then
    asterisk -rx "manager reload"
fi

if systemctl is-enabled --quiet asl3-node-watcher 2>/dev/null; then
    systemctl restart asl3-node-watcher
    echo "Restarted existing watcher."
else
    echo "Enable with: systemctl enable --now asl3-node-watcher"
fi

echo "Installation complete."
