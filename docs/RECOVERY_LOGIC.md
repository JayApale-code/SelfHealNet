# Recovery Logic Documentation

## Recovery flow
1. Detect anomaly or fault
2. Diagnose root cause
3. Score risk and severity
4. Select the least risky safe recovery action
5. Execute action through SDN or orchestration layer
6. Verify improvements
7. Trigger fallback if verification fails

## Verification criteria
After stabilization, the verification engine collects a new sample and checks
reachability, latency, packet loss, and utilization when those metrics are
available. Recovery is successful only when every evaluated criterion passes;
the result is `RECOVERY_SUCCESSFUL`, otherwise it is `RECOVERY_FAILED`. The
full thresholds and comparison behavior are documented in
`PHASE11_RECOVERY_VERIFICATION.md`.
