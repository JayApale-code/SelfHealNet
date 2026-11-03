from network_simulation.mininet_topology import (
    ReproducibleTopology,
    create_mininet_topology,
    simulate_link_failure,
    verify_connectivity,
)
import network_simulation.mininet_topology as mininet_topology


def test_reproducible_topology_has_expected_structure():
    topology = ReproducibleTopology(hosts=3, switches=3)
    topology.build()

    assert len(topology.hosts) == 3
    assert len(topology.switches) == 3
    assert len(topology.links) >= 5
    assert topology.has_redundant_paths is True


def test_connectivity_and_link_failure_are_reproducible():
    topology = create_mininet_topology(hosts=2, switches=2)
    assert topology["hosts"] == ["h1", "h2"]
    assert topology["switches"] == ["s1", "s2"]

    original = verify_connectivity(topology)
    assert original["all_links_up"] is True

    original_link_count = len(topology["links"])
    failed = simulate_link_failure(topology, "s1-s2")
    assert failed["failed_link"] == "s1-s2"
    assert failed["links_remaining"] == original_link_count - 1
    assert len(topology["links"]) == original_link_count - 1


def test_real_mininet_factory_uses_remote_openflow13_controller(monkeypatch):
    calls = {"switches": [], "controllers": []}

    class FakeMininet:
        def __init__(self, **kwargs):
            calls["network_options"] = kwargs

        def addHost(self, name):
            calls.setdefault("hosts", []).append(name)

        def addSwitch(self, name, **kwargs):
            calls["switches"].append((name, kwargs))

        def addLink(self, left, right):
            calls.setdefault("links", []).append((left, right))

        def addController(self, name, **kwargs):
            calls["controllers"].append((name, kwargs))

    monkeypatch.setattr(mininet_topology, "Mininet", FakeMininet)
    monkeypatch.setattr(mininet_topology, "RemoteController", object())
    topology = {
        "hosts": ["h1", "h2"],
        "switches": ["s1"],
        "links": [("h1", "s1"), ("h2", "s1")],
        "controller": {"ip": "127.0.0.1", "port": 6633},
    }

    mininet_topology.create_mininet_network(topology)

    assert calls["network_options"]["controller"] is None
    assert calls["switches"] == [("s1", {"protocols": "OpenFlow13"})]
    assert calls["controllers"][0][1]["controller"] is mininet_topology.RemoteController
    assert calls["controllers"][0][1]["ip"] == "127.0.0.1"
    assert calls["controllers"][0][1]["port"] == 6633
