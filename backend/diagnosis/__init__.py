# diagnosis/__init__.py - Fault Diagnosis Engine

from typing import Any, Dict, List, Mapping, Optional
import logging
from datetime import datetime

try:
    from ..database import SessionLocal
except ImportError:
    try:
        from database import SessionLocal
    except ImportError:
        SessionLocal = None

logger = logging.getLogger(__name__)


class DiagnosisEngine:
    """
    Analyzes network incidents and determines root causes.
    Uses metrics, topology analysis, and correlation logic.
    """
    
    def __init__(self, db_session=None):
        self.db = db_session

    def diagnose(
        self,
        live_metrics: Mapping[str, Any],
        ml_prediction: Mapping[str, Any],
        topology: Any,
        affected_node: Optional[str] = None,
        affected_link: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Diagnose a fault from telemetry, ML evidence, and topology context.

        The rule scores are deliberately visible in the returned evidence so a
        diagnosis can be audited without treating the ML prediction as a cause.
        Metric names from both the monitoring service and the legacy collector
        are accepted.
        """
        metrics = self._normalize_metrics(live_metrics)
        prediction_label = str(
            ml_prediction.get("label", ml_prediction.get("fault_type", "NORMAL"))
        ).upper()
        prediction_probability = self._bounded_float(
            ml_prediction.get(
                "probability",
                ml_prediction.get("confidence", 0.0),
            )
        )
        component = affected_link or affected_node or "unknown"
        scores = {
            "LINK_FAILURE": 0.0,
            "CONNECTIVITY_FAILURE": 0.0,
            "CONGESTION": 0.0,
            "SERVICE_DEGRADATION": 0.0,
            "NORMAL": 0.0,
        }
        evidence: Dict[str, List[Dict[str, Any]]] = {
            fault_type: [] for fault_type in scores
        }

        def add(fault_type: str, points: float, metric: str, value: Any, reason: str) -> None:
            scores[fault_type] += points
            evidence[fault_type].append({
                "metric": metric,
                "value": value,
                "reason": reason,
            })

        link_status = str(metrics.get("link_status", "unknown")).lower()
        connectivity = str(metrics.get("connectivity", "unknown")).lower()
        if link_status == "down":
            add("LINK_FAILURE", 5.0, "link_status", link_status, "link is down")
        if connectivity in {"down", "failed", "unreachable"}:
            add("CONNECTIVITY_FAILURE", 5.0, "connectivity", connectivity, "endpoint is unreachable")
        if metrics["packet_loss_pct"] is not None and metrics["packet_loss_pct"] >= 10:
            add("LINK_FAILURE", 3.0, "packet_loss_pct", metrics["packet_loss_pct"], "packet loss is critically high")
        elif metrics["throughput_mbps"] is not None and metrics["throughput_mbps"] <= 0:
            add("LINK_FAILURE", 3.0, "throughput_mbps", metrics["throughput_mbps"], "measured throughput is zero")
        if metrics["connectivity_score"] is not None and metrics["connectivity_score"] < 0.5:
            add("CONNECTIVITY_FAILURE", 3.0, "connectivity_score", metrics["connectivity_score"], "connectivity score is critically low")
        elif metrics["route_redundancy"] is not None and metrics["route_redundancy"] <= 0:
            add("CONNECTIVITY_FAILURE", 3.0, "route_redundancy", metrics["route_redundancy"], "no redundant route is available")

        if metrics["bandwidth_utilization_pct"] is not None and metrics["bandwidth_utilization_pct"] >= 85:
            add("CONGESTION", 3.0, "bandwidth_utilization_pct", metrics["bandwidth_utilization_pct"], "utilization exceeds 85%")
        if metrics["latency_ms"] is not None and metrics["latency_ms"] > 100:
            add("CONGESTION", 2.0, "latency_ms", metrics["latency_ms"], "latency is critically elevated")
        elif metrics["latency_ms"] is not None and metrics["latency_ms"] > 50:
            add("CONGESTION", 1.0, "latency_ms", metrics["latency_ms"], "latency is elevated")
        if metrics["packet_loss_pct"] is not None and metrics["packet_loss_pct"] > 1:
            add("CONGESTION", 1.0, "packet_loss_pct", metrics["packet_loss_pct"], "packet loss indicates queue pressure")
        if (
            metrics["cpu_utilization_pct"] is not None and metrics["cpu_utilization_pct"] >= 85
        ) or (
            metrics["memory_utilization_pct"] is not None and metrics["memory_utilization_pct"] >= 85
        ):
            add("SERVICE_DEGRADATION", 2.0, "resource_utilization", {
                "cpu_pct": metrics["cpu_utilization_pct"],
                "memory_pct": metrics["memory_utilization_pct"],
            }, "node resources are critically utilized")
        if (
            metrics["latency_ms"] is not None and metrics["latency_ms"] > 50
        ) or (
            metrics["packet_loss_pct"] is not None and metrics["packet_loss_pct"] > 1
        ):
            add("SERVICE_DEGRADATION", 1.0, "latency_and_loss", {
                "latency_ms": metrics["latency_ms"],
                "packet_loss_pct": metrics["packet_loss_pct"],
            }, "service quality is degraded")

        if prediction_label in scores and prediction_label != "NORMAL":
            add(prediction_label, 2.0 * prediction_probability, "ml_prediction", prediction_label, f"ML model probability is {prediction_probability:.2f}")
        elif prediction_label == "NORMAL" and prediction_probability >= 0.8:
            scores["NORMAL"] += 1.0

        topology_context = self._topology_context(topology, affected_node, affected_link)
        if topology_context["component_known"]:
            for fault_type in ("LINK_FAILURE", "CONNECTIVITY_FAILURE"):
                scores[fault_type] += 0.5

        fault_type = max(scores, key=scores.get)
        if scores[fault_type] == 0:
            fault_type = "NORMAL"
        severity = self._severity(fault_type, metrics, scores[fault_type])
        supporting_metrics = evidence[fault_type]
        explanation = self._explanation(fault_type, supporting_metrics)
        confidence = self._confidence(scores, fault_type, prediction_probability)

        return {
            "fault_type": fault_type,
            "affected_component": component,
            "severity": severity,
            "confidence": confidence,
            "supporting_metrics": supporting_metrics,
            "explanation": explanation,
            "topology_context": topology_context,
        }

    @staticmethod
    def _bounded_float(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _normalize_metrics(cls, metrics: Mapping[str, Any]) -> Dict[str, Any]:
        def optional_number(*names: str) -> Optional[float]:
            for name in names:
                if name in metrics:
                    try:
                        return float(metrics[name])
                    except (TypeError, ValueError):
                        continue
            return None

        return {
            "latency_ms": optional_number("latency_ms", "latency", "latency_mean"),
            "packet_loss_pct": optional_number("packet_loss_pct", "packet_loss", "packet_loss_mean"),
            "throughput_mbps": optional_number("throughput_mbps", "throughput"),
            "bandwidth_utilization_pct": optional_number("bandwidth_utilization_pct", "bandwidth_usage", "bandwidth_util"),
            "cpu_utilization_pct": optional_number("cpu_utilization_pct", "cpu_usage"),
            "memory_utilization_pct": optional_number("memory_utilization_pct", "memory_usage"),
            "connectivity_score": optional_number("connectivity_score"),
            "route_redundancy": optional_number("route_redundancy"),
            "link_status": metrics.get("link_status", "unknown"),
            "connectivity": metrics.get("connectivity", "unknown"),
        }

    @staticmethod
    def _topology_context(topology: Any, node: Optional[str], link: Optional[str]) -> Dict[str, Any]:
        nodes = topology.get("nodes", []) if isinstance(topology, Mapping) else getattr(topology, "nodes", [])
        links = topology.get("links", []) if isinstance(topology, Mapping) else getattr(topology, "links", [])
        normalized_links = [list(item) if isinstance(item, (tuple, list)) else item for item in links]
        node_known = node in nodes if node else False
        link_known = link in links or link in normalized_links if link else False
        return {
            "node_known": node_known,
            "link_known": link_known,
            "component_known": node_known or link_known,
            "node_degree": sum(node in item for item in normalized_links if isinstance(item, list)) if node else 0,
        }

    @staticmethod
    def _severity(fault_type: str, metrics: Mapping[str, Any], score: float) -> str:
        if fault_type == "NORMAL":
            return "LOW"
        if fault_type in {"LINK_FAILURE", "CONNECTIVITY_FAILURE"}:
            return "CRITICAL"
        if (
            score >= 5
            or (metrics["latency_ms"] is not None and metrics["latency_ms"] > 100)
            or (metrics["packet_loss_pct"] is not None and metrics["packet_loss_pct"] > 3)
        ):
            return "HIGH"
        return "MEDIUM"

    @staticmethod
    def _confidence(scores: Mapping[str, float], fault_type: str, ml_probability: float) -> float:
        total = sum(scores.values())
        margin = scores[fault_type] - max((score for name, score in scores.items() if name != fault_type), default=0.0)
        confidence = 0.5 + min(scores[fault_type] / 10, 0.3) + min(max(margin, 0.0) / 10, 0.15)
        if fault_type != "NORMAL":
            confidence = max(confidence, ml_probability)
        return round(max(0.0, min(1.0, confidence if total else 0.95)), 3)

    @staticmethod
    def _explanation(fault_type: str, evidence: List[Dict[str, Any]]) -> str:
        if not evidence:
            return "No fault indicators exceeded the diagnosis thresholds."
        details = "; ".join(item["reason"] for item in evidence)
        return f"{fault_type} is supported by {details}."
    
    def diagnose_incident(
        self,
        incident_id: str,
        affected_node: str,
        incident_type: str,
        metrics: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Diagnose an incident and determine root cause.
        
        Args:
            incident_id: Unique incident identifier
            affected_node: Node experiencing the issue
            incident_type: Type of incident (link_failure, congestion, etc.)
            metrics: Current network metrics
            
        Returns:
            Diagnosis result with root cause and recommendations
        """
        diagnosis = {
            "incident_id": incident_id,
            "timestamp": datetime.utcnow().isoformat(),
            "affected_node": affected_node,
            "incident_type": incident_type,
            "root_cause": None,
            "severity": "medium",
            "affected_services": [],
            "recommendation": None,
            "confidence": 0.0
        }
        
        # Analyze based on incident type
        if incident_type == "link_failure":
            diagnosis.update(self._diagnose_link_failure(affected_node, metrics))
        elif incident_type == "congestion":
            diagnosis.update(self._diagnose_congestion(affected_node, metrics))
        elif incident_type == "high_latency":
            diagnosis.update(self._diagnose_high_latency(affected_node, metrics))
        elif incident_type == "packet_loss":
            diagnosis.update(self._diagnose_packet_loss(affected_node, metrics))
        elif incident_type == "anomaly":
            diagnosis.update(self._diagnose_anomaly(affected_node, metrics))
        else:
            diagnosis["root_cause"] = f"Unknown incident type: {incident_type}"
            diagnosis["confidence"] = 0.3
        
        return diagnosis
    
    def _diagnose_link_failure(self, node_id: str, metrics: Dict) -> Dict:
        """Diagnose link failure"""
        return {
            "root_cause": f"Physical or logical link failure on node {node_id}",
            "severity": "critical",
            "affected_services": self._get_affected_services(node_id),
            "recommendation": f"Check physical connections on {node_id}. Restart interface if needed. Consider rerouting traffic.",
            "confidence": 0.95,
            "reasoning": {
                "indicators": [
                    "Complete packet loss or extreme latency",
                    "No response from node",
                    "BGP session down"
                ]
            }
        }
    
    def _diagnose_congestion(self, node_id: str, metrics: Dict) -> Dict:
        """Diagnose network congestion"""
        return {
            "root_cause": f"Network congestion on node {node_id}",
            "severity": "high",
            "affected_services": self._get_affected_services(node_id),
            "recommendation": f"Increase capacity on {node_id}. QoS traffic shaping. Route traffic away from congested links.",
            "confidence": 0.90,
            "reasoning": {
                "indicators": [
                    f"High bandwidth utilization: {metrics.get('bandwidth_util', 0):.1f}%",
                    "Increased latency and packet loss",
                    "Buffer queue buildup"
                ]
            }
        }
    
    def _diagnose_high_latency(self, node_id: str, metrics: Dict) -> Dict:
        """Diagnose high latency"""
        latency = metrics.get('latency_mean', 0)
        
        if latency > 100:
            reason = "Possible long-distance link or routing inefficiency"
        elif latency > 50:
            reason = "Elevated but acceptable - possible congestion or processing delays"
        else:
            reason = "Latency within normal range - possible transient spike"
        
        return {
            "root_cause": f"High latency on {node_id}: {reason}",
            "severity": "medium",
            "affected_services": self._get_affected_services(node_id),
            "recommendation": "Check routing path. Verify link quality. Consider optimization.",
            "confidence": 0.75,
            "reasoning": {
                "indicators": [
                    f"Latency mean: {latency:.1f}ms",
                    "May indicate routing loop or suboptimal path",
                ]
            }
        }
    
    def _diagnose_packet_loss(self, node_id: str, metrics: Dict) -> Dict:
        """Diagnose packet loss"""
        packet_loss = metrics.get('packet_loss_mean', 0)
        
        if packet_loss > 5:
            severity = "critical"
        elif packet_loss > 1:
            severity = "high"
        else:
            severity = "medium"
        
        return {
            "root_cause": f"Packet loss detected on {node_id}",
            "severity": severity,
            "affected_services": self._get_affected_services(node_id),
            "recommendation": "Check link quality (CRC errors). Verify buffer size. Consider link replacement.",
            "confidence": 0.85,
            "reasoning": {
                "indicators": [
                    f"Packet loss rate: {packet_loss:.2f}%",
                    "Possible wireless interference or physical link issues"
                ]
            }
        }
    
    def _diagnose_anomaly(self, node_id: str, metrics: Dict) -> Dict:
        """Diagnose anomalous behavior"""
        return {
            "root_cause": f"Anomalous behavior detected on {node_id}",
            "severity": "medium",
            "affected_services": self._get_affected_services(node_id),
            "recommendation": "Investigate recent changes. Check for DDoS or malware. Review logs.",
            "confidence": 0.60,
            "reasoning": {
                "indicators": [
                    "Metrics deviate significantly from baseline",
                    "Pattern not matching known fault signatures"
                ]
            }
        }
    
    def _get_affected_services(self, node_id: str) -> List[str]:
        """
        Determine which services are affected by the incident.
        In a real system, this would query service dependency maps.
        """
        # Simulated service dependency mapping
        service_map = {
            "router-1": ["web-server", "api-gateway"],
            "router-2": ["database", "cache"],
            "switch-1": ["load-balancer", "monitoring"],
            "link-1-2": ["web-server", "database", "api-gateway"],
        }
        
        return service_map.get(node_id, ["general-services"])
    
    def correlate_incidents(
        self,
        current_incident: Dict[str, Any],
        recent_incidents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Correlate current incident with recent incidents to find patterns.
        
        Args:
            current_incident: Current incident details
            recent_incidents: List of recent incidents
            
        Returns:
            Correlation analysis
        """
        correlation = {
            "incident_id": current_incident["incident_id"],
            "correlated_incidents": [],
            "pattern_detected": False,
            "pattern_type": None,
            "confidence": 0.0
        }
        
        if not recent_incidents:
            return correlation
        
        # Check for spatial correlation (same node/region)
        same_node_incidents = [
            inc for inc in recent_incidents
            if inc.get("affected_node") == current_incident["affected_node"]
        ]
        
        if same_node_incidents:
            correlation["correlated_incidents"] = same_node_incidents
            correlation["pattern_detected"] = True
            correlation["pattern_type"] = "cascading_failure"
            correlation["confidence"] = min(0.5 + len(same_node_incidents) * 0.1, 0.95)
            correlation["analysis"] = f"Multiple incidents on same node suggest cascading failure"
        
        # Check for temporal correlation (rapid succession)
        if recent_incidents:
            time_diff = (
                datetime.fromisoformat(current_incident["timestamp"]) -
                datetime.fromisoformat(recent_incidents[-1]["timestamp"])
            ).total_seconds()
            
            if time_diff < 300:  # Within 5 minutes
                correlation["pattern_type"] = "temporal_burst"
                correlation["pattern_detected"] = True
                correlation["confidence"] = 0.70
                correlation["analysis"] = "Multiple incidents in rapid succession"
        
        return correlation
    
    def close(self):
        """Close database connection"""
        if self.db is not None:
            self.db.close()


# Global diagnosis engine instance
_engine = None


def get_diagnosis_engine() -> DiagnosisEngine:
    """Get or create global diagnosis engine"""
    global _engine
    if _engine is None:
        _engine = DiagnosisEngine()
    return _engine
