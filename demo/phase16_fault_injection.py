"""Controlled Phase 16 fault-injection demonstrations."""

from __future__ import annotations

from typing import Any, Dict, List

from backend.app.monitoring import MonitoringService
from backend.diagnosis import DiagnosisEngine
from backend.explainability import ExplainableDecisionEngine
from backend.incident_logging import IncidentLogger
from backend.recovery import RecoveryOrchestrator
from backend.risk_assessment import RiskAssessmentEngine
from backend.safety import SafetyChecker
from backend.verification import VerificationEngine
from sdn_controller.controller import SDNController


class FaultInjectionDemo:
    """Run controlled faults through the complete self-healing pipeline."""

    def __init__(self) -> None:
        self.topology = {
            "nodes": ["host-a", "switch-1", "router-a", "router-b", "host-b"],
            "links": [["host-a", "switch-1"], ["switch-1", "router-a"], ["router-a", "router-b"], ["router-a", "host-b"], ["router-b", "host-b"]],
        }
        self.controller = SDNController(
            links=[tuple(link) for link in self.topology["links"]],
            routes={"flow-a-b": ["host-a", "switch-1", "router-a", "router-b", "host-b"]},
            services=["api-gateway"],
        )
        self.monitor = MonitoringService()
        self.diagnoser = DiagnosisEngine()
        self.risk_engine = RiskAssessmentEngine()
        self.decision_engine = ExplainableDecisionEngine()
        self.safety = SafetyChecker()
        self.recovery = RecoveryOrchestrator(controller=self.controller, safety_checker=self.safety)
        self.incidents = IncidentLogger()
        self.verifier = VerificationEngine()
        self.events: List[str] = ["NORMAL NETWORK"]

    def inject_link_failure(self) -> None:
        """Inject a failed primary path while retaining the alternate path."""
        self.controller.disable_link("router-b", "router-a")
        self.events.append("LINK FAILURE INJECTED")

    def inject_congestion(self) -> None:
        """Inject high utilization and quality degradation telemetry."""
        self.events.append("CONGESTION INJECTED")

    def inject_connectivity_failure(self) -> None:
        """Inject endpoint reachability loss for the primary flow."""
        self.controller.flows["flow-a-b"] = {"path": [], "status": "unreachable"}
        self.events.append("CONNECTIVITY FAILURE INJECTED")

    def run(self, scenario: str = "link_failure", recovery_failure: bool = False) -> Dict[str, Any]:
        """Run one scenario and return its complete dashboard/demo state."""
        scenario = scenario.lower()
        incident_id = f"DEMO-{scenario.upper()}"
        if scenario == "link_failure":
            self.inject_link_failure()
            metrics = {"latency_ms": 240, "packet_loss_pct": 18, "bandwidth_utilization_pct": 62, "throughput_mbps": 0, "link_status": "down", "connectivity": "down"}
            ml_prediction = {"label": "LINK_FAILURE", "probability": 0.96}
            affected_component = "router-a-router-b"
        elif scenario == "congestion":
            self.inject_congestion()
            metrics = {"latency_ms": 126, "packet_loss_pct": 4, "bandwidth_utilization_pct": 94, "throughput_mbps": 80, "link_status": "up"}
            ml_prediction = {"label": "CONGESTION", "probability": 0.91}
            affected_component = "router-a"
        elif scenario == "connectivity_failure":
            self.inject_connectivity_failure()
            metrics = {"latency_ms": 180, "packet_loss_pct": 100, "bandwidth_utilization_pct": 40, "throughput_mbps": 0, "connectivity": "down", "connectivity_score": 0.1, "route_redundancy": 1}
            ml_prediction = {"label": "CONNECTIVITY_FAILURE", "probability": 0.94}
            affected_component = "flow-a-b"
        else:
            raise ValueError("scenario must be link_failure, congestion, or connectivity_failure")

        sample = self.monitor.collect_periodic_sample("host-a", "host-b", metrics)
        diagnosis = self.diagnoser.diagnose(metrics, ml_prediction, self.topology, affected_node=affected_component)
        risk = self.risk_engine.assess_risk(
            diagnosis=diagnosis,
            traffic_impact=metrics.get("bandwidth_utilization_pct", 0) / 100,
            recovery_action_risk="high" if scenario != "congestion" else "medium",
            alternate_path_available=True,
            affected_component=affected_component,
        )
        decision = self.decision_engine.decide(diagnosis, risk, metrics, alternate_path_available=True)
        action = self._controller_action(scenario, decision, recovery_failure)
        safety = self.safety.validate_action(action, self._network_state(scenario), {"incident_id": incident_id, "affected_nodes": [affected_component]})
        execution = self.recovery.execute_recovery(
            recovery_id=f"{incident_id}-RECOVERY",
            incident_id=incident_id,
            strategy={"name": decision["selected_action"], "actions": [action]},
            network_state=self._network_state(scenario),
        )
        verification = self.verifier.verify_metrics(
            recovery_id=f"{incident_id}-RECOVERY",
            incident_id=incident_id,
            pre_recovery_metrics=metrics,
            post_recovery_metrics=self._post_metrics(scenario, execution),
        )
        final_status = "RESOLVED" if verification["verified"] else "FAILED"
        incident = self.incidents.create_incident(
            incident_id=incident_id,
            detected_fault=diagnosis["fault_type"],
            affected_component=affected_component,
            metrics=sample,
            ml_prediction=ml_prediction,
            confidence=diagnosis["confidence"],
            severity=risk["risk_level"],
            selected_action=decision["selected_action"],
            safety_result=safety,
            recovery_result=execution,
            verification_metrics=verification,
            final_status=final_status,
        )
        self.incidents.update_incident(incident_id, final_status=final_status)
        self.events.extend(["MONITORING DETECTED", "ML PREDICTED", "DIAGNOSIS COMPLETE", "DECISION SELECTED", "SAFETY CHECK", "SDN RECOVERY", "VERIFICATION", "SELF-HEALED" if verification["verified"] else "RECOVERY FAILED"])
        return {
            "scenario": scenario,
            "events": self.events,
            "dashboard_status": "SELF-HEALED" if verification["verified"] else "RECOVERY_FAILED",
            "incident": incident,
            "diagnosis": diagnosis,
            "risk": risk,
            "decision": decision,
            "safety": safety,
            "recovery": execution,
            "verification": verification,
            "controller_state": {
                "routes": self.controller.routes,
                "flows": self.controller.flows,
                "links": {f"{source}->{target}": active for (source, target), active in self.controller.links.items()},
                "link_weights": {f"{source}->{target}": weight for (source, target), weight in self.controller.link_weights.items()},
                "qos_policies": self.controller.qos_policies,
                "services": self.controller.services,
            },
        }

    def run_fallback_demo(self) -> Dict[str, Any]:
        """Demonstrate failed primary recovery followed by escalation/success."""
        incident_id = "DEMO-FALLBACK"
        results = iter([{"success": False}, {"success": True}])
        audit = self.recovery.execute_with_fallback(
            recovery_id=incident_id,
            incident_id=incident_id,
            primary_strategy={"name": "REROUTE_TRAFFIC", "actions": [{"type": "increase_monitoring"}]},
            fallback_strategy={"name": "UPDATE_FLOW_RULE", "actions": [{"type": "increase_monitoring"}]},
            verify_attempt=lambda execution: next(results),
            max_attempts=2,
        )
        self.events.extend(["PRIMARY RECOVERY FAILED", "FALLBACK RECOVERY", "SELF-HEALED" if audit["status"] == "RECOVERY_SUCCESSFUL" else "ESCALATED"])
        return {"scenario": "recovery_failure_fallback", "events": self.events, "dashboard_status": "SELF-HEALED" if audit["status"] == "RECOVERY_SUCCESSFUL" else "ESCALATED", "recovery": audit}

    def _controller_action(self, scenario: str, decision: Dict[str, Any], recovery_failure: bool) -> Dict[str, Any]:
        if recovery_failure:
            return {"type": "update_routing", "flow_id": "flow-a-b", "path": ["missing", "path"]}
        if scenario == "link_failure":
            return {"type": "update_routing", "flow_id": "flow-a-b", "path": ["host-a", "switch-1", "router-a", "host-b"]}
        if scenario == "congestion":
            return {"type": "apply_qos", "target": "router-a", "rate_mbps": 100}
        return {"type": "update_routing", "flow_id": "flow-a-b", "path": ["host-a", "switch-1", "router-a", "host-b"]}

    def _network_state(self, scenario: str) -> Dict[str, Any]:
        return {"alternate_path_available": True, "available_resources": ["router-a"], "link_utilization": {}}

    @staticmethod
    def _post_metrics(scenario: str, execution: Dict[str, Any]) -> Dict[str, Any]:
        if execution["status"] != "success":
            return {"latency_ms": 240, "packet_loss_pct": 18, "bandwidth_utilization_pct": 96, "link_status": "down", "connectivity": "down"}
        return {"latency_ms": 42 if scenario != "congestion" else 58, "packet_loss_pct": 2 if scenario != "congestion" else 0.8, "bandwidth_utilization_pct": 68, "link_status": "up", "connectivity": "up", "node_responsive": True}


if __name__ == "__main__":
    import json
    print(json.dumps(FaultInjectionDemo().run("link_failure"), indent=2, default=str))
