"""Monitoring agent for simulation metrics."""

from __future__ import annotations


def poll_metrics() -> dict:
    return {"latency_ms": 30.0, "packet_loss_pct": 0.01, "status": "ok"}
