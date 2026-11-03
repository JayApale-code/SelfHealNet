# recovery/__init__.py - Recovery Orchestration Module

from typing import Dict, List, Any, Optional
import logging
from datetime import datetime
try:
    from ..database import SessionLocal
except ImportError:
    try:
        from database import SessionLocal
    except ImportError:
        SessionLocal = None

try:
    from ..safety import get_safety_checker
except ImportError:
    from safety import get_safety_checker

try:
    from ...sdn_controller.controller import SDNController
except ImportError:
    from sdn_controller.controller import SDNController

logger = logging.getLogger(__name__)


class RecoveryOrchestrator:
    """
    Orchestrates recovery actions for network incidents.
    Integrates with SDN controllers for automated network changes.
    """
    
    def __init__(self, sdn_controller_url: str = None, safety_checker=None, controller=None):
        self.db = None
        self.safety_checker = safety_checker or get_safety_checker()
        self.sdn_controller_url = sdn_controller_url or "http://localhost:8080"
        self.sdn_controller = controller or SDNController(self.sdn_controller_url)

    def execute_with_fallback(
        self,
        recovery_id: str,
        incident_id: str,
        primary_strategy: Dict[str, Any],
        fallback_strategy: Optional[Dict[str, Any]],
        verify_attempt,
        max_attempts: int = 2,
        dry_run: bool = False,
        network_state: Dict[str, Any] = None,
        incident_context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Execute recovery attempts with verification and bounded escalation.

        ``verify_attempt`` receives each execution result and must return a
        verification dictionary containing ``success`` or ``verified``. The
        maximum is applied to the total number of attempts, not per strategy,
        so a fallback can never create an unbounded recovery loop.
        """
        if not callable(verify_attempt):
            raise TypeError("verify_attempt must be callable")
        attempt_limit = max(1, min(int(max_attempts), 2))
        strategies = [primary_strategy]
        if fallback_strategy is not None and attempt_limit > 1:
            strategies.append(fallback_strategy)
        audit = {
            "recovery_id": recovery_id,
            "incident_id": incident_id,
            "status": "ESCALATED",
            "max_attempts": attempt_limit,
            "attempts": [],
            "administrator_alert": None,
        }

        for attempt_number, strategy in enumerate(strategies[:attempt_limit], start=1):
            execution = self.execute_recovery(
                recovery_id=f"{recovery_id}-{attempt_number}",
                incident_id=incident_id,
                strategy=strategy,
                dry_run=dry_run,
                network_state=network_state,
                incident_context=incident_context,
            )
            verification = verify_attempt(execution)
            successful = bool(verification.get("success", verification.get("verified", False)))
            audit["attempts"].append({
                "attempt": attempt_number,
                "strategy": strategy.get("name", "primary" if attempt_number == 1 else "fallback"),
                "execution": execution,
                "verification": verification,
            })
            if successful:
                audit["status"] = "RECOVERY_SUCCESSFUL"
                audit["successful_attempt"] = attempt_number
                return audit

        audit["administrator_alert"] = {
            "severity": "CRITICAL",
            "message": "All permitted recovery attempts failed; administrator escalation required.",
            "incident_id": incident_id,
        }
        logger.critical(audit["administrator_alert"]["message"])
        return audit

    recover_with_fallback = execute_with_fallback
    
    def plan_recovery(
        self,
        incident_id: str,
        incident_type: str,
        affected_node: str,
        risk_level: str
    ) -> Dict[str, Any]:
        """
        Plan recovery strategy for incident.
        
        Args:
            incident_id: Incident identifier
            incident_type: Type of incident
            affected_node: Affected network node
            risk_level: Risk/severity level
            
        Returns:
            Recovery plan with primary and fallback strategies
        """
        
        plan = {
            "incident_id": incident_id,
            "timestamp": datetime.utcnow().isoformat(),
            "primary_strategy": None,
            "fallback_strategy": None,
            "actions": []
        }
        
        # Plan based on incident type
        if incident_type == "link_failure":
            plan["primary_strategy"] = {
                "name": "failover_to_backup_link",
                "description": "Reroute traffic to backup link",
                "actions": [
                    {"type": "disable_link", "target": affected_node},
                    {"type": "enable_backup_link", "target": f"{affected_node}-backup"},
                    {"type": "update_routing", "protocol": "bgp"}
                ],
                "estimated_recovery_time": 30
            }
            plan["fallback_strategy"] = {
                "name": "manual_intervention_required",
                "description": "Alert operators for manual repair",
                "actions": [
                    {"type": "alert_ops", "severity": "critical"},
                    {"type": "page_on_call_engineer", "reason": "link_repair_needed"}
                ]
            }
        
        elif incident_type == "congestion":
            plan["primary_strategy"] = {
                "name": "traffic_engineering",
                "description": "Reroute congested traffic",
                "actions": [
                    {"type": "adjust_weights", "protocol": "ospf", "target": affected_node},
                    {"type": "apply_qos", "target": affected_node},
                    {"type": "enable_traffic_shaping"}
                ],
                "estimated_recovery_time": 60
            }
            plan["fallback_strategy"] = {
                "name": "rate_limiting",
                "description": "Rate limit traffic if rerouting fails",
                "actions": [
                    {"type": "rate_limit", "target": affected_node, "rate_mbps": 100}
                ]
            }
        
        elif incident_type == "high_latency":
            plan["primary_strategy"] = {
                "name": "optimize_routing",
                "description": "Find optimal path",
                "actions": [
                    {"type": "trigger_spf_recalculation", "protocol": "ospf"},
                    {"type": "verify_bgp_neighbors"}
                ],
                "estimated_recovery_time": 15
            }
            plan["fallback_strategy"] = {
                "name": "increase_monitoring",
                "description": "Increase monitoring frequency",
                "actions": [
                    {"type": "increase_metric_frequency", "interval": 5}
                ]
            }

        elif incident_type == "service_degradation":
            plan["primary_strategy"] = {
                "name": "restart_affected_service",
                "description": "Restart the degraded service through the controller",
                "actions": [{"type": "restart_service", "target": affected_node}],
                "estimated_recovery_time": 45
            }
            plan["fallback_strategy"] = {
                "name": "increase_monitoring",
                "description": "Monitor service while operators investigate",
                "actions": [{"type": "increase_monitoring", "interval": 5}]
            }

        elif incident_type == "connectivity_failure":
            plan["primary_strategy"] = {
                "name": "update_flow_routing",
                "description": "Install an active route and flow rule through the controller",
                "actions": [{"type": "update_routing", "flow_id": affected_node, "source": affected_node, "target": "gateway"}],
                "estimated_recovery_time": 20
            }
            plan["fallback_strategy"] = {
                "name": "manual_connectivity_recovery",
                "description": "Alert operators when no active route can be installed",
                "actions": [{"type": "alert_ops", "severity": "critical"}]
            }
        
        else:
            plan["primary_strategy"] = {
                "name": "observation_mode",
                "description": "Monitor and observe",
                "actions": [
                    {"type": "increase_monitoring", "interval": 10}
                ],
                "estimated_recovery_time": 0
            }
        
        return plan
    
    def execute_recovery(
        self,
        recovery_id: str,
        incident_id: str,
        strategy: Dict[str, Any],
        dry_run: bool = False,
        network_state: Dict[str, Any] = None,
        incident_context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Execute recovery strategy.
        
        Args:
            recovery_id: Unique recovery attempt ID
            incident_id: Associated incident ID
            strategy: Recovery strategy to execute
            dry_run: If True, only simulate without actual execution
            
        Returns:
            Execution result with status and actions taken
        """
        
        result = {
            "recovery_id": recovery_id,
            "incident_id": incident_id,
            "timestamp": datetime.utcnow().isoformat(),
            "dry_run": dry_run,
            "status": "in_progress",
            "actions_executed": [],
            "errors": []
        }
        
        try:
            # Execute each action in strategy
            for action in strategy.get("actions", []):
                safety_decision = self.safety_checker.validate_action(
                    action,
                    network_state or {},
                    incident_context or {"incident_id": incident_id},
                )
                if not safety_decision["safe"]:
                    result["errors"].append({
                        "action": action.get("type"),
                        "error": safety_decision["administrator_alert"]["message"],
                        "safety_decision": safety_decision,
                    })
                    continue
                action_result = self._execute_action(action, dry_run)
                
                if action_result["success"]:
                    result["actions_executed"].append(action_result)
                else:
                    result["errors"].append({
                        "action": action["type"],
                        "error": action_result.get("error", "Unknown error")
                    })
            
            # Determine overall status
            if not result["errors"]:
                result["status"] = "success"
            elif len(result["errors"]) < len(strategy.get("actions", [])):
                result["status"] = "partial_success"
            else:
                result["status"] = "failed"
            
            logger.info(f"Recovery execution: {result['status']}")
            
        except Exception as e:
            logger.error(f"Recovery execution error: {e}")
            result["status"] = "failed"
            result["errors"].append({"error": str(e)})
        
        return result
    
    def _execute_action(
        self,
        action: Dict[str, Any],
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Execute single recovery action"""
        
        action_type = action.get("type")
        
        result = {
            "action": action_type,
            "target": action.get("target"),
            "dry_run": dry_run,
            "success": False,
            "details": {}
        }
        
        try:
            if dry_run:
                # Simulate action
                result["success"] = True
                result["details"]["simulation"] = f"Would execute {action_type} on {action.get('target')}"
            else:
                controller_result = self.sdn_controller.execute_action(action)
                result["success"] = controller_result.get("status") in {"applied", "restarted", "recorded"}
                result["details"] = controller_result
        
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Action execution error: {action_type} - {e}")
        
        return result
    
    # ==================== SDN Integration ====================
    
    def _sdn_disable_link(self, target: str) -> bool:
        """Disable link via SDN controller"""
        self.sdn_controller.execute_action({"type": "disable_link", "target": target})
        return True
    
    def _sdn_enable_link(self, target: str) -> bool:
        """Enable link via SDN controller"""
        self.sdn_controller.execute_action({"type": "enable_backup_link", "target": target})
        return True
    
    def _sdn_update_routing(self, protocol: str) -> bool:
        """Update routing via SDN controller"""
        self.sdn_controller.execute_action({"type": "update_routing", "protocol": protocol})
        return True
    
    def _sdn_adjust_weights(self, target: str) -> bool:
        """Adjust OSPF weights via SDN controller"""
        self.sdn_controller.execute_action({"type": "adjust_weights", "target": target})
        return True
    
    def _sdn_apply_qos(self, target: str) -> bool:
        """Apply QoS policy via SDN controller"""
        self.sdn_controller.execute_action({"type": "apply_qos", "target": target})
        return True
    
    def _sdn_rate_limit(self, target: str, rate_mbps: float) -> bool:
        """Rate limit via SDN controller"""
        self.sdn_controller.execute_action({"type": "rate_limit", "target": target, "rate_mbps": rate_mbps})
        return True
    
    def get_rollback_actions(
        self,
        recovery_id: str,
        executed_actions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Generate rollback actions (reverse of executed actions)"""
        
        rollback_actions = []
        
        # Reverse order of execution
        for action in reversed(executed_actions):
            action_type = action.get("action")
            target = action.get("target")
            
            # Create inverse action
            if action_type == "disable_link":
                rollback_actions.append({"type": "enable_link", "target": target})
            elif action_type == "enable_backup_link":
                rollback_actions.append({"type": "disable_backup_link", "target": target})
            elif action_type == "rate_limit":
                rollback_actions.append({"type": "remove_rate_limit", "target": target})
            else:
                rollback_actions.append({"type": f"undo_{action_type}", "target": target})
        
        return rollback_actions
    
    def close(self):
        """Close database connection"""
        if self.db is not None:
            self.db.close()


# Global recovery orchestrator instance
_orchestrator = None


def get_recovery_orchestrator() -> RecoveryOrchestrator:
    """Get or create global recovery orchestrator"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = RecoveryOrchestrator()
    return _orchestrator
