# SDN lab setup on Windows with WSL2

> **Superseded:** This historical guide's Ryu 4.34 install and
> `ryu.app.*` commands are not the verified setup for the current workspace.
> Use [SDN_LAB_SETUP.md](SDN_LAB_SETUP.md), which documents the installed
> OS-Ken package and the project-owned local-only lab controller.

This guide sets up a Linux Mininet/Open vSwitch lab and a Ryu OpenFlow
controller under WSL2. The commands are instructions only; they have not been
run and this guide does not install anything automatically.

## Prerequisites

- Windows 10 version 2004/build 19041 or later, or Windows 11.
- Hardware virtualization enabled in firmware and the Windows Virtual Machine
  Platform feature available.
- Administrator access for WSL installation and reboot.
- Ubuntu 22.04 LTS in WSL2. It provides Python 3.10, which is a more suitable
  starting point for the unmaintained Ryu project than a recent Python release.
- Internet access from Ubuntu for package installation.

Microsoft's WSL installation instructions: <https://learn.microsoft.com/windows/wsl/install>.

## Install WSL2 and Ubuntu

Run in **PowerShell as Administrator**:

```powershell
wsl --status
wsl --update
wsl --set-default-version 2
wsl --install -d Ubuntu-22.04
```

Restart Windows if prompted, then launch Ubuntu 22.04 from the Start menu and
create its Linux user. Confirm the distribution and WSL version in PowerShell:

```powershell
wsl --list --verbose
```

If Ubuntu is listed with version 1, convert it:

```powershell
wsl --set-version Ubuntu-22.04 2
```

## Install Mininet and Open vSwitch

Run in the Ubuntu WSL shell:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip python3-dev \
  build-essential libffi-dev libssl-dev libxml2-dev libxslt1-dev zlib1g-dev \
  mininet openvswitch-switch
```

Start Open vSwitch and check that its daemon responds:

```bash
sudo service openvswitch-switch start
sudo ovs-vsctl show
mn --version
ovs-vsctl --version
```

Run Mininet's packaged Open vSwitch bridge smoke test:

```bash
sudo mn -c
sudo mn --switch ovsbr --test pingall
```

The test should finish with all host pairs reachable. Mininet's upstream
installation guide describes the source-install alternative if the Ubuntu
package is unsuitable: <https://mininet.org/download/>.

### WSL2 kernel limitation

Mininet needs Linux network namespaces and Open vSwitch needs a usable
datapath. WSL2 kernel/module support can vary by Windows and WSL kernel version.
If `openvswitch-switch` fails to start or the Mininet smoke test reports that
Open vSwitch is unavailable, inspect the service and kernel before proceeding:

```bash
sudo service openvswitch-switch status
sudo journalctl -u openvswitch-switch --no-pager -n 100
uname -r
sudo modprobe openvswitch
```

If the Open vSwitch kernel module is unavailable, use a supported Ubuntu VM
(the Mininet project recommends its VM for an easier setup) rather than
assuming that a successful package installation means a working switch.

## Install Ryu in a separate Python virtual environment

Keep Ryu's older dependencies isolated from SelfHealNet's Windows `.venv` and
from Ubuntu's system Python:

```bash
python3 --version
python3 -m venv ~/venvs/ryu
source ~/venvs/ryu/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install ryu
ryu-manager --version
```

Ryu's upstream quick start documents `pip install ryu` and `ryu-manager`.
**Ryu is currently unmaintained**, according to its own documentation; package
installation can fail as Python and its dependencies evolve. Do not bypass
system package protections or silently substitute another controller. Resolve
any installation error in the isolated environment first. Upstream notice and
installation guidance: <https://ryu.readthedocs.io/en/latest/getting_started.html>.

## Start Ryu and connect a real Mininet switch

Keep the Open vSwitch service running. In one Ubuntu terminal, activate the Ryu
environment and start Ryu's OpenFlow 1.3 learning-switch example on its default
OpenFlow port, 6633:

```bash
source ~/venvs/ryu/bin/activate
ryu-manager ryu.app.simple_switch_13 ryu.app.ofctl_rest ryu.app.rest_topology
```

`ofctl_rest` exposes the HTTP statistics API (typically port 8080), and
`rest_topology` exposes switch/link discovery endpoints. SelfHealNet uses these
REST APIs for read-only monitoring. TCP 6633 remains the OpenFlow connection
from the Mininet switch to Ryu; it is not an HTTP endpoint. Start SelfHealNet
with `SDN_CONTROLLER_URL` set to the reachable Ryu REST base URL, typically
`http://127.0.0.1:8080` when both run in the same network namespace.

In a second Ubuntu terminal in the **same WSL distribution**, start a two-host
Mininet topology with an OpenFlow 1.3 Open vSwitch switch and a remote Ryu
controller:

```bash
sudo mn -c
sudo mn --topo single,2 --switch ovsk,protocols=OpenFlow13 \
  --controller=remote,ip=127.0.0.1,port=6633
```

At the `mininet>` prompt, check host connectivity:

```text
pingall
```

While Mininet remains running, use a third Ubuntu terminal to verify the
controller target and installed flows:

```bash
sudo ovs-vsctl show
sudo ovs-vsctl get-controller s1
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
```

Confirm all of the following before calling the lab operational:

1. Ryu logs a switch/datapath connection.
2. `ovs-vsctl get-controller s1` reports `tcp:127.0.0.1:6633`.
3. `pingall` reports no lost host pairs.
4. `dump-flows` returns switch flow entries after traffic is sent.

Exit Mininet with `exit`; then clean up leftover Mininet state if needed:

```bash
sudo mn -c
```

## SelfHealNet integration status and safety boundary

Passing the lab checks proves only that **Ryu and Mininet can communicate**.
SelfHealNet must also be able to reach the Ryu REST base URL from its own
network namespace.

SelfHealNet verifies `/stats/switches` before reporting `CONNECTED`, then reads
port/flow statistics and topology from Ryu's REST API. `NOT CONFIGURED` means
no REST base URL is set; `DISCONNECTED` means the configured core endpoint
could not be verified. Optional topology/stat failures appear as partial
errors and are not replaced with synthetic data.

The adapter is deliberately read-only. The recovery workflow receives it
through the existing controller interface, uses observed topology for
diagnosis, and blocks switch-changing actions until write support is
deliberately implemented and approved. Verify `GET /api/v1/sdn/status` reports
`CONNECTED` with real switch IDs before describing the controller as
connected. Never send HTTP requests to port 6633.
