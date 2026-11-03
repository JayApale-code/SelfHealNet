#!/usr/bin/env python3
"""Run one isolated two-host/one-switch Mininet test and clean up that net only."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from argparse import ArgumentParser
from urllib.request import urlopen


CONTROLLER_HOST = os.getenv("SDN_OPENFLOW_HOST", "127.0.0.1")
OPENFLOW_PORT = int(os.getenv("SDN_OPENFLOW_PORT", "6633"))
OPENFLOW_VERSION = os.getenv("SDN_OPENFLOW_VERSION", "OpenFlow13")
REST_BASE = os.getenv("SDN_CONTROLLER_URL", "http://127.0.0.1:8080").rstrip("/")
LAB_MARKER = "selfhealnet-mininet-v1"


def get_json(path: str) -> object:
    with urlopen(f"{REST_BASE}{path}", timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def ovs_read(*args: str) -> str:
    result = subprocess.run(
        ["ovs-vsctl", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def wait_for_port_recovery(
    port_no: int,
    previous_attempts: int | None = None,
    timeout: float = 8.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = get_json("/healthz")
        recovery = payload.get("automatic_recovery", {}) if isinstance(payload, dict) else {}
        attempts = recovery.get("attempts", 0) if isinstance(recovery, dict) else 0
        recovered = previous_attempts is None or (
            isinstance(attempts, int)
            and attempts > previous_attempts
            and recovery.get("last_result") == "verified"
            and recovery.get("last_port") == f"1:s1-eth{port_no}"
        )
        if recovered:
            port_payload = get_json(f"/stats/portdesc/1")
            ports = port_payload.get("1", []) if isinstance(port_payload, dict) else []
            port = next(
                (item for item in ports if isinstance(item, dict) and item.get("port_no") == port_no),
                None,
            ) if isinstance(ports, list) else None
            if (
                port is not None
                and isinstance(port.get("config"), int)
                and not port["config"] & 1
                and isinstance(port.get("state"), int)
                and port["state"] & 4
            ):
                return port
        time.sleep(0.1)
    raise RuntimeError(f"Controller did not restore Mininet switch port {port_no} within {timeout:g}s")


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--persistent", action="store_true")
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("This test must run as root (the shell wrapper uses sudo).", file=sys.stderr)
        return 2
    if OPENFLOW_VERSION != "OpenFlow13":
        print("The SelfHealNet lab currently supports OpenFlow13 only.", file=sys.stderr)
        return 2

    try:
        health = get_json("/healthz")
    except Exception as exc:
        print(f"Controller REST health check failed: {exc}", file=sys.stderr)
        return 2
    if health.get("controller") != "os-ken-lab":
        print(f"Unexpected controller identity: {health!r}", file=sys.stderr)
        return 2
    automatic_recovery = health.get("automatic_recovery")
    if not isinstance(automatic_recovery, dict) or not automatic_recovery.get("enabled"):
        print("OS-Ken lab controller does not have Mininet auto-recovery enabled.", file=sys.stderr)
        return 2

    try:
        existing_bridges = ovs_read("list-br").splitlines()
    except subprocess.CalledProcessError as exc:
        print(f"Cannot read OVS bridges: {exc.stderr.strip()}", file=sys.stderr)
        return 2
    if "s1" in existing_bridges:
        marker = ovs_read("get", "Bridge", "s1", "external_ids:selfhealnet").strip('"')
        controller = ovs_read("get-controller", "s1")
        protocols = ovs_read("get", "Bridge", "s1", "protocols")
        expected_controller = f"tcp:{CONTROLLER_HOST}:{OPENFLOW_PORT}"
        if not args.persistent or marker != LAB_MARKER:
            print("OVS bridge s1 already exists and is not a managed SelfHealNet lab; refusing to modify it.", file=sys.stderr)
            return 2
        if expected_controller not in controller or OPENFLOW_VERSION not in protocols:
            print("Existing SelfHealNet bridge has a controller or OpenFlow version mismatch; refusing to modify it.", file=sys.stderr)
            return 2
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if 1 in get_json("/stats/switches"):
                print("SelfHealNet Mininet topology ready (existing DPID 1; no duplicate network created).", flush=True)
                return 0
            time.sleep(0.25)
        print("Managed OVS bridge s1 exists but has not reconnected to the controller.", file=sys.stderr)
        return 2

    from mininet.net import Mininet
    from mininet.node import OVSSwitch, RemoteController
    from mininet.topo import Topo

    class LabTopo(Topo):
        def build(self) -> None:
            switch = self.addSwitch(
                "s1",
                dpid="0000000000000001",
                protocols=OPENFLOW_VERSION,
                failMode="secure",
            )
            left = self.addHost("h1")
            right = self.addHost("h2")
            self.addLink(left, switch)
            self.addLink(right, switch)

    net = Mininet(
        topo=LabTopo(),
        controller=None,
        switch=OVSSwitch,
        autoSetMacs=True,
        autoStaticArp=True,
        build=False,
    )
    net.addController("c0", controller=RemoteController, ip=CONTROLLER_HOST, port=OPENFLOW_PORT)
    stop_requested = threading.Event()
    try:
        net.start()
        ovs_read("set", "Bridge", "s1", f"external_ids:selfhealnet={LAB_MARKER}")
        configured = ovs_read("get-controller", "s1")
        expected = f"tcp:{CONTROLLER_HOST}:{OPENFLOW_PORT}"
        print(f"Configured switch controller: {configured}")
        if expected not in configured:
            raise RuntimeError(f"s1 controller is not {expected}")

        loss = net.pingAll()
        print(f"Mininet pingall loss: {loss}%")
        if loss != 0:
            raise RuntimeError(f"pingall reported {loss}% packet loss")

        deadline = time.monotonic() + 12
        switches: list[object] = []
        ports: dict[str, object] = {}
        flows: dict[str, object] = {}
        while time.monotonic() < deadline:
            switches = get_json("/stats/switches")
            ports = get_json("/stats/port/1")
            flows = get_json("/stats/flow/1")
            if 1 in switches and len(flows.get("1", [])) > 1 and flows.get("1") and ports.get("1"):
                break
            time.sleep(0.25)

        if 1 not in switches:
            raise RuntimeError(f"Controller did not discover DPID 1: {switches!r}")
        if len(flows.get("1", [])) <= 1:
            raise RuntimeError(f"Controller did not return learned flow entries: {flows!r}")
        if not ports.get("1"):
            raise RuntimeError(f"Controller did not return port statistics: {ports!r}")

        if not args.persistent:
            initial_health = get_json("/healthz")
            initial_recovery = initial_health.get("automatic_recovery", {})
            previous_attempts = initial_recovery.get("attempts", 0)
            if not isinstance(previous_attempts, int):
                raise RuntimeError(f"Controller returned invalid auto-recovery status: {initial_recovery!r}")

            wait_for_port_recovery(1)
            subprocess.run(
                ["ovs-ofctl", "-O", "OpenFlow13", "mod-port", "s1", "1", "down"],
                check=True,
                capture_output=True,
                text=True,
            )
            recovered_port = wait_for_port_recovery(1, previous_attempts)
            recovered_loss = net.pingAll()
            if recovered_loss != 0:
                raise RuntimeError(f"Mininet connectivity did not recover after restoring port 1: {recovered_loss}% loss")
            print(
                "Live auto-recovery: PASS "
                f"(cleared admin-down on s1 port 1; state={recovered_port.get('state')}; pingall loss={recovered_loss}%)."
            )

        dump = subprocess.run(
            ["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", "s1"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if "actions=" not in dump:
            raise RuntimeError("ovs-ofctl returned no flow entries")

        print(f"OpenFlow discovery: PASS (DPID 1; REST switches={switches})")
        print(f"Controller port telemetry entries: {len(ports['1'])}")
        print(f"Controller flow telemetry entries: {len(flows['1'])}")
        if args.persistent:
            signal.signal(signal.SIGINT, lambda *_: stop_requested.set())
            signal.signal(signal.SIGTERM, lambda *_: stop_requested.set())
            print("SelfHealNet Mininet topology ready (DPID 1; OpenFlow13; h1, h2).", flush=True)
            stop_requested.wait()
            return 0
        print("ovs-ofctl dump-flows s1:")
        print(dump.rstrip())
        print("SDN lab test: PASS")
        return 0
    finally:
        net.stop()
        print("Stopped only the Mininet network created by this process.")


if __name__ == "__main__":
    raise SystemExit(main())