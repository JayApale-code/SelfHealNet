#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
controller_url="${SDN_CONTROLLER_URL:-http://127.0.0.1:8080}"

for argument in "$@"; do
    if [[ "$argument" == "--persistent" ]]; then
        exec bash "$script_dir/start_mininet_sdn_lab.sh"
    fi
done

command -v sudo >/dev/null 2>&1 || { printf 'sudo is required to create Linux network namespaces.\n' >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { printf 'curl is required.\n' >&2; exit 1; }
curl --silent --show-error --fail --max-time 2 "$controller_url/healthz" >/dev/null || {
    printf 'Local OS-Ken lab controller is not healthy; run scripts/start_sdn_lab.sh first.\n' >&2
    exit 1
}

printf 'Mininet creates only h1, h2, and s1. It refuses an existing s1 bridge and tears down its own net object.\n'
printf 'No mn -c/global cleanup is run. sudo may prompt for your Ubuntu password.\n'
sudo -v
exec sudo -n /usr/bin/python3 "$script_dir/mininet_sdn_lab.py" "$@"