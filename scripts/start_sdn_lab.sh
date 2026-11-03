#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)
python="${HOME}/selfhealnet-sdn/.venv/bin/python"
run_dir="${XDG_RUNTIME_DIR:-${HOME}/.local/run}/selfhealnet-sdn"
log_dir="${XDG_STATE_HOME:-${HOME}/.local/state}/selfhealnet-sdn"
pid_file="$run_dir/controller.pid"
log_file="$log_dir/controller.log"
openflow_host="${SDN_OPENFLOW_HOST:-127.0.0.1}"
openflow_port="${SDN_OPENFLOW_PORT:-6633}"
openflow_version="${SDN_OPENFLOW_VERSION:-OpenFlow13}"
rest_host="${SDN_CONTROLLER_REST_HOST:-127.0.0.1}"
rest_port="${SDN_CONTROLLER_REST_PORT:-8080}"
health_url="http://${rest_host}:${rest_port}/healthz"

for command_name in curl ss; do
    command -v "$command_name" >/dev/null 2>&1 || { printf 'Required command not found: %s\n' "$command_name" >&2; exit 1; }
done
[[ -x "$python" ]] || { printf 'Isolated OS-Ken Python not found: %s\n' "$python" >&2; exit 1; }
systemctl is-active --quiet openvswitch-switch || { printf 'openvswitch-switch is not active; start it manually in WSL after review.\n' >&2; exit 1; }
[[ "$openflow_version" == "OpenFlow13" ]] || { printf 'The SelfHealNet OS-Ken lab supports OpenFlow13 only.\n' >&2; exit 1; }

mkdir -p "$run_dir" "$log_dir"

if [[ -f "$pid_file" ]]; then
    old_pid=$(cat "$pid_file")
    if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
        old_cmd=$(tr '\0' ' ' < "/proc/$old_pid/cmdline" 2>/dev/null || true)
        if [[ "$old_cmd" == *"-m sdn_controller.osken_lab"* ]]; then
            if curl --silent --fail --max-time 2 "$health_url" >/dev/null; then
                if curl --silent --fail --max-time 2 "$health_url" |
                    "$python" -c 'import json, sys; health = json.load(sys.stdin); sys.exit(0 if health.get("automatic_recovery", {}).get("enabled") is True and health.get("automatic_recovery_profile") == "mininet-admin-down-port-v1" else 1)'; then
                    printf 'Controller already running with Mininet auto-recovery enabled (pid %s). Log: %s\n' "$old_pid" "$log_file"
                    exit 0
                fi
                printf 'Restarting the recorded SelfHealNet controller to enable Mininet auto-recovery.\n'
                bash "$script_dir/stop_sdn_lab.sh"
            else
                printf 'Recorded controller pid %s is alive but its health endpoint failed; refusing to start a duplicate.\n' "$old_pid" >&2
                exit 1
            fi
        fi
        if kill -0 "$old_pid" 2>/dev/null; then
            printf 'PID file points to an unrelated process (%s); refusing to signal it.\n' "$old_pid" >&2
            exit 1
        fi
    fi
    rm -f -- "$pid_file"
fi

if ss -ltn | grep -Eq "${openflow_host}:${openflow_port}([[:space:]]|$)|${rest_host}:${rest_port}([[:space:]]|$)"; then
    printf 'A required loopback port (6633 or 8080) is already in use; refusing to start.\n' >&2
    exit 1
fi

cd "$repo_root"
PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" PYTHONDONTWRITEBYTECODE=1 \
    nohup "$python" -m sdn_controller.osken_lab \
    --openflow-host "$openflow_host" --openflow-port "$openflow_port" \
    --rest-host "$rest_host" --rest-port "$rest_port" \
    --enable-lab-auto-recovery \
    >"$log_file" 2>&1 </dev/null &
pid=$!
printf '%s\n' "$pid" > "$pid_file"

for _ in {1..40}; do
    if curl --silent --fail --max-time 1 "$health_url" >/dev/null; then
        printf 'PASS OS-Ken lab controller ready (pid %s).\n' "$pid"
        printf 'OpenFlow %s: %s:%s; read-only REST with Mininet lab auto-recovery: http://%s:%s\n' "$openflow_version" "$openflow_host" "$openflow_port" "$rest_host" "$rest_port"
        printf 'Log: %s\n' "$log_file"
        exit 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        printf 'Controller exited during startup. Recent log:\n' >&2
        tail -n 60 "$log_file" >&2 || true
        rm -f -- "$pid_file"
        exit 1
    fi
    sleep 0.25
done

printf 'Controller did not become healthy. Stopping only pid %s.\n' "$pid" >&2
kill -TERM "$pid" 2>/dev/null || true
tail -n 60 "$log_file" >&2 || true
rm -f -- "$pid_file"
exit 1