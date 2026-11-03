# Phase 12 Fallback Recovery

`RecoveryOrchestrator.execute_with_fallback` provides a bounded recovery
workflow:

1. Execute the primary strategy through the SDN controller.
2. Verify the attempt.
3. If verification fails, execute the alternative strategy.
4. Verify the alternative attempt.
5. If all permitted attempts fail, return `ESCALATED` with a critical
   administrator alert.

`max_attempts` counts total strategy executions, including the primary attempt.
It is clamped to a maximum of two for this phase, which permits one primary and
one fallback attempt and prevents infinite recovery loops. Every attempt stores
its strategy, execution result, and verification result in the returned audit
record. A successful verification returns `RECOVERY_SUCCESSFUL` immediately
and no further action is attempted.