# Phase 7 Risk Assessment

`RiskAssessmentEngine.assess_risk` converts five operational factors into a
single score from 0 to 100. Each factor is scored as `LOW=10`, `MEDIUM=40`,
`HIGH=70`, or `CRITICAL=100`.

| Factor | Weight | Meaning |
| --- | ---: | --- |
| Severity | 30% | Severity reported by diagnosis |
| Traffic impact | 25% | Proportion or class of traffic affected |
| Affected component | 15% | Critical service, link, node, or unknown component |
| Recovery action risk | 20% | Risk of executing the proposed recovery |
| Alternate path | 10% | Adds risk when no alternate path is available |

The weighted factors are summed and classified as:

- `LOW`: score below 25
- `MEDIUM`: score 25 to 49.99
- `HIGH`: score 50 to 74.99
- `CRITICAL`: score 75 to 100

Traffic impact and recovery risk accept either a 0-1 fraction, a percentage,
or a severity label. Alternate-path availability accepts a boolean or a path
count. A missing or invalid factor uses a conservative `MEDIUM` factor value,
while an unavailable alternate path contributes the full 10 points.

The result includes the raw factor scores, weighted contributions, affected
component, and a human-readable `decision_logic` string so the classification
can be reviewed without opaque calculations.