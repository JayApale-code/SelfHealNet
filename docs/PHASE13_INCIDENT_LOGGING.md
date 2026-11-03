# Phase 13 Incident Logging

`IncidentLogger` creates one complete record for every incident and updates the
same record as recovery proceeds. Records include the incident ID and
timestamp, detected fault, affected component, live metrics, ML prediction and
confidence, severity, selected action, safety result, recovery result,
verification metrics, fallback action, and final status.

The only terminal statuses are:

- `RESOLVED`: recovery verification succeeded.
- `FAILED`: recovery was attempted and did not succeed.
- `ESCALATED`: permitted recovery attempts were exhausted and an administrator
  was alerted.

The logger rejects duplicate incident IDs and rejects updates to fields outside
the lifecycle audit fields. Pass a SQLAlchemy session to `IncidentLogger` to
persist records in `network_incidents`; without a session it retains records in
memory for adapters and tests.