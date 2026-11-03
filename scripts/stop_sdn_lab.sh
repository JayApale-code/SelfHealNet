#!/usr/bin/env bash
set -euo pipefail

run_dir="${XDG_RUNTIME_DIR:-${HOME}/.local/run}/selfhealnet-sdn"
pid_file="$run_dir/controller.pid"

if [[ ! -f "$pid_file" ]]; then
    printf 'No SelfHealNet lab controller PID file; nothing was stopped.\n'
    exit 0
fi

pid=$(cat "$pid_file")
if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
    printf 'Invalid controller PID file; refusing to signal any process.\n' >&2
    exit 1
fi
if ! kill -0 "$pid" 2>/dev/null; then
    rm -f -- "$pid_file"
    printf 'Recorded controller is already stopped.\n'
    exit 0
fi

cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
if [[ "$cmdline" != *"-m sdn_controller.osken_lab"* ]]; then
    printf 'PID %s is not the SelfHealNet lab controller; refusing to signal it.\n' "$pid" >&2
    exit 1
fi

kill -TERM "$pid"
for _ in {1..40}; do
    if ! kill -0 "$pid" 2>/dev/null; then
        rm -f -- "$pid_file"
        printf 'Stopped SelfHealNet lab controller pid %s. No Mininet cleanup was run.\n' "$pid"
        exit 0
    fi
    sleep 0.25
done

printf 'Controller pid %s did not exit after SIGTERM; no force-kill was attempted.\n' "$pid" >&2
exit 1