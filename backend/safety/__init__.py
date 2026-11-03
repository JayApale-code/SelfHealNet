# safety/__init__.py - Safety Validation and Constraint Checking

from typing import Dict, List, Any
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class SafetyConstraint:
    """Represents a safety constraint for recovery actions"""
    
    def __init__(
        self,
        name: str,
        description: str,
        check_function,
        severity: str = "high"
    ):
        self.name = name
        self.description = description
        self.check_function = check_function
        self.severity = severity
    
    def validate(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate constraint.
        
        Returns:
            Dictionary with passed (bool), reason (str)
        """
        return self.check_function(context)


class SafetyChecker:
    """
    Pre-flight validation for recovery actions.
    Ensures recovery actions don't violate safety constraints.
    """
    
    def __init__(self):
        self.constraints = self._initialize_constraints()
        self.decision_log: List[Dict[str, Any]] = []
        self.supported_actions = {
            "disable_link", "enable_link", "enable_backup_link", "disable_backup_link",
            "update_routing", "adjust_weights", "apply_qos", "enable_traffic_shaping",
            "rate_limit", "remove_rate_limit", "trigger_spf_recalculation",
            "verify_bgp_neighbors", "increase_monitoring", "increase_metric_frequency",
            "alert_ops", "page_on_call_engineer", "restart_service",
        }

    def validate_action(
        self,
        action: Dict[str, Any],
        network_state: Dict[str, Any],
        incident_context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Validate one recovery action immediately before execution.

        Every decision is appended to ``decision_log`` and emitted through the
        logger. Unsafe actions return an administrator alert and must not be
        executed by the recovery layer.
        """
        incident_context = incident_context or {}
        network_state = network_state or {}
        action_type = action.get("type")
        checks = []

        def check(name: str, passed: bool, reason: str) -> None:
            checks.append({"check": name, "passed": passed, "reason": reason})

        check(
            "supported_action",
            action_type in self.supported_actions,
            f"Action '{action_type}' is supported" if action_type in self.supported_actions else f"Action '{action_type}' is not supported",
        )

        alternate_paths = network_state.get("alternative_paths", {})
        has_alternate = network_state.get("alternate_path_available", False)
        if isinstance(alternate_paths, dict):
            has_alternate = has_alternate or bool(alternate_paths.get(action.get("target"), False))
        requires_path = action_type in {"disable_link", "enable_backup_link", "update_routing", "adjust_weights"}
        check(
            "required_alternate_path",
            not requires_path or bool(has_alternate),
            "Required alternate path is available" if not requires_path or has_alternate else "Required alternate path is unavailable",
        )

        required_resource = action.get("required_resource")
        available_resources = network_state.get("available_resources", [])
        resource_present = not required_resource or required_resource in available_resources
        if action_type == "enable_backup_link":
            backup_links = network_state.get("backup_links", [])
            resource_present = action.get("target") in backup_links or action.get("target") in available_resources
        check(
            "required_resource",
            resource_present,
            "Required resource is available" if resource_present else "Required recovery resource is unavailable",
        )

        affected_nodes = action.get("affected_nodes", incident_context.get("affected_nodes", []))
        impact_limit = float(network_state.get("max_affected_nodes", 0) or 0)
        impact_ok = not impact_limit or len(affected_nodes) <= impact_limit
        check(
            "estimated_impact",
            impact_ok,
            "Estimated impact is within the configured limit" if impact_ok else "Estimated impact exceeds the configured node limit",
        )

        overloads = []
        traffic_shift = float(action.get("traffic_shift", network_state.get("traffic_shift", 0)) or 0)
        for link in action.get("target_links", network_state.get("target_links", [])):
            current = float(network_state.get("link_utilization", {}).get(link, 0) or 0)
            proposed = current + traffic_shift
            if proposed > 85:
                overloads.append(f"{link} would reach {proposed:.1f}% utilization")
        check(
            "overload_prevention",
            not overloads,
            "No target component would exceed 85% utilization" if not overloads else "; ".join(overloads),
        )

        passed = all(item["passed"] for item in checks)
        decision = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action_type,
            "safe": passed,
            "checks": checks,
            "administrator_alert": None if passed else {
                "severity": "CRITICAL",
                "message": f"Recovery action '{action_type}' blocked by safety validation",
                "reasons": [item["reason"] for item in checks if not item["passed"]],
                "incident_id": incident_context.get("incident_id"),
            },
        }
        self.decision_log.append(decision)
        logger.info(
            "Safety decision: %s action=%s checks=%d",
            "ALLOWED" if passed else "BLOCKED",
            action_type,
            len(checks),
        )
        return decision
    
    def _initialize_constraints(self) -> List[SafetyConstraint]:
        """Initialize standard safety constraints"""
        
        constraints = [
            SafetyConstraint(
                name="no_single_point_of_failure",
                description="Recovery must not create single point of failure",
                check_function=self._check_no_single_point_of_failure,
                severity="critical"
            ),
            SafetyConstraint(
                name="connectivity_preservation",
                description="Recovery must maintain network connectivity",
                check_function=self._check_connectivity_preservation,
                severity="critical"
            ),
            SafetyConstraint(
                name="capacity_headroom",
                description="Recovery must not exceed link capacity",
                check_function=self._check_capacity_headroom,
                severity="high"
            ),
            SafetyConstraint(
                name="bgp_stability",
                description="Recovery must not destabilize BGP",
                check_function=self._check_bgp_stability,
                severity="high"
            ),
            SafetyConstraint(
                name="service_level_maintenance",
                description="Recovery must maintain SLA requirements",
                check_function=self._check_service_level_maintenance,
                severity="high"
            ),
            SafetyConstraint(
                name="loop_prevention",
                description="Recovery must not create routing loops",
                check_function=self._check_loop_prevention,
                severity="critical"
            ),
            SafetyConstraint(
                name="rate_limiting",
                description="Limit recovery action rate to prevent oscillation",
                check_function=self._check_rate_limiting,
                severity="medium"
            ),
        ]
        
        return constraints
    
    def pre_flight_check(
        self,
        recovery_strategy: Dict[str, Any],
        incident_context: Dict[str, Any],
        network_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Perform pre-flight validation before recovery.
        
        Args:
            recovery_strategy: Proposed recovery strategy
            incident_context: Context of incident
            network_state: Current network state
            
        Returns:
            Safety check result with passed/failed status and violations
        """
        
        check_context = {
            "recovery_strategy": recovery_strategy,
            "incident_context": incident_context,
            "network_state": network_state,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        result = {
            "passed": True,
            "timestamp": check_context["timestamp"],
            "total_constraints": len(self.constraints),
            "violations": [],
            "warnings": [],
            "recommendations": []
        }
        
        # Check each constraint
        for constraint in self.constraints:
            try:
                validation = constraint.validate(check_context)
                
                if not validation.get("passed", False):
                    violation = {
                        "constraint": constraint.name,
                        "severity": constraint.severity,
                        "reason": validation.get("reason", "Unknown")
                    }
                    
                    if constraint.severity == "critical":
                        result["passed"] = False
                    
                    result["violations"].append(violation)
                    logger.warning(f"Safety constraint violated: {constraint.name}")
                else:
                    logger.info(f"Safety constraint passed: {constraint.name}")
            
            except Exception as e:
                logger.error(f"Error checking constraint {constraint.name}: {e}")
                result["warnings"].append({
                    "constraint": constraint.name,
                    "error": str(e)
                })
        
        # Generate recommendations if check failed
        if not result["passed"]:
            result["recommendations"] = self._generate_safety_recommendations(result)
        
        logger.info(
            f"Pre-flight check: {'PASSED' if result['passed'] else 'FAILED'} - "
            f"Violations: {len(result['violations'])}"
        )
        
        return result
    
    # ==================== Constraint Implementations ====================
    
    def _check_no_single_point_of_failure(
        self,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ensure recovery doesn't create single point of failure"""
        
        recovery = context["recovery_strategy"]
        network = context["network_state"]
        
        # Check if recovery action removes redundancy
        target_node = recovery.get("target_node")
        
        # Simplified check: verify alternative paths exist
        has_alternative = network.get("alternative_paths", {}).get(target_node, False)
        
        if not has_alternative:
            return {
                "passed": False,
                "reason": f"No alternative paths available for {target_node}"
            }
        
        return {
            "passed": True,
            "reason": "Alternative paths verified"
        }
    
    def _check_connectivity_preservation(
        self,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ensure recovery maintains network connectivity"""
        
        recovery = context["recovery_strategy"]
        
        # Check if recovery action maintains overall connectivity
        if recovery.get("action_type") in ["reroute", "failover"]:
            # Verify target paths maintain connectivity
            affected_nodes = recovery.get("affected_nodes", [])
            
            if not affected_nodes:
                return {
                    "passed": False,
                    "reason": "Recovery action does not specify affected nodes"
                }
            
            return {
                "passed": True,
                "reason": f"Connectivity maintained for {len(affected_nodes)} nodes"
            }
        
        return {
            "passed": True,
            "reason": "Action type compatible with connectivity requirements"
        }
    
    def _check_capacity_headroom(
        self,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ensure recovery doesn't exceed link capacity"""
        
        recovery = context["recovery_strategy"]
        network = context["network_state"]
        
        target_links = recovery.get("target_links", [])
        
        for link in target_links:
            current_util = network.get("link_utilization", {}).get(link, 0)
            proposed_util = current_util + recovery.get("traffic_shift", 0)
            
            # Allow maximum 85% utilization
            if proposed_util > 85:
                return {
                    "passed": False,
                    "reason": f"Link {link} would exceed safe utilization (proposed: {proposed_util:.1f}%)"
                }
        
        return {
            "passed": True,
            "reason": "All links remain within capacity headroom"
        }
    
    def _check_bgp_stability(
        self,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ensure recovery doesn't destabilize BGP"""
        
        recovery = context["recovery_strategy"]
        
        if recovery.get("action_type") in ["bgp_update", "route_change"]:
            # Check if change is too frequent (BGP flapping)
            recent_changes = context.get("network_state", {}).get("recent_bgp_changes", 0)
            
            if recent_changes > 3:  # More than 3 changes in short time
                return {
                    "passed": False,
                    "reason": "BGP flapping detected - wait before making routing changes"
                }
        
        return {
            "passed": True,
            "reason": "BGP stability maintained"
        }
    
    def _check_service_level_maintenance(
        self,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ensure recovery maintains SLA requirements"""
        
        incident = context["incident_context"]
        recovery = context["recovery_strategy"]
        
        # Check if recovery strategy maintains SLA
        affected_services = incident.get("affected_services", [])
        
        if incident.get("severity_level") == "critical":
            # For critical incidents, ensure recovery completes within MTTR
            estimated_time = recovery.get("estimated_recovery_time", 300)
            
            # Critical SLA MTTR: 5 minutes
            if estimated_time > 300:
                return {
                    "passed": False,
                    "reason": f"Recovery time ({estimated_time}s) exceeds SLA MTTR (300s)"
                }
        
        return {
            "passed": True,
            "reason": "Service levels can be maintained"
        }
    
    def _check_loop_prevention(
        self,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ensure recovery doesn't create routing loops"""
        
        recovery = context["recovery_strategy"]
        network = context["network_state"]
        
        # Check if route change would create loop
        if recovery.get("action_type") == "route_change":
            new_path = recovery.get("new_path", [])
            
            # Check for cycles in path
            if len(new_path) != len(set(new_path)):
                return {
                    "passed": False,
                    "reason": f"Routing loop detected in path: {new_path}"
                }
        
        return {
            "passed": True,
            "reason": "No routing loops detected"
        }
    
    def _check_rate_limiting(
        self,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prevent recovery action oscillation"""
        
        incident = context["incident_context"]
        
        # Check if same node had recovery recently
        incident_id = incident.get("incident_id")
        recent_recoveries = context.get("network_state", {}).get("recent_recoveries", {})
        
        if incident_id in recent_recoveries:
            last_recovery = recent_recoveries[incident_id]
            time_since = (datetime.utcnow() - last_recovery).total_seconds()
            
            # Minimum 60 seconds between recovery attempts
            if time_since < 60:
                return {
                    "passed": False,
                    "reason": f"Recovery attempted too recently ({int(time_since)}s ago). Waiting for stability."
                }
        
        return {
            "passed": True,
            "reason": "Recovery rate within acceptable limits"
        }
    
    def _generate_safety_recommendations(
        self,
        check_result: Dict[str, Any]
    ) -> List[str]:
        """Generate recommendations based on failed constraints"""
        
        recommendations = []
        
        for violation in check_result["violations"]:
            constraint = violation["constraint"]
            
            if constraint == "no_single_point_of_failure":
                recommendations.append(
                    "Verify alternative paths exist before proceeding with recovery"
                )
            elif constraint == "connectivity_preservation":
                recommendations.append(
                    "Ensure all affected nodes maintain connectivity during recovery"
                )
            elif constraint == "capacity_headroom":
                recommendations.append(
                    "Consider traffic engineering or load balancing to reduce link utilization"
                )
            elif constraint == "bgp_stability":
                recommendations.append(
                    "Wait for BGP to stabilize before attempting routing changes"
                )
            elif constraint == "service_level_maintenance":
                recommendations.append(
                    "Ensure recovery can complete within SLA MTTR requirements"
                )
            elif constraint == "loop_prevention":
                recommendations.append(
                    "Verify routing path does not create loops"
                )
            elif constraint == "rate_limiting":
                recommendations.append(
                    "Wait before attempting another recovery on same node"
                )
        
        return recommendations


# Global safety checker instance
_checker = None


def get_safety_checker() -> SafetyChecker:
    """Get or create global safety checker"""
    global _checker
    if _checker is None:
        _checker = SafetyChecker()
    return _checker
