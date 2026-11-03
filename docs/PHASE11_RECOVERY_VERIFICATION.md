# Phase 11 Recovery Verification

`VerificationEngine.verify_metrics` waits for the configured stabilization
interval, collects a fresh metric sample, and compares it with the pre-recovery
sample. A supplied `metric_collector` is called only after the wait; callers
may also provide already-collected post-recovery metrics.

The default criteria are:

- The node is responsive, the link is `up`, or connectivity is restored when
  that signal is present.
- Post-recovery latency is no more than 120% of the pre-recovery value, with a
  50 ms floor for small baselines.
- Post-recovery packet loss is no more than 25% of the previous value, with a
  3% ceiling for low-loss baselines.
- Post-recovery bandwidth utilization is at most 85%.

Only criteria for metrics actually supplied are evaluated. Recovery is
`RECOVERY_SUCCESSFUL` when every evaluated criterion passes; otherwise it is
`RECOVERY_FAILED`. The result preserves before/after samples, per-metric
changes, criteria met, criteria failed, stabilization time, and confidence.