#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)
unit="selfhealnet-mininet.service"
controller_url="${SDN_CONTROLLER_URL:-http://127.0.0.1:8080}"
controller_host="${SDN_OPENFLOW_HOST:-127.0.0.1}"
controller_port="${SDN_OPENFLOW_PORT:-6633}"
openflow_version="${SDN_OPENFLOW_VERSION:-OpenFlow13}"
health_url="${controller_url%/}/healthz"

for command_name in curl systemctl systemd-run; do
    command -v "$command_name" >/dev/null 2>&1 || {
        printf 'Required command not found: %s\n' "$command_name" >&2
        exit 1
    }
done

systemctl is-active --quiet openvswitch-switch || {
    printf 'openvswitch-switch is not active; start the SDN controller task first.\n' >&2
    exit 1
}
curl --silent --show-error --fail --max-time 2 "$health_url" >/dev/null || {
    printf 'Local OS-Ken lab controller is not healthy; run scripts/start_sdn_lab.sh first.\n' >&2
    exit 1
}

if ! systemctl is-active --quiet "$unit"; then
    sudo -v
    if sudo -n systemctl is-failed --quiet "$unit"; then
        sudo -n systemctl reset-failed "$unit"
    fi
    sudo -n systemd-run \
        --unit="$unit" \
        --collect \
        --property="WorkingDirectory=$repo_root" \
        --property="Restart=on-failure" \
        --property="RestartSec=2s" \
        --setenv="SDN_CONTROLLER_URL=$controller_url" \
        --setenv="SDN_OPENFLOW_HOST=$controller_host" \
        --setenv="SDN_OPENFLOW_PORT=$controller_port" \
        --setenv="SDN_OPENFLOW_VERSION=$openflow_version" \
        -- /usr/bin/python3 "$script_dir/mininet_sdn_lab.py" --persistent
fi

for _ in {1..80}; do
    if ! curl --silent --fail --max-time 1 "$health_url" |
        grep -Eq '"switch_count"[[:space:]]*:[[:space:]]*[1-9][0-9]*'; then
        if ! systemctl is-active --quiet "$unit"; then
            printf 'Persistent Mininet service stopped before connecting a switch. Recent log:\n' >&2
            sudo -n journalctl --no-pager -u "$unit" -n 60 >&2 || true
            exit 1
        fi
        sleep 0.25
        continue
    fi

    printf 'SelfHealNet Mininet topology ready (systemd-managed DPID 1; OpenFlow13; h1, h2).\n'
    printf 'Persistent topology service: %s\n' "$unit"
    exit 0
done

printf 'Mininet service is active, but the controller did not discover its switch. Recent log:\n' >&2
sudo -n journalctl --no-pager -u "$unit" -n 60 >&2 || true
exit 1
