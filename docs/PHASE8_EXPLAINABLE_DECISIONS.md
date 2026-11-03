# Phase 8 Explainable Decision Engine

`ExplainableDecisionEngine.decide` creates a recovery decision before any
recovery action is executed. The result records the fault, selected action,
reason, evidence, expected effect, confidence, risk, and affected component.

Decision logic:

- `LINK_FAILURE` with an alternate path selects `REROUTE_TRAFFIC`.
- `LINK_FAILURE` without an alternate path selects `ALERT_OPERATIONS`.
- `CONGESTION` selects `TRAFFIC_ENGINEERING` when an alternate path exists;
  otherwise it selects `APPLY_QOS` to contain the impact.
- `CONNECTIVITY_FAILURE` selects `FAILOVER` when a redundant path exists;
  otherwise it selects `ALERT_OPERATIONS`.
- `SERVICE_DEGRADATION` selects `APPLY_QOS`.
- An unconfirmed or normal condition selects `INCREASE_MONITORING`.
- A `CRITICAL` risk assessment overrides an automated action with
  `ALERT_OPERATIONS`, requiring approval and controlled recovery.

Evidence is taken from diagnosis `supporting_metrics`; when that field is
empty, the live metrics are preserved as evidence. Confidence combines the
diagnosis confidence, risk score, and a small evidence-count bonus, capped at
1.0.
