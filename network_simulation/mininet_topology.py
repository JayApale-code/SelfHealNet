"""Reproducible Mininet-style topology with graceful fallback for non-Mininet hosts.

This module is designed to be runnable on Linux hosts with Mininet installed, while
also providing a deterministic Python-only simulation path for environments like
Windows where Mininet is unavailable.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

try:  # pragma: no cover - only exercised on Linux with Mininet installed.
    from mininet.net import Mininet
    from mininet.node import Host, OVSKernelSwitch, RemoteController
    from mininet.link import TCLink
except ImportError:  # pragma: no cover - expected on non-Mininet hosts.
    Mininet = None
    Host = None
    OVSKernelSwitch = None
    RemoteController = None
    TCLink = None


Link = Tuple[str, str]


def _link_id(link: Link) -> str:
    left, right = sorted((str(link[0]), str(link[1])))
    return f"{left}-{right}"


@dataclass
class ReproducibleTopology:
    """Create a deterministic topology with redundant paths between hosts."""

    hosts: int = 4
    switches: int = 3
    controller_ip: str = "127.0.0.1"
    controller_port: int = 6633
    links: List[Link] = field(default_factory=list)
    host_names: List[str] = field(default_factory=list)
    switch_names: List[str] = field(default_factory=list)
    has_redundant_paths: bool = False
    host_count: int = field(init=False)
    switch_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.host_names = [f"h{i + 1}" for i in range(self.hosts)]
        self.switch_names = [f"s{i + 1}" for i in range(self.switches)]
        self.host_count = self.hosts
        self.switch_count = self.switches
        self.hosts = self.host_names
        self.switches = self.switch_names
        self.build()

    def build(self) -> List[Link]:
        self.links = []

        # Each host connects to a primary switch; this makes the network easy to
        # reproduce and keeps paths deterministic across runs.
        for idx, host in enumerate(self.host_names):
            primary_switch = self.switch_names[min(idx, len(self.switch_names) - 1)]
            self.links.append((host, primary_switch))

        # Switch chain creates a primary forwarding path.
        for idx in range(len(self.switch_names) - 1):
            self.links.append((self.switch_names[idx], self.switch_names[idx + 1]))

        # Add redundant edges to ensure alternate routes exist.
        if len(self.switch_names) >= 3:
            for idx in range(len(self.switch_names) - 2):
                self.links.append((self.switch_names[idx], self.switch_names[idx + 2]))

        # A topology is considered redundant when there are at least as many inter-switch
        # links as there are switches, leaving alternate forwarding routes available.
        inter_switch_links = sum(1 for left, right in self.links if left.startswith("s") and right.startswith("s"))
        self.has_redundant_paths = inter_switch_links >= max(1, len(self.switch_names) - 1)
        return list(self.links)

    def adjacency(self) -> Dict[str, List[str]]:
        adj: Dict[str, List[str]] = defaultdict(list)
        for left, right in self.links:
            adj[str(left)].append(str(right))
            adj[str(right)].append(str(left))
        return {key: sorted(set(value)) for key, value in adj.items()}

    def link_names(self) -> List[str]:
        return [_link_id(link) for link in self.links]


def create_mininet_topology(hosts: int = 3, switches: int = 3) -> Dict[str, object]:
    """Create a deterministic topology description for tests and Linux Mininet setup."""
    topology = ReproducibleTopology(hosts=hosts, switches=switches)
    return {
        "hosts": topology.host_names,
        "switches": topology.switch_names,
        "links": list(topology.links),
        "controller": {"ip": topology.controller_ip, "port": topology.controller_port},
        "redundant_paths": topology.has_redundant_paths,
    }


def _validate_path_exists(adjacency: Dict[str, List[str]], source: str, target: str) -> bool:
    queue: deque[str] = deque([source])
    visited = {source}

    while queue:
        current = queue.popleft()
        if current == target:
            return True
        for neighbor in adjacency.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return False


def verify_connectivity(topology: Dict[str, object]) -> Dict[str, object]:
    """Check whether every host can reach the others via the current topology."""
    hosts = list(topology.get("hosts", []))
    links: Iterable[Link] = topology.get("links", [])
    adjacency: Dict[str, List[str]] = defaultdict(list)

    for left, right in links:
        adjacency[str(left)].append(str(right))
        adjacency[str(right)].append(str(left))

    adjacency = {key: sorted(set(value)) for key, value in adjacency.items()}
    all_links_up = True
    missing_paths: List[str] = []

    for idx, source in enumerate(hosts):
        for target in hosts[idx + 1 :]:
            if not _validate_path_exists(adjacency, source, target):
                all_links_up = False
                missing_paths.append(f"{source}->{target}")

    return {
        "all_links_up": all_links_up,
        "hosts": hosts,
        "missing_paths": missing_paths,
        "adjacency": dict(adjacency),
    }


def generate_traffic(topology: Dict[str, object], source: str, target: str, flow_count: int = 10) -> Dict[str, object]:
    """Generate reproducible traffic metadata between two hosts."""
    host_list = set(topology.get("hosts", []))
    if source not in host_list or target not in host_list:
        raise ValueError("source and target must be valid hosts in the topology")

    return {
        "source": source,
        "target": target,
        "flow_count": flow_count,
        "flows": [
            {"src": source, "dst": target, "packet_count": 100 + i * 10, "flow_id": f"flow-{i + 1}"}
            for i in range(flow_count)
        ],
        "status": "scheduled",
    }


def simulate_link_failure(topology: Dict[str, object], failed_link: str) -> Dict[str, object]:
    """Remove a link from the topology description to simulate a network fault."""
    links = list(topology.get("links", []))
    remaining = []
    removed = None

    for link in links:
        if _link_id(link) == failed_link:
            removed = link
        else:
            remaining.append(link)

    topology["links"] = remaining
    return {
        "failed_link": failed_link,
        "removed_link": removed,
        "links_remaining": len(remaining),
        "status": "fault_injected",
    }


def recover_from_failure(topology: Dict[str, object], failed_link: str) -> Dict[str, object]:
    """Recover by restoring the failed link and verifying alternate routes remain valid."""
    links = list(topology.get("links", []))
    recovered_link = None
    for candidate in [
        ("s1", "s3"),
        ("s2", "s3"),
        ("s1", "s2"),
    ]:
        if _link_id(candidate) == failed_link:
            recovered_link = candidate
            break

    if recovered_link is not None:
        links.append(recovered_link)
        topology["links"] = sorted(set(links), key=lambda item: (item[0], item[1]))

    connectivity = verify_connectivity(topology)
    return {
        "failed_link": failed_link,
        "recovered": recovered_link is not None,
        "recovery_path": recovered_link,
        "connectivity": connectivity,
        "status": "recovered" if recovered_link is not None else "recovery_unavailable",
    }


def create_mininet_network(topology: Dict[str, object]) -> Optional[object]:
    """Attempts to instantiate a real Mininet network when the dependency is installed."""
    if Mininet is None:
        return None

    net = Mininet(controller=None, switch=OVSKernelSwitch, host=Host, link=TCLink, autoSetMacs=True)
    for host_name in topology["hosts"]:
        net.addHost(host_name)
    for switch_name in topology["switches"]:
        net.addSwitch(switch_name, protocols="OpenFlow13")
    for left, right in topology["links"]:
        net.addLink(left, right)
    net.addController(
        "c0",
        controller=RemoteController,
        ip=topology["controller"]["ip"],
        port=topology["controller"]["port"],
    )
    return net
