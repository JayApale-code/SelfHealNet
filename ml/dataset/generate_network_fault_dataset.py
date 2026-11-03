"""Generate a controlled synthetic network-fault dataset for the prototype.

This dataset is intentionally synthetic but grounded in fault-injection scenarios
that mirror typical SDN/Mininet behavior: normal traffic, controlled congestion,
link degradation, service degradation, and connectivity loss.

It is not a claim of production accuracy; it is a college prototype dataset for
training and evaluating a fault-classification model in a controlled environment.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

LABELS = [
    "NORMAL",
    "CONGESTION",
    "LINK_FAILURE",
    "SERVICE_DEGRADATION",
    "CONNECTIVITY_FAILURE",
]

ROWS_PER_LABEL = 250
OUTPUT_PATH = Path(__file__).with_name("network_fault_dataset.csv")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_normal(rng: random.Random):
    return {
        "latency_ms": rng.uniform(8, 35),
        "jitter_ms": rng.uniform(1, 6),
        "packet_loss_pct": rng.uniform(0.05, 0.8),
        "throughput_mbps": rng.uniform(75, 145),
        "bandwidth_utilization_pct": rng.uniform(18, 60),
        "cpu_utilization_pct": rng.uniform(20, 55),
        "memory_utilization_pct": rng.uniform(28, 60),
        "active_flows": rng.randint(20, 180),
        "retransmissions_pct": rng.uniform(0.2, 1.2),
        "dropped_packets": rng.randint(0, 8),
        "link_status": "up",
        "route_redundancy": rng.randint(2, 4),
        "connectivity_score": rng.uniform(0.9, 1.0),
        "fault_scenario": "baseline_healthy",
    }


def build_congestion(rng: random.Random):
    return {
        "latency_ms": rng.uniform(55, 120),
        "jitter_ms": rng.uniform(8, 25),
        "packet_loss_pct": rng.uniform(1.5, 4.0),
        "throughput_mbps": rng.uniform(20, 70),
        "bandwidth_utilization_pct": rng.uniform(75, 96),
        "cpu_utilization_pct": rng.uniform(55, 88),
        "memory_utilization_pct": rng.uniform(50, 80),
        "active_flows": rng.randint(120, 350),
        "retransmissions_pct": rng.uniform(2.0, 8.0),
        "dropped_packets": rng.randint(8, 80),
        "link_status": "degraded",
        "route_redundancy": rng.randint(1, 2),
        "connectivity_score": rng.uniform(0.6, 0.9),
        "fault_scenario": "controlled_congestion",
    }


def build_link_failure(rng: random.Random):
    return {
        "latency_ms": rng.uniform(120, 500),
        "jitter_ms": rng.uniform(25, 120),
        "packet_loss_pct": rng.uniform(3.0, 12.0),
        "throughput_mbps": rng.uniform(0, 20),
        "bandwidth_utilization_pct": rng.uniform(45, 90),
        "cpu_utilization_pct": rng.uniform(60, 90),
        "memory_utilization_pct": rng.uniform(58, 85),
        "active_flows": rng.randint(40, 160),
        "retransmissions_pct": rng.uniform(5.0, 20.0),
        "dropped_packets": rng.randint(50, 420),
        "link_status": "down",
        "route_redundancy": rng.randint(0, 1),
        "connectivity_score": rng.uniform(0.2, 0.6),
        "fault_scenario": "fault_injected_link_drop",
    }


def build_service_degradation(rng: random.Random):
    return {
        "latency_ms": rng.uniform(50, 160),
        "jitter_ms": rng.uniform(7, 30),
        "packet_loss_pct": rng.uniform(0.8, 2.2),
        "throughput_mbps": rng.uniform(30, 85),
        "bandwidth_utilization_pct": rng.uniform(62, 82),
        "cpu_utilization_pct": rng.uniform(60, 82),
        "memory_utilization_pct": rng.uniform(65, 88),
        "active_flows": rng.randint(90, 240),
        "retransmissions_pct": rng.uniform(1.5, 6.0),
        "dropped_packets": rng.randint(10, 120),
        "link_status": "degraded",
        "route_redundancy": rng.randint(1, 3),
        "connectivity_score": rng.uniform(0.7, 0.9),
        "fault_scenario": "application_or_service_degradation",
    }


def build_connectivity_failure(rng: random.Random):
    return {
        "latency_ms": rng.uniform(200, 1200),
        "jitter_ms": rng.uniform(50, 180),
        "packet_loss_pct": rng.uniform(10, 30),
        "throughput_mbps": rng.uniform(0, 8),
        "bandwidth_utilization_pct": rng.uniform(10, 35),
        "cpu_utilization_pct": rng.uniform(50, 90),
        "memory_utilization_pct": rng.uniform(55, 90),
        "active_flows": rng.randint(30, 110),
        "retransmissions_pct": rng.uniform(12.0, 35.0),
        "dropped_packets": rng.randint(120, 700),
        "link_status": "down",
        "route_redundancy": 0,
        "connectivity_score": rng.uniform(0.0, 0.25),
        "fault_scenario": "controlled_connectivity_loss",
    }


BUILDERS = {
    "NORMAL": build_normal,
    "CONGESTION": build_congestion,
    "LINK_FAILURE": build_link_failure,
    "SERVICE_DEGRADATION": build_service_degradation,
    "CONNECTIVITY_FAILURE": build_connectivity_failure,
}

FIELDNAMES = [
    "label",
    "source",
    "destination",
    "latency_ms",
    "jitter_ms",
    "packet_loss_pct",
    "throughput_mbps",
    "bandwidth_utilization_pct",
    "cpu_utilization_pct",
    "memory_utilization_pct",
    "active_flows",
    "retransmissions_pct",
    "dropped_packets",
    "link_status",
    "route_redundancy",
    "connectivity_score",
    "fault_scenario",
]


def make_row(label: str, idx: int, rng: random.Random):
    source = f"h{(idx % 4) + 1}"
    destination = f"h{((idx % 4) + 1) % 4 + 1}"
    data = BUILDERS[label](rng)
    return {
        "label": label,
        "source": source,
        "destination": destination,
        "latency_ms": round(data["latency_ms"], 3),
        "jitter_ms": round(data["jitter_ms"], 3),
        "packet_loss_pct": round(data["packet_loss_pct"], 3),
        "throughput_mbps": round(data["throughput_mbps"], 3),
        "bandwidth_utilization_pct": round(data["bandwidth_utilization_pct"], 3),
        "cpu_utilization_pct": round(data["cpu_utilization_pct"], 3),
        "memory_utilization_pct": round(data["memory_utilization_pct"], 3),
        "active_flows": data["active_flows"],
        "retransmissions_pct": round(data["retransmissions_pct"], 3),
        "dropped_packets": data["dropped_packets"],
        "link_status": data["link_status"],
        "route_redundancy": data["route_redundancy"],
        "connectivity_score": round(clamp(data["connectivity_score"], 0.0, 1.0), 3),
        "fault_scenario": data["fault_scenario"],
    }


def generate_dataset() -> list[dict[str, object]]:
    rng = random.Random(42)
    rows: list[dict[str, object]] = []

    for label in LABELS:
        for idx in range(ROWS_PER_LABEL):
            rows.append(make_row(label, idx, rng))

    rng.shuffle(rows)
    return rows


def write_csv(rows: list[dict[str, object]]) -> None:
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    rows = generate_dataset()
    write_csv(rows)
    print(f"Wrote {len(rows)} records to {OUTPUT_PATH}")
