#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)
venv_python="${HOME}/selfhealnet-sdn/.venv/bin/python"
failed=0

check_command() {
    if command -v "$1" >/dev/null 2>&1; then
        printf 'PASS command: %s (%s)\n' "$1" "$(command -v "$1")"
    else
        printf 'MISSING command: %s\n' "$1"
        failed=1
    fi
}

printf 'SelfHealNet SDN prerequisites (read-only)\n'
. /etc/os-release
printf 'OS: %s\n' "$PRETTY_NAME"
printf 'Kernel: %s\n' "$(uname -r)"

for command_name in mn ovs-vsctl ovs-ofctl ss curl; do
    check_command "$command_name"
done

if [[ -x "$venv_python" ]]; then
    "$venv_python" -c 'import importlib.metadata as m, os_ken; print("OS-Ken:", m.version("os-ken")); print("package:", os_ken.__file__)'
else
    printf 'MISSING isolated OS-Ken interpreter: %s\n' "$venv_python"
    failed=1
fi

if /usr/bin/python3 -c 'from mininet.net import Mininet; from mininet.node import OVSSwitch, RemoteController' >/dev/null 2>&1; then
    printf 'PASS system Python Mininet imports\n'
else
    printf 'FAIL system Python cannot import Mininet/OVS classes\n'
    failed=1
fi

if systemctl is-active --quiet openvswitch-switch; then
    printf 'PASS openvswitch-switch is active\n'
else
    printf 'FAIL openvswitch-switch is not active\n'
    failed=1
fi

if [[ ! -f "$repo_root/sdn_controller/osken_lab.py" ]]; then
    printf 'FAIL custom OS-Ken lab app is missing\n'
    failed=1
fi

if (( failed )); then
    printf '\nNo packages were installed. Review the missing prerequisites before continuing.\n' >&2
    exit 1
fi

printf '\nPASS prerequisite checks. This script made no system or network changes.\n'