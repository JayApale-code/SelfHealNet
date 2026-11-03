# explainability/__init__.py - Explainability and Interpretability Module

from typing import Dict, Any, List
import numpy as np
import pandas as pd
import logging
try:
    import shap
except ImportError:
    shap = None

try:
    from ..ml_engine import get_fault_prediction_model
except ImportError:
    try:
        from ml_engine import get_fault_prediction_model
    except ImportError:
        get_fault_prediction_model = None

logger = logging.getLogger(__name__)


class ExplainableDecisionEngine:
    """Select a recovery action and preserve the evidence for that choice."""

    def decide(
        self,
        diagnosis: Dict[str, Any],
        risk_assessment: Dict[str, Any],
        live_metrics: Dict[str, Any],
        alternate_path_available: Any = None,
    ) -> Dict[str, Any]:
        """Generate a recovery decision before any recovery action is executed.

        The diagnosis selects the action family, topology/path availability
        selects whether rerouting or failover is safe, and risk determines
        whether automation should stop at an operator alert. Evidence is copied
        into the result rather than reduced to an opaque score.
        """
        fault_type = str(diagnosis.get("fault_type", diagnosis.get("incident_type", "NORMAL"))).upper()
        risk_level = str(risk_assessment.get("risk_level", risk_assessment.get("severity_level", "MEDIUM"))).upper()
        path_available = self._path_available(alternate_path_available, diagnosis, live_metrics)
        evidence = list(diagnosis.get("supporting_metrics", []))
        if not evidence:
            evidence = self._metric_evidence(live_metrics)

        if fault_type == "LINK_FAILURE":
            if path_available:
                action = "REROUTE_TRAFFIC"
                reason = "Primary path unavailable and an alternate path is available."
                expected_effect = "Restore connectivity through the alternate path."
            else:
                action = "ALERT_OPERATIONS"
                reason = "Primary path unavailable and no alternate path is available for automated rerouting."
                expected_effect = "Escalate for manual link repair or emergency failover."
        elif fault_type == "CONGESTION":
            action = "TRAFFIC_ENGINEERING" if path_available else "APPLY_QOS"
            reason = (
                "An alternate path is available, so traffic can be redistributed away from the congested component."
                if path_available
                else "No alternate path is available, so traffic shaping is the least disruptive containment action."
            )
            expected_effect = "Reduce utilization, latency, and packet loss."
        elif fault_type == "CONNECTIVITY_FAILURE":
            action = "FAILOVER" if path_available else "ALERT_OPERATIONS"
            reason = (
                "Connectivity is unavailable and a redundant path supports failover."
                if path_available
                else "Connectivity is unavailable without a redundant path for automated recovery."
            )
            expected_effect = "Restore endpoint reachability through a redundant route." if path_available else "Initiate manual connectivity recovery."
        elif fault_type == "SERVICE_DEGRADATION":
            action = "APPLY_QOS"
            reason = "Service quality metrics are degraded; QoS can contain impact without changing topology."
            expected_effect = "Protect critical flows and stabilize service performance."
        else:
            action = "INCREASE_MONITORING"
            reason = "No actionable fault signature was confirmed; observe before changing network state."
            expected_effect = "Collect more evidence while avoiding unnecessary recovery changes."

        if risk_level == "CRITICAL" and action != "ALERT_OPERATIONS":
            action = "ALERT_OPERATIONS"
            reason = f"Risk is CRITICAL, so automated action is blocked. Original decision: {reason}"
            expected_effect = "Escalate for approval and controlled recovery."

        confidence = self._confidence(diagnosis, risk_assessment, evidence)
        return {
            "fault_type": fault_type,
            "selected_action": action,
            "reason": reason,
            "evidence": evidence,
            "expected_effect": expected_effect,
            "confidence": confidence,
            "risk": risk_level,
            "affected_component": diagnosis.get("affected_component", diagnosis.get("affected_node")),
        }

    generate_decision = decide

    @staticmethod
    def _path_available(value: Any, diagnosis: Dict[str, Any], metrics: Dict[str, Any]) -> bool:
        if value is None:
            value = diagnosis.get("alternate_path_available", metrics.get("alternate_path_available", False))
        if isinstance(value, str):
            return value.lower() in {"true", "yes", "available", "up"}
        if isinstance(value, bool):
            return value
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _metric_evidence(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"metric": key, "value": value}
            for key, value in metrics.items()
            if key not in {"timestamp", "status"}
        ]

    @staticmethod
    def _confidence(diagnosis: Dict[str, Any], risk: Dict[str, Any], evidence: List[Dict[str, Any]]) -> float:
        diagnosis_confidence = float(diagnosis.get("confidence", 0.0) or 0.0)
        risk_score = float(risk.get("risk_score", 0.0) or 0.0)
        evidence_bonus = min(len(evidence) * 0.03, 0.15)
        return round(min(1.0, max(diagnosis_confidence, risk_score / 100) + evidence_bonus), 3)


