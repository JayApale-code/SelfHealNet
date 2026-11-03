"""Topology definitions for SDN."""

from __future__ import annotations


class Topology:
    def __init__(self):
        self.nodes: list[str] = []
        self.links: list[tuple[str, str]] = []

    def add_link(self, source: str, target: str) -> None:
        self.links.append((source, target))
        if source not in self.nodes:
            self.nodes.append(source)
        if target not in self.nodes:
            self.nodes.append(target)
