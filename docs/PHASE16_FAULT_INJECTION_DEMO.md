# Phase 16 Fault Injection Demo

Run the controlled end-to-end demo from the repository root:

```text
python -m demo.phase16_fault_injection
```

The `FaultInjectionDemo` pipeline is:

`NORMAL NETWORK -> inject fault -> monitoring -> ML prediction -> diagnosis -> decision -> safety check -> SDN state change -> verification -> SELF-HEALED`

Supported scenarios are `link_failure`, `congestion`, and
`connectivity_failure`. `run_fallback_demo()` demonstrates a failed primary
attempt followed by a bounded fallback attempt. The controller state is
returned with routes, flows, links, QoS policies, and services so the demo
proves an underlying state change rather than a dashboard-only status update.