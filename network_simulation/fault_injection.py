"""Fault injection helpers for simulations."""

from __future__ import annotations


def inject_fault(fault_type: str) -> dict:
    return {"fault_type": fault_type, "status": "injected"}
