#!/usr/bin/env bash
set -euo pipefail

api_root=${SELFHEALNET_API_URL:-http://127.0.0.1:8000}
command -v curl >/dev/null 2>&1 || { printf 'curl is required.\n' >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { printf 'python3 is required.\n' >&2; exit 1; }

health=$(curl --silent --show-error --fail --max-time 3 "$api_root/health") || {
    printf 'SelfHealNet health endpoint is unavailable: %s/health\n' "$api_root" >&2
    exit 1
}
printf 'Backend health: %s\n' "$health"

snapshot=$(curl --silent --show-error --fail --max-time 5 "$api_root/api/v1/sdn/status") || {
    printf 'SDN status endpoint is unavailable: %s/api/v1/sdn/status\n' "$api_root" >&2
    exit 1
}
printf '%s\n' "$snapshot" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps(d,indent=2)); assert d.get("status")=="CONNECTED", "controller is not connected"; assert d.get("source")=="os_ken_lab_rest_api", "unexpected or simulated source"; assert d.get("switches"), "no real switch is reported"; assert d.get("flow_count") is not None, "flow telemetry unavailable"'
printf 'SelfHealNet-to-OS-Ken lab verification: PASS\n'