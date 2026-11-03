# Phase 9 Safety Check

`SafetyChecker.validate_action` is the mandatory pre-action gate for recovery.
It evaluates each action immediately before execution and appends the result to
`decision_log`.

The checks are:

1. **Supported action**: the action type must be in the recovery allowlist.
2. **Required alternate path**: rerouting, failover-related link changes, and
   route changes require an available alternate path.
3. **Required resource**: backup links and explicitly requested resources must
   be present in the current network state.
4. **Estimated impact**: an action's affected-node count must stay within
   `max_affected_nodes` when configured.
5. **Overload prevention**: each target link's current utilization plus the
   proposed traffic shift must remain at or below 85%.

An action is safe only when every check passes. Unsafe actions are skipped by
`RecoveryOrchestrator.execute_recovery`, an administrator alert is attached to
the execution error, and the complete decision is recorded in the safety
checker log. Safe actions proceed to the existing executor, including dry-run
mode.
