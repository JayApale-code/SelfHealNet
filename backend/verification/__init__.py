# verification/__init__.py - Post-Recovery Verification Module

from typing import Dict, List, Any, Optional, Callable
import logging
from datetime import datetime
import time

try:
    from ..database import SessionLocal, NetworkMetric, RecoveryAttempt
except ImportError:
    try:
        from database import SessionLocal, NetworkMetric, RecoveryAttempt
    except ImportError:
        SessionLocal = None
        NetworkMetric = None
        RecoveryAttempt = None

logger = logging.getLogger(__name__)


class VerificationEngine:
    """
    Validates recovery success and triggers fallback if needed.
    Compares pre-recovery and post-recovery metrics.
    """
    
    def __init__(self, db_session=None, sleep_fn: Callable[[float], None] = time.sleep):
        self.db = db_session
        self.sleep_fn = sleep_fn

    def verify_metrics(
        self,
        recovery_id: str,
        incident_id: str,
        pre_recovery_metrics: Dict[str, Any],
        post_recovery_metrics: Optional[Dict[str, Any]] = None,
        metric_collector: Optional[Callable[[], Dict[str, Any]]] = None,
        stabilization_seconds: float = 0,
    ) -> Dict[str, Any]:
        """Wait, collect, and verify post-recovery network metrics.

        ``metric_collector`` is called after stabilization when post metrics are
        not supplied. This keeps verification usable with a real monitoring
        adapter or a stateful simulator while making the comparison explicit.
        Recovery succeeds when the node/link is reachable and the available
        quality metrics meet the criteria documented in
        ``docs/PHASE11_RECOVERY_VERIFICATION.md``.
        """
        stabilization_seconds = max(0.0, float(stabilization_seconds))
        if stabilization_seconds:
            self.sleep_fn(stabilization_seconds)
        if post_recovery_metrics is None:
            if metric_collector is None:
                raise ValueError("post_recovery_metrics or metric_collector is required")
            post_recovery_metrics = metric_collector()

        pre = self._normalize_metrics(pre_recovery_metrics)
        post = self._normalize_metrics(post_recovery_metrics)
        comparisons = self._compare_metric_values(pre, post)
        criteria = self._evaluate_criteria(pre, post)
        failed = [name for name, passed in criteria.items() if not passed]
        successful = not failed
        confidence = 0.95 if successful else max(0.2, 0.7 - 0.1 * len(failed))

        return {
            "recovery_id": recovery_id,
            "incident_id": incident_id,
            "timestamp": datetime.utcnow().isoformat(),
            "stabilization_wait_seconds": stabilization_seconds,
            "before": pre_recovery_metrics,
            "after": post_recovery_metrics,
            "metric_comparisons": comparisons,
            "criteria": criteria,
            "criteria_met": [name for name, passed in criteria.items() if passed],
            "criteria_failed": failed,
            "result": "RECOVERY_SUCCESSFUL" if successful else "RECOVERY_FAILED",
            "verified": successful,
            "confidence": round(confidence, 2),
        }

    verify = verify_metrics

    @staticmethod
    def _normalize_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
        aliases = {
            "latency_ms": ("latency_ms", "latency", "latency_mean"),
            "packet_loss_pct": ("packet_loss_pct", "packet_loss", "packet_loss_mean"),
            "bandwidth_utilization_pct": ("bandwidth_utilization_pct", "bandwidth_usage", "bandwidth_util"),
            "link_status": ("link_status",),
            "node_responsive": ("node_responsive",),
            "connectivity": ("connectivity",),
        }
        normalized: Dict[str, Any] = {}
        for target, names in aliases.items():
            for name in names:
                if name in metrics:
                    normalized[target] = metrics[name]
                    break
        return normalized

    @staticmethod
    def _compare_metric_values(pre: Dict[str, Any], post: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        comparisons = {}
        lower_is_better = {"latency_ms", "packet_loss_pct", "bandwidth_utilization_pct"}
        for name in lower_is_better:
            if name not in pre or name not in post:
                continue
            before = float(pre[name])
            after = float(post[name])
            comparisons[name] = {
                "before": before,
                "after": after,
                "change": round(after - before, 3),
                "improvement_percent": round((before - after) / max(abs(before), 0.001) * 100, 2),
                "direction": "improved" if after < before else "worsened" if after > before else "unchanged",
            }
        return comparisons

    @staticmethod
    def _evaluate_criteria(pre: Dict[str, Any], post: Dict[str, Any]) -> Dict[str, bool]:
        criteria = {}
        if "node_responsive" in post:
            criteria["node_responsive"] = post["node_responsive"] is True
        elif "link_status" in post:
            criteria["link_available"] = str(post["link_status"]).lower() == "up"
        elif "connectivity" in post:
            criteria["connectivity_restored"] = str(post["connectivity"]).lower() in {"up", "connected", "restored"}

        if "latency_ms" in post:
            baseline = float(pre.get("latency_ms", post["latency_ms"]))
            criteria["latency_stable"] = float(post["latency_ms"]) <= max(50.0, baseline * 1.2)
        if "packet_loss_pct" in post:
            baseline = float(pre.get("packet_loss_pct", post["packet_loss_pct"]))
            criteria["packet_loss_acceptable"] = float(post["packet_loss_pct"]) <= max(3.0, baseline * 0.25)
        if "bandwidth_utilization_pct" in post:
            criteria["bandwidth_safe"] = float(post["bandwidth_utilization_pct"]) <= 85.0

        return criteria or {"post_metrics_available": False}
    
    def verify_recovery(
        self,
        recovery_id: str,
        incident_id: str,
        affected_node: str,
        pre_recovery_metrics: Dict[str, float],
        success_criteria: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Verify recovery success by comparing metrics.
        
        Args:
            recovery_id: Recovery attempt ID
            incident_id: Associated incident ID
            affected_node: Node that was recovered
            pre_recovery_metrics: Metrics before recovery
            success_criteria: Custom success criteria
            
        Returns:
            Verification result with success status
        """
        
        # Default success criteria
        if success_criteria is None:
            success_criteria = self._get_default_criteria(affected_node)
        
        verification = {
            "recovery_id": recovery_id,
            "incident_id": incident_id,
            "timestamp": datetime.utcnow().isoformat(),
            "verified": False,
            "success": False,
            "pre_recovery_metrics": pre_recovery_metrics,
            "post_recovery_metrics": {},
            "metric_improvements": {},
            "criteria_met": [],
            "criteria_failed": [],
            "confidence": 0.0
        }
        
        try:
            # Collect post-recovery metrics
            post_metrics = self._collect_post_recovery_metrics(affected_node)
            verification["post_recovery_metrics"] = post_metrics
            
            # Compare metrics
            improvements = self._compare_metrics(pre_recovery_metrics, post_metrics)
            verification["metric_improvements"] = improvements
            
            # Evaluate success criteria
            for criterion_name, criterion_check in success_criteria.items():
                if criterion_check(post_metrics, pre_recovery_metrics):
                    verification["criteria_met"].append(criterion_name)
                else:
                    verification["criteria_failed"].append(criterion_name)
            
            # Determine overall success
            if not verification["criteria_failed"]:
                verification["success"] = True
                verification["verified"] = True
                verification["confidence"] = 0.95
            elif len(verification["criteria_met"]) > len(verification["criteria_failed"]):
                verification["success"] = True
                verification["verified"] = True
                verification["confidence"] = 0.75
            else:
                verification["success"] = False
                verification["verified"] = False
                verification["confidence"] = 0.3
            
            logger.info(
                f"Recovery verification: {recovery_id} - "
                f"Success: {verification['success']}, "
                f"Confidence: {verification['confidence']:.2f}"
            )
        
        except Exception as e:
            logger.error(f"Verification error: {e}")
            verification["success"] = False
            verification["verified"] = False
            verification["error"] = str(e)
        
        return verification
    
    def _get_default_criteria(self, node_id: str) -> Dict[str, callable]:
        """Get default success criteria for node"""
        
        criteria = {
            "latency_recovered": lambda post, pre: (
                post.get("latency_mean", float('inf')) < 
                pre.get("latency_mean", 0) * 1.2  # Within 120% of baseline
            ),
            "packet_loss_acceptable": lambda post, pre: (
                post.get("packet_loss_mean", 1.0) < 0.5  # Less than 0.5%
            ),
            "bandwidth_available": lambda post, pre: (
                post.get("bandwidth_util", 100) < 90  # Less than 90% utilization
            ),
            "node_responding": lambda post, pre: (
                post.get("node_responsive", False) is True
            )
        }
        
        return criteria
    
    def _collect_post_recovery_metrics(self, node_id: str) -> Dict[str, float]:
        """Collect current metrics for node"""
        
        try:
            # Query latest metrics from database
            latest_metrics = self.db.query(NetworkMetric).filter(
                NetworkMetric.node_id == node_id
            ).order_by(NetworkMetric.timestamp.desc()).limit(10).all()
            
            if not latest_metrics:
                return {"node_responsive": False}
            
            # Aggregate metrics by type
            metric_dict = {}
            for metric in latest_metrics:
                key = f"{metric.metric_type}_mean"
                if key not in metric_dict:
                    metric_dict[key] = []
                metric_dict[key].append(metric.value)
            
            # Calculate averages
            post_metrics = {
                "latency_mean": sum(metric_dict.get("latency_mean", [0])) / len(metric_dict.get("latency_mean", [1])),
                "packet_loss_mean": sum(metric_dict.get("packet_loss_mean", [0])) / len(metric_dict.get("packet_loss_mean", [1])),
                "bandwidth_util": sum(metric_dict.get("bandwidth_util", [0])) / len(metric_dict.get("bandwidth_util", [1])),
                "node_responsive": True
            }
            
            return post_metrics
        
        except Exception as e:
            logger.error(f"Error collecting post-recovery metrics: {e}")
            return {"node_responsive": False}
    
    def _compare_metrics(
        self,
        pre_metrics: Dict[str, float],
        post_metrics: Dict[str, float]
    ) -> Dict[str, Dict[str, float]]:
        """Compare pre and post recovery metrics"""
        
        improvements = {}
        
        for metric_name in pre_metrics.keys():
            if metric_name not in post_metrics:
                continue
            
            pre_value = pre_metrics[metric_name]
            post_value = post_metrics[metric_name]
            
            if metric_name in ["packet_loss_mean", "latency_mean"]:
                # Lower is better
                improvement = ((pre_value - post_value) / max(pre_value, 0.001)) * 100
            else:
                # For bandwidth: higher is better
                improvement = ((post_value - pre_value) / max(pre_value, 0.001)) * 100
            
            improvements[metric_name] = {
                "pre_value": pre_value,
                "post_value": post_value,
                "improvement_percent": improvement
            }
        
        return improvements
    
    def check_fallback_needed(
        self,
        verification_result: Dict[str, Any]
    ) -> bool:
        """
        Determine if fallback strategy should be triggered.
        
        Returns:
            True if fallback needed, False otherwise
        """
        
        # Trigger fallback if:
        # 1. Verification failed
        # 2. Confidence too low
        # 3. Critical criteria not met
        
        if not verification_result.get("verified"):
            return True
        
        if verification_result.get("confidence", 0) < 0.5:
            return True
        
        critical_failures = [
            criterion for criterion in verification_result.get("criteria_failed", [])
            if "critical" in criterion.lower() or "node_responding" in criterion
        ]
        
        if critical_failures:
            return True
        
        return False
    
    def trigger_fallback(
        self,
        recovery_id: str,
        incident_id: str,
        primary_recovery_actions: List[Dict[str, Any]],
        fallback_strategy: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Trigger fallback recovery strategy.
        
        Args:
            recovery_id: Original recovery ID
            incident_id: Associated incident
            primary_recovery_actions: Actions from primary recovery
            fallback_strategy: Fallback strategy to execute
            
        Returns:
            Fallback execution result
        """
        
        fallback_result = {
            "original_recovery_id": recovery_id,
            "incident_id": incident_id,
            "timestamp": datetime.utcnow().isoformat(),
            "fallback_triggered": True,
            "reason": "Primary recovery verification failed",
            "fallback_strategy": fallback_strategy.get("name"),
            "status": "in_progress",
            "actions_executed": []
        }
        
        try:
            logger.warning(
                f"Triggering fallback recovery for {incident_id} "
                f"(original recovery: {recovery_id})"
            )
            
            # Execute fallback actions
            for action in fallback_strategy.get("actions", []):
                action_result = {
                    "action": action.get("type"),
                    "target": action.get("target"),
                    "executed_at": datetime.utcnow().isoformat()
                }
                fallback_result["actions_executed"].append(action_result)
            
            fallback_result["status"] = "completed"
            
        except Exception as e:
            logger.error(f"Fallback execution error: {e}")
            fallback_result["status"] = "failed"
            fallback_result["error"] = str(e)
        
        return fallback_result
    
    def get_recovery_metrics(
        self,
        recovery_id: str
    ) -> Dict[str, Any]:
        """
        Get summary metrics for recovery attempt.
        
        Args:
            recovery_id: Recovery attempt ID
            
        Returns:
            Recovery metrics including MTTR, success rate, etc.
        """
        
        try:
            recovery = self.db.query(RecoveryAttempt).filter(
                RecoveryAttempt.recovery_id == recovery_id
            ).first()
            
            if not recovery:
                return {"error": "Recovery not found"}
            
            # Calculate metrics
            if recovery.start_time and recovery.end_time:
                mttr_seconds = (recovery.end_time - recovery.start_time).total_seconds()
            else:
                mttr_seconds = None
            
            metrics = {
                "recovery_id": recovery_id,
                "status": recovery.status.value,
                "verified": recovery.verified,
                "success": recovery.success,
                "mttr_seconds": mttr_seconds,
                "strategy": recovery.strategy_name,
                "actions_count": len(recovery.recovery_actions.get("actions", [])) if recovery.recovery_actions else 0
            }
            
            return metrics
        
        except Exception as e:
            logger.error(f"Error retrieving recovery metrics: {e}")
            return {"error": str(e)}
    
    def close(self):
        """Close database connection"""
        if self.db is not None:
            self.db.close()


# Global verification engine instance
_engine = None


def get_verification_engine() -> VerificationEngine:
    """Get or create global verification engine"""
    global _engine
    if _engine is None:
        _engine = VerificationEngine()
    return _engine
