# risk_assessment/__init__.py - Risk and Severity Assessment Module

from typing import Dict, Any, List, Mapping
from enum import Enum
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class RiskCategory(str, Enum):
    """Risk categories"""
    CONNECTIVITY = "connectivity"
    PERFORMANCE = "performance"
    SECURITY = "security"
    AVAILABILITY = "availability"
    DATA_INTEGRITY = "data_integrity"


class RiskAssessmentEngine:
    """
    Assesses risk and severity of network incidents.
    Combines impact, probability, and criticality factors.
    """
    
    # Risk scoring matrices
    IMPACT_SCORE = {
        "low": 1,      # Affects single device/user
        "medium": 3,   # Affects service component
        "high": 7,     # Affects critical service
        "critical": 10 # Affects multiple critical services
    }
    
    PROBABILITY_SCORE = {
        "low": 0.1,      # Rare occurrence (< 1% chance)
        "medium": 0.5,   # Occasional (1-10% chance)
        "high": 0.8,     # Frequent (10-50% chance)
        "certain": 1.0   # Already occurred or will occur
    }
    
    CRITICALITY_SCORE = {
        "low": 0.5,      # Non-essential service
        "medium": 1.0,   # Important but redundant
        "high": 1.5,     # Critical, limited redundancy
        "critical": 2.0  # Business-critical, no redundancy
    }

    # Phase 7 weights. The weights add up to 100 and are documented in
    # docs/PHASE7_RISK_ASSESSMENT.md.
    RISK_WEIGHTS = {
        "severity": 30,
        "traffic_impact": 25,
        "affected_component": 15,
        "recovery_action_risk": 20,
        "alternate_path": 10,
    }

    def assess_risk(
        self,
        diagnosis: Mapping[str, Any],
        traffic_impact: Any,
        recovery_action_risk: Any,
        alternate_path_available: Any,
        affected_component: Any = None,
    ) -> Dict[str, Any]:
        """Return an explainable LOW-to-CRITICAL operational risk assessment.

        Inputs may use either numeric values from 0 to 1 or the labels
        ``low``, ``medium``, ``high``, and ``critical``. Numeric traffic and
        recovery values above 1 are treated as percentages and capped at 100.
        ``alternate_path_available`` accepts a boolean, a path count, or a
        matching availability label.
        """
        severity = self._level(diagnosis.get("severity", "medium"))
        component = affected_component or diagnosis.get("affected_component") or diagnosis.get("affected_node") or "unknown"
        component_level = self._component_level(component, diagnosis)
        traffic_level = self._factor_level(traffic_impact)
        recovery_level = self._factor_level(recovery_action_risk)
        alternate_score = self._alternate_path_score(alternate_path_available)

        factor_scores = {
            "severity": self._level_score(severity),
            "traffic_impact": self._level_score(traffic_level),
            "affected_component": self._level_score(component_level),
            "recovery_action_risk": self._level_score(recovery_level),
            "alternate_path": alternate_score,
        }
        weighted_scores = {
            factor: round(self.RISK_WEIGHTS[factor] * score / 100, 2)
            for factor, score in factor_scores.items()
        }
        risk_score = round(sum(weighted_scores.values()), 2)
        risk_level = self._risk_level(risk_score)

        return {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "affected_component": component,
            "factor_scores": factor_scores,
            "weighted_scores": weighted_scores,
            "decision_logic": self._decision_logic(
                severity,
                traffic_level,
                component_level,
                recovery_level,
                alternate_path_available,
            ),
        }

    @staticmethod
    def _level(value: Any) -> str:
        normalized = str(value).lower()
        return normalized if normalized in {"low", "medium", "high", "critical"} else "medium"

    @classmethod
    def _factor_level(cls, value: Any) -> str:
        if isinstance(value, Mapping):
            value = value.get("level", value.get("impact", value.get("risk", "medium")))
        if isinstance(value, str):
            return cls._level(value)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "medium"
        if numeric > 1:
            numeric /= 100
        if numeric < 0.25:
            return "low"
        if numeric < 0.5:
            return "medium"
        if numeric < 0.75:
            return "high"
        return "critical"

    @staticmethod
    def _level_score(level: str) -> int:
        return {"low": 10, "medium": 40, "high": 70, "critical": 100}[level]

    @classmethod
    def _component_level(cls, component: Any, diagnosis: Mapping[str, Any]) -> str:
        services = diagnosis.get("affected_services", [])
        if any(service in {"database", "authentication", "payment-processing", "api-gateway"} for service in services):
            return "critical"
        if len(services) >= 3 or "link" in str(component).lower():
            return "high"
        if component == "unknown":
            return "low"
        return "medium"

    @staticmethod
    def _alternate_path_score(value: Any) -> int:
        if isinstance(value, str):
            return 10 if value.lower() in {"none", "unavailable", "false", "no", "down"} else 0
        if isinstance(value, bool):
            return 0 if value else 10
        try:
            return 0 if float(value) > 0 else 10
        except (TypeError, ValueError):
            return 5

    @staticmethod
    def _risk_level(score: float) -> str:
        if score >= 75:
            return "CRITICAL"
        if score >= 50:
            return "HIGH"
        if score >= 25:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _decision_logic(
        severity: str,
        traffic: str,
        component: str,
        recovery: str,
        alternate_path: Any,
    ) -> str:
        path_text = "available" if RiskAssessmentEngine._alternate_path_score(alternate_path) == 0 else "unavailable or insufficient"
        return (
            f"Severity={severity}; traffic impact={traffic}; affected component={component}; "
            f"recovery action risk={recovery}; alternate path={path_text}. "
            "These factors are combined using the documented Phase 7 weights."
        )
    
    def assess_incident(
        self,
        incident_id: str,
        incident_type: str,
        diagnosis: Dict[str, Any],
        metrics: Dict[str, float],
        topology_data: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Assess risk and severity of an incident.
        
        Args:
            incident_id: Incident identifier
            incident_type: Type of incident
            diagnosis: Diagnosis results
            metrics: Network metrics
            topology_data: Network topology information
            
        Returns:
            Risk assessment with scores and recommendations
        """
        assessment = {
            "incident_id": incident_id,
            "timestamp": datetime.utcnow().isoformat(),
            "risk_score": 0.0,
            "severity_level": "low",
            "impact": "low",
            "probability": "medium",
            "criticality": "medium",
            "affected_services": diagnosis.get("affected_services", []),
            "sla_impact": None,
            "recovery_priority": "normal",
            "risk_factors": [],
            "recommendations": []
        }
        
        # Determine impact level
        impact_level = self._assess_impact(incident_type, diagnosis, metrics)
        assessment["impact"] = impact_level
        
        # Determine probability
        probability_level = self._assess_probability(incident_type, metrics)
        assessment["probability"] = probability_level
        
        # Determine criticality
        criticality_level = self._assess_criticality(
            diagnosis.get("affected_services", []),
            topology_data
        )
        assessment["criticality"] = criticality_level
        
        # Calculate risk score: Impact × Probability × Criticality
        risk_score = (
            self.IMPACT_SCORE[impact_level] *
            self.PROBABILITY_SCORE[probability_level] *
            self.CRITICALITY_SCORE[criticality_level]
        )
        assessment["risk_score"] = risk_score
        
        # Determine severity level
        assessment["severity_level"] = self._score_to_severity(risk_score)
        
        # Assess SLA impact
        assessment["sla_impact"] = self._assess_sla_impact(
            incident_type,
            assessment["severity_level"],
            assessment["affected_services"]
        )
        
        # Determine recovery priority
        assessment["recovery_priority"] = self._get_recovery_priority(risk_score)
        
        # Identify risk factors
        assessment["risk_factors"] = self._identify_risk_factors(
            incident_type,
            metrics,
            diagnosis
        )
        
        # Generate recommendations
        assessment["recommendations"] = self._generate_recommendations(
            incident_type,
            assessment["severity_level"],
            assessment["affected_services"]
        )
        
        logger.info(
            f"Risk assessment: {incident_id} - "
            f"Severity: {assessment['severity_level']}, "
            f"Risk Score: {risk_score:.2f}"
        )
        
        return assessment
    
    def _assess_impact(
        self,
        incident_type: str,
        diagnosis: Dict[str, Any],
        metrics: Dict[str, float]
    ) -> str:
        """Assess impact level of incident"""
        
        if incident_type == "link_failure":
            return "critical"
        elif incident_type == "node_failure":
            return "critical"
        elif incident_type == "congestion":
            util = metrics.get("bandwidth_util", 0)
            return "critical" if util > 95 else "high"
        elif incident_type == "high_latency":
            latency = metrics.get("latency_mean", 0)
            if latency > 150:
                return "high"
            elif latency > 100:
                return "medium"
            else:
                return "low"
        elif incident_type == "packet_loss":
            loss = metrics.get("packet_loss_mean", 0)
            if loss > 5:
                return "critical"
            elif loss > 1:
                return "high"
            else:
                return "medium"
        elif incident_type == "anomaly":
            confidence = diagnosis.get("confidence", 0)
            return "high" if confidence > 0.7 else "medium"
        else:
            return "medium"
    
    def _assess_probability(self, incident_type: str, metrics: Dict) -> str:
        """Assess probability of incident occurring again"""
        
        # Check metric volatility and trend
        latency = metrics.get("latency_mean", 0)
        packet_loss = metrics.get("packet_loss_mean", 0)
        bandwidth = metrics.get("bandwidth_util", 0)
        
        # Multiple degraded metrics suggest higher probability
        degraded_metrics = sum([
            latency > 50,
            packet_loss > 0.1,
            bandwidth > 80
        ])
        
        if degraded_metrics >= 2:
            return "high"
        elif degraded_metrics == 1:
            return "medium"
        else:
            return "low"
    
    def _assess_criticality(
        self,
        affected_services: List[str],
        topology_data: Dict[str, Any] = None
    ) -> str:
        """Assess criticality based on affected services"""
        
        # Critical services
        critical_services = [
            "database",
            "api-gateway",
            "authentication",
            "payment-processing"
        ]
        
        # Check if any critical services are affected
        if any(service in critical_services for service in affected_services):
            return "critical"
        
        # High criticality services
        high_services = [
            "web-server",
            "load-balancer",
            "cache"
        ]
        
        if any(service in high_services for service in affected_services):
            return "high"
        
        # Default based on number of affected services
        if len(affected_services) > 3:
            return "medium"
        
        return "low"
    
    def _score_to_severity(self, risk_score: float) -> str:
        """Convert risk score to severity level"""
        if risk_score >= 15:
            return "critical"
        elif risk_score >= 7:
            return "high"
        elif risk_score >= 3:
            return "medium"
        else:
            return "low"
    
    def _assess_sla_impact(
        self,
        incident_type: str,
        severity: str,
        affected_services: List[str]
    ) -> Dict[str, Any]:
        """Assess impact on SLA requirements"""
        
        # SLA requirements (uptime %)
        sla_requirements = {
            "database": 99.99,
            "api-gateway": 99.9,
            "web-server": 99.5,
            "cache": 99.0
        }
        
        # Calculate potential SLA violation
        affected_slas = [
            sla_requirements.get(svc, 99.0)
            for svc in affected_services
        ]
        
        if not affected_slas:
            return {
                "violation_risk": "low",
                "estimated_downtime_minutes": 0
            }
        
        avg_sla = sum(affected_slas) / len(affected_slas)
        
        # Estimate downtime based on severity
        downtime_map = {
            "critical": 60,
            "high": 15,
            "medium": 5,
            "low": 1
        }
        
        estimated_downtime = downtime_map.get(severity, 5)
        
        # Check if this would violate SLA
        violation_risk = "high" if avg_sla > 99.5 else "medium"
        
        return {
            "affected_services_slas": dict(zip(affected_services, affected_slas)),
            "average_sla_requirement": avg_sla,
            "violation_risk": violation_risk,
            "estimated_downtime_minutes": estimated_downtime
        }
    
    def _get_recovery_priority(self, risk_score: float) -> str:
        """Get recovery priority based on risk score"""
        if risk_score >= 15:
            return "immediate"
        elif risk_score >= 7:
            return "urgent"
        elif risk_score >= 3:
            return "high"
        else:
            return "normal"
    
    def _identify_risk_factors(
        self,
        incident_type: str,
        metrics: Dict[str, float],
        diagnosis: Dict[str, Any]
    ) -> List[str]:
        """Identify risk factors contributing to incident"""
        
        factors = []
        
        # Check metric thresholds
        if metrics.get("latency_mean", 0) > 100:
            factors.append("High latency exceeds normal range")
        
        if metrics.get("packet_loss_mean", 0) > 1:
            factors.append("Packet loss indicates link quality degradation")
        
        if metrics.get("bandwidth_util", 0) > 90:
            factors.append("Network utilization critically high")
        
        if metrics.get("jitter_mean", 0) > 20:
            factors.append("High jitter suggests unstable link")
        
        # Incident-specific factors
        if incident_type == "anomaly":
            factors.append("Anomalous patterns detected - requires investigation")
        
        if diagnosis.get("affected_services"):
            factors.append(f"Multiple services affected: {len(diagnosis['affected_services'])}")
        
        return factors or ["Standard incident risk factors"]
    
    def _generate_recommendations(
        self,
        incident_type: str,
        severity: str,
        affected_services: List[str]
    ) -> List[str]:
        """Generate remediation recommendations"""
        
        recommendations = []
        
        # Severity-based recommendations
        if severity in ["critical", "high"]:
            recommendations.append("IMMEDIATE: Initiate incident response team")
            recommendations.append("IMMEDIATE: Notify stakeholders and affected users")
        
        # Incident-type specific recommendations
        if incident_type == "link_failure":
            recommendations.append("Verify physical connections")
            recommendations.append("Check for BGP session establishment")
            recommendations.append("Consider failover to backup link")
        
        elif incident_type == "congestion":
            recommendations.append("Implement traffic shaping or QoS policies")
            recommendations.append("Increase link capacity if possible")
            recommendations.append("Route traffic to alternative paths")
        
        elif incident_type == "high_latency":
            recommendations.append("Analyze routing paths for optimization")
            recommendations.append("Check link utilization and capacity")
            recommendations.append("Monitor for ongoing performance degradation")
        
        elif incident_type == "packet_loss":
            recommendations.append("Check physical link quality (CRC errors)")
            recommendations.append("Verify buffer availability")
            recommendations.append("Consider link replacement if persistent")
        
        # Service-specific recommendations
        if "database" in affected_services:
            recommendations.append("Ensure database replication is functioning")
        
        if "api-gateway" in affected_services:
            recommendations.append("Monitor API response times and error rates")
        
        if "web-server" in affected_services:
            recommendations.append("Verify web server health and session persistence")
        
        return recommendations or ["Monitor situation and prepare for escalation"]


# Global risk assessment engine instance
_engine = None


def get_risk_assessment_engine() -> RiskAssessmentEngine:
    """Get or create global risk assessment engine"""
    global _engine
    if _engine is None:
        _engine = RiskAssessmentEngine()
    return _engine
