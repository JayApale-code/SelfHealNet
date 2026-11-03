"""Network topology simulation helpers."""

from __future__ import annotations


class NetworkTopology:
    def __init__(self):
        self.nodes: list[str] = []
        self.links: list[tuple[str, str]] = []

    def add_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            self.nodes.append(node_id)

    def add_link(self, source: str, target: str) -> None:
        self.add_node(source)
        self.add_node(target)
        self.links.append((source, target))