class ExplainabilityEngine:
    """
    Provides explainable AI explanations for model predictions and decisions.
    Integrates SHAP (SHapley Additive exPlanations) for model interpretability.
    """
    
    def __init__(self):
        self.explainer = None
        self._initialize_explainer()
    
    def _initialize_explainer(self):
        """Initialize SHAP explainer"""
        try:
            model = get_fault_prediction_model()
            if model.model is not None:
                # Use tree explainer for XGBoost
                self.explainer = shap.TreeExplainer(model.model)
                logger.info("SHAP explainer initialized")
            else:
                logger.warning("ML model not loaded, explainability unavailable")
        except Exception as e:
            logger.error(f"Failed to initialize SHAP explainer: {e}")
    
    def explain_prediction(
        self,
        prediction_data: pd.DataFrame,
        prediction_probability: float,
        feature_names: List[str]
    ) -> Dict[str, Any]:
        """
        Generate SHAP-based explanation for a fault prediction.
        
        Args:
            prediction_data: Feature vector for prediction
            prediction_probability: Predicted fault probability
            feature_names: Names of features
            
        Returns:
            Explanation with feature contributions and reasoning
        """
        if self.explainer is None or prediction_data.empty:
            return self._generate_fallback_explanation(
                prediction_probability,
                feature_names
            )
        
        try:
            # Calculate SHAP values
            shap_values = self.explainer.shap_values(prediction_data)
            
            # For binary classification, get values for fault class
            if isinstance(shap_values, list):
                shap_values = shap_values[1]
            
            # Get feature importance from SHAP
            feature_importance = np.abs(shap_values).mean(axis=0)
            
            # Create explanation dictionary
            explanation = {
                "prediction_probability": float(prediction_probability),
                "prediction_threshold": 0.7,
                "predicted_fault": prediction_probability > 0.7,
                "confidence": float(max(prediction_probability, 1 - prediction_probability)),
                "shap_values": self._prepare_shap_output(
                    shap_values[0],
                    prediction_data.values[0],
                    feature_names
                ),
                "top_contributing_features": self._get_top_features(
                    feature_importance,
                    feature_names,
                    top_n=5
                ),
                "reasoning": self._generate_reasoning(
                    prediction_probability,
                    shap_values[0],
                    feature_names,
                    prediction_data.values[0]
                )
            }
            
            return explanation
        
        except Exception as e:
            logger.error(f"Error in explain_prediction: {e}")
            return self._generate_fallback_explanation(
                prediction_probability,
                feature_names
            )
    
    def _prepare_shap_output(
        self,
        shap_values: np.ndarray,
        feature_values: np.ndarray,
        feature_names: List[str]
    ) -> List[Dict[str, Any]]:
        """Prepare SHAP values for output"""
        
        # Sort by absolute impact
        indices = np.argsort(np.abs(shap_values))[::-1]
        
        shap_output = []
        for idx in indices:
            shap_output.append({
                "feature_name": feature_names[idx],
                "shap_value": float(shap_values[idx]),
                "feature_value": float(feature_values[idx]),
                "impact": "positive" if shap_values[idx] > 0 else "negative"
            })
        
        return shap_output
    
    def _get_top_features(
        self,
        feature_importance: np.ndarray,
        feature_names: List[str],
        top_n: int = 5
    ) -> List[Dict[str, Any]]:
        """Get top contributing features"""
        
        indices = np.argsort(feature_importance)[::-1][:top_n]
        
        top_features = []
        for idx in indices:
            top_features.append({
                "rank": len(top_features) + 1,
                "feature_name": feature_names[idx],
                "importance_score": float(feature_importance[idx])
            })
        
        return top_features
    
    def _generate_reasoning(
        self,
        prediction_probability: float,
        shap_values: np.ndarray,
        feature_names: List[str],
        feature_values: np.ndarray
    ) -> str:
        """Generate human-readable reasoning for prediction"""
        
        if prediction_probability > 0.7:
            reasoning = f"HIGH FAULT PROBABILITY ({prediction_probability*100:.1f}%). "
        elif prediction_probability > 0.5:
            reasoning = f"ELEVATED FAULT PROBABILITY ({prediction_probability*100:.1f}%). "
        else:
            reasoning = f"LOW FAULT PROBABILITY ({prediction_probability*100:.1f}%). "
        
        # Find most influential features
        top_indices = np.argsort(np.abs(shap_values))[::-1][:3]
        
        contributing_features = []
        for idx in top_indices:
            feature = feature_names[idx]
            value = feature_values[idx]
            shap_val = shap_values[idx]
            direction = "increases" if shap_val > 0 else "decreases"
            contributing_features.append(
                f"{feature}={value:.2f} ({direction} fault likelihood)"
            )
        
        reasoning += "Key factors: " + ", ".join(contributing_features)
        
        return reasoning
    
    def _generate_fallback_explanation(
        self,
        prediction_probability: float,
        feature_names: List[str]
    ) -> Dict[str, Any]:
        """Generate explanation when SHAP is unavailable"""
        
        return {
            "prediction_probability": float(prediction_probability),
            "prediction_threshold": 0.7,
            "predicted_fault": prediction_probability > 0.7,
            "confidence": float(max(prediction_probability, 1 - prediction_probability)),
            "shap_values": [],
            "top_contributing_features": [],
            "reasoning": (
                f"Prediction: {prediction_probability*100:.1f}% fault probability. "
                "Detailed explanation unavailable - model not initialized. "
                "Please train the ML model first."
            )
        }
    
    def explain_diagnosis(
        self,
        diagnosis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Explain the diagnosis reasoning.
        
        Args:
            diagnosis: Diagnosis output from diagnosis engine
            
        Returns:
            Explanation with reasoning chain
        """
        
        explanation = {
            "incident_id": diagnosis.get("incident_id"),
            "incident_type": diagnosis.get("incident_type"),
            "root_cause": diagnosis.get("root_cause"),
            "confidence": diagnosis.get("confidence", 0.0),
            "reasoning_chain": self._build_reasoning_chain(diagnosis),
            "evidence": self._extract_evidence(diagnosis),
            "alternative_causes": self._suggest_alternatives(diagnosis)
        }
        
        return explanation
    
    def _build_reasoning_chain(self, diagnosis: Dict[str, Any]) -> List[str]:
        """Build step-by-step reasoning chain"""
        
        chain = [
            f"1. Incident Type: {diagnosis.get('incident_type')}",
            f"2. Affected Node: {diagnosis.get('affected_node')}",
            f"3. Identified Root Cause: {diagnosis.get('root_cause')}",
            f"4. Confidence Level: {diagnosis.get('confidence', 0)*100:.0f}%"
        ]
        
        if diagnosis.get("reasoning"):
            indicators = diagnosis["reasoning"].get("indicators", [])
            if indicators:
                chain.append("5. Supporting Indicators:")
                for i, indicator in enumerate(indicators):
                    chain.append(f"   - {indicator}")
        
        return chain
    
    def _extract_evidence(self, diagnosis: Dict[str, Any]) -> List[str]:
        """Extract supporting evidence from diagnosis"""
        
        evidence = []
        
        if diagnosis.get("reasoning"):
            indicators = diagnosis["reasoning"].get("indicators", [])
            evidence.extend(indicators)
        
        if diagnosis.get("affected_services"):
            evidence.append(
                f"Services affected: {', '.join(diagnosis['affected_services'])}"
            )
        
        return evidence
    
    def _suggest_alternatives(self, diagnosis: Dict[str, Any]) -> List[str]:
        """Suggest alternative root causes with lower confidence"""
        
        incident_type = diagnosis.get("incident_type")
        
        alternatives_map = {
            "link_failure": [
                "Configuration error causing interface shutdown",
                "BGP session flapping",
                "Physical link damage (fiber cut)"
            ],
            "congestion": [
                "DDoS attack (traffic spike)",
                "Routing loop causing traffic multiplication",
                "Misconfigured traffic policies"
            ],
            "high_latency": [
                "Suboptimal routing due to network changes",
                "Buffer bloat in intermediate nodes",
                "Wireless interference on wireless links"
            ],
            "packet_loss": [
                "Buffer overflow due to congestion",
                "CRC errors on physical link",
                "QoS policy dropping packets"
            ],
            "anomaly": [
                "Configuration change impact",
                "DDoS or security incident",
                "Scheduled maintenance effects"
            ]
        }
        
        return alternatives_map.get(incident_type, ["Unable to suggest alternatives"])


# Global explainability engine instance
_engine = None


def get_explainability_engine() -> ExplainabilityEngine:
    """Get or create global explainability engine"""
    global _engine
    if _engine is None:
        _engine = ExplainabilityEngine()
    return _engine
