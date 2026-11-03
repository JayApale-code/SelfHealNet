"""Recovery actions for SDN controller."""

from __future__ import annotations


def generate_recovery_action(event: str) -> dict:
    return {"event": event, "action": "reroute_traffic"}
