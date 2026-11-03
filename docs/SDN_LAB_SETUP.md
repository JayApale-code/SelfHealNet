# SelfHealNet Isolated WSL2 SDN Lab

This lab uses the installed `os-ken==4.2.2` Python 3.10 environment and the
Ubuntu Mininet/Open vSwitch packages. The published OS-Ken wheel has no
`osken-manager`, `os_ken.cmd.manager`, `simple_switch_13`, `ofctl_rest`, or
`rest_topology` files. SelfHealNet therefore supplies a small local-only
OpenFlow 1.3 learning switch and read-only REST surface in
`sdn_controller/osken_lab.py`; it does not claim to be Ryu.

The controller listens only on WSL loopback: OpenFlow TCP `6633`, REST HTTP
`8080`. Its GET API follows the existing adapter's Ryu-compatible response
shape, and labels itself `os_ken_lab_rest_api`. The startup script enables a
single fixed OpenFlow recovery action: clear the administrative-down flag on
the two host-facing ports of DPID 1 (`s1-eth1` and `s1-eth2`). The controller
does not expose REST writes or accept arbitrary switch, port, flow, or routing
commands.

## Prerequisites

- Run commands from the Ubuntu 22.04 WSL shell at the mounted project root:
  `/mnt/c/Users/VICTUS/OneDrive/Documents/Desktop/SELF-HEALING`.
- The isolated controller interpreter must be
  `~/selfhealnet-sdn/.venv/bin/python` and contain `os-ken==4.2.2`.
- Mininet, Open vSwitch, `curl`, and `ss` must already be installed; the
  Open vSwitch service must be active.
- The Mininet test requires `sudo` for Linux network namespaces and OVS bridge
  creation. It prompts for the Ubuntu user's password; no password is embedded
  in scripts. No Windows administrator elevation is used.

Run the read-only prerequisite checker:

```bash
bash scripts/setup_sdn_lab.sh
```

It does not install packages or start services. If prerequisites are missing,
it reports them; review any package installation separately before proceeding.

## Start, Test, Stop

Start the controller as the normal WSL user:

```bash
bash scripts/start_sdn_lab.sh
```

The process and log are recorded under `~/.local/run/selfhealnet-sdn` and
`~/.local/state/selfhealnet-sdn`, outside the project. A second start recognizes
the same process; a port conflict or unrelated PID is reported rather than
killed.

Run the isolated topology test:

```bash
bash scripts/test_sdn_lab.sh
```

The test refuses to run if an unmanaged OVS bridge named `s1` already exists.
It creates two hosts (`h1`, `h2`) and one switch (`s1`, DPID 1), explicitly
connects `s1` to `127.0.0.1:6633` using OpenFlow 1.3, runs `pingall`, and
verifies controller discovery and real port/flow statistics. It then
administratively disables port 1, verifies the controller restores it, and
confirms `pingall` returns to 0% packet loss. It dumps flows with `ovs-ofctl`,
then stops only the Mininet network object it created. It never runs `mn -c`
or cleans up unrelated bridges.

Start the persistent topology as a systemd-managed WSL service:

```bash
bash scripts/test_sdn_lab.sh --persistent
```

When the service is not already running, the command asks for the Ubuntu
password once, then starts the managed topology outside the VS Code task
process and waits for the controller to discover its switch. Closing VS Code
no longer tears down the Mininet network. Starting the project again reuses
the service and verifies that the switch is connected without asking for
elevation again. To stop only this lab topology, run
`sudo systemctl stop selfhealnet-mininet.service`. The controller remains
running separately.

Stop only the recorded controller process:

```bash
bash scripts/stop_sdn_lab.sh
```

The controller's HTTP API is GET-only; writes return HTTP 405. The app reports
only datapaths and stats received over OpenFlow. With no connected switch,
`/stats/switches` returns an empty list. `/healthz` exposes whether the
fixed Mininet port recovery is enabled and its last result.

## Connect SelfHealNet

In the PowerShell session used to start the backend, set these process-local
values (do not create `.env`):

```powershell
$env:SDN_CONTROLLER_URL = "http://127.0.0.1:8080"
$env:SDN_CONTROLLER_TYPE = "os_ken_lab"
```

For verification, point `DATABASE_URL` at a disposable database outside the
project before starting the backend. Backend startup creates/updates schema and
the monitoring workers persist data; do not use the production database for
this integration test. `MODEL_PATH` should continue pointing at the preserved
artifact and must not be used by training commands.

With the backend and lab controller running, from WSL:

```bash
bash scripts/verify_selfhealnet.sh
```

The check requires `/api/v1/sdn/status` to say `CONNECTED`, source
`os_ken_lab_rest_api`, at least one discovered switch, and a flow count. It does
not create telemetry or incidents.

## Limits and Safety

- This is a one-switch learning-switch lab; topology links are correctly empty.
- Automatic recovery is limited to administratively disabled host-facing lab
  ports. It cannot repair a physically disconnected cable, create an alternate
  route, remediate arbitrary faults, or manage the physical Wi-Fi/router.
- The adapter's `write_operations_enabled` remains false for generic workflow
  writes. This does not enable ML-selected actions or arbitrary recovery
  workflows; only the fixed in-controller Mininet port repair is automatic.
- The controller listens on loopback and checks the switch DPID and exact
  `s1-eth1`/`s1-eth2` port mapping before issuing the port change. The Mininet
  test separately checks the OVS bridge marker before reusing an existing `s1`.
- The OVS kernel datapath can vary by WSL kernel. A package or active service
  alone is not proof; the `pingall` and flow/port checks are the acceptance
  evidence. If the test fails due to kernel/namespace limitations, stop and use
  a supported Linux VM/host rather than broad cleanup commands.
- Keep SelfHealNet's SQLite database and model unchanged during lab tests.