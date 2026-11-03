"""Real-time monitoring service for network metrics.

The thresholds below are intentionally documented so that status decisions are not
arbitrary. They are based on common production network operating ranges:

- latency: under 50ms is healthy; 50-100ms is degraded; over 100ms is critical.
- packet loss: under 1% is normal; 1-3% is warning; over 3% is critical.
- bandwidth usage: under 70% is normal; 70-85% is warning; above 85% is critical.
- CPU and memory usage: under 70% is normal; 70-85% is warning; above 85% is critical.
- link status: 'up' is normal; 'degraded' is warning; 'down' is critical.

These thresholds are deliberately conservative for operational visibility and are
meant to be tuned for a deployed environment with historical baselines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class MonitoringService:
    """Collect, classify, and store real-time network telemetry."""

    history: List[Dict[str, Any]] = field(default_factory=list)
    collection_interval_seconds: int = 5
    status_thresholds: Dict[str, Dict[str, float]] = field(
        default_factory=lambda: {
            "latency_ms": {"normal": 50.0, "warning": 100.0},
            "packet_loss_pct": {"normal": 1.0, "warning": 3.0},
            "bandwidth_usage_pct": {"normal": 70.0, "warning": 85.0},
            "cpu_usage_pct": {"normal": 70.0, "warning": 85.0},
            "memory_usage_pct": {"normal": 70.0, "warning": 85.0},
        }
    )

    def classify_status(
        self,
        latency: float,
        packet_loss: float,
        throughput: float,
        bandwidth_usage: float,
        link_status: str,
        cpu_usage: float,
        memory_usage: float,
    ) -> str:
        """Map telemetry values to NORMAL, WARNING, or CRITICAL."""

        severity_score = 0

        if latency > self.status_thresholds["latency_ms"]["warning"]:
            severity_score += 2
        elif latency > self.status_thresholds["latency_ms"]["normal"]:
            severity_score += 1

        if packet_loss > self.status_thresholds["packet_loss_pct"]["warning"]:
            severity_score += 2
        elif packet_loss > self.status_thresholds["packet_loss_pct"]["normal"]:
            severity_score += 1

        if bandwidth_usage > self.status_thresholds["bandwidth_usage_pct"]["warning"]:
            severity_score += 2
        elif bandwidth_usage > self.status_thresholds["bandwidth_usage_pct"]["normal"]:
            severity_score += 1

        if cpu_usage > self.status_thresholds["cpu_usage_pct"]["warning"]:
            severity_score += 2
        elif cpu_usage > self.status_thresholds["cpu_usage_pct"]["normal"]:
            severity_score += 1

        if memory_usage > self.status_thresholds["memory_usage_pct"]["warning"]:
            severity_score += 2
        elif memory_usage > self.status_thresholds["memory_usage_pct"]["normal"]:
            severity_score += 1

        if link_status == "down":
            severity_score += 3
        elif link_status == "degraded":
            severity_score += 1

        if throughput <= 0:
            severity_score += 1

        if severity_score >= 6:
            return "CRITICAL"
        if severity_score >= 2:
            return "WARNING"
        return "NORMAL"

    def collect_sample(
        self,
        source: str,
        destination: str,
        latency: float,
        packet_loss: float,
        throughput: float,
        bandwidth_usage: float,
        link_status: str,
        cpu_usage: float,
        memory_usage: float,
        from_link: Optional[str] = None,
        connectivity: Optional[str] = None,
        flow_statistics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Collect and timestamp a single monitoring record."""

        status = self.classify_status(
            latency=latency,
            packet_loss=packet_loss,
            throughput=throughput,
            bandwidth_usage=bandwidth_usage,
            link_status=link_status,
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
        )

        record: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "destination": destination,
            "latency": latency,
            "packet_loss": packet_loss,
            "throughput": throughput,
            "bandwidth_usage": bandwidth_usage,
            "link_status": link_status,
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "status": status,
            "from_link": from_link,
            "connectivity": connectivity or "up",
            "flow_statistics": flow_statistics or {},
        }
        self.history.append(record)
        return record

    def collect_periodic_sample(self, source: str, destination: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Convenience wrapper for periodic polling."""
        return self.collect_sample(
            source=source,
            destination=destination,
            latency=float(metrics.get("latency", 0.0)),
            packet_loss=float(metrics.get("packet_loss", 0.0)),
            throughput=float(metrics.get("throughput", 0.0)),
            bandwidth_usage=float(metrics.get("bandwidth_usage", 0.0)),
            link_status=str(metrics.get("link_status", "up")),
            cpu_usage=float(metrics.get("cpu_usage", 0.0)),
            memory_usage=float(metrics.get("memory_usage", 0.0)),
            from_link=metrics.get("from_link"),
            connectivity=metrics.get("connectivity"),
            flow_statistics=metrics.get("flow_statistics"),
        )

    def sample(self, source: str, destination: str, **metrics: Any) -> Dict[str, Any]:
        """Alias for collection used in tests and service integrations."""
        return self.collect_periodic_sample(source, destination, metrics)
