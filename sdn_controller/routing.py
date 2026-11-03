"""Routing logic for SDN-based recovery."""

from __future__ import annotations


def compute_best_path(graph: dict, source: str, target: str) -> list[str]:
    if source == target:
        return [source]
    return [source, target] if target in graph else [source]
