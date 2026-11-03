# Network Fault Prediction Dataset

This directory contains a prototype dataset for network-fault classification in the SelfHealNet project.

## Data provenance

The dataset is synthetic and generated from controlled fault-injection scenarios designed to resemble a small Software-Defined Network (SDN) topology running on Mininet or an equivalent deterministic simulation environment. The labels are produced from rule-based scenarios rather than from a fabricated production deployment claim.

This is appropriate for a college prototype and academic evaluation, but it should not be interpreted as a production-grade telemetry corpus. When a real Mininet measurement pipeline is available, the dataset should be refreshed with actual measurements.

## Label definitions

- NORMAL: healthy traffic, stable routing, low packet loss, low latency.
- CONGESTION: sustained queue buildup, elevated bandwidth usage, moderate packet loss, reduced throughput.
- LINK_FAILURE: one path fails or becomes unusable; latency rises sharply and packet loss climbs.
- SERVICE_DEGRADATION: application or service behavior is degraded while basic connectivity remains available.
- CONNECTIVITY_FAILURE: route loss or severe outage; throughput collapses and connectivity score drops near zero.

## Feature definitions

| Feature | Description |
| --- | --- |
| label | Target class used for supervised learning. |
| source | Source host or node in the simulation. |
| destination | Destination host or node in the simulation. |
| latency_ms | End-to-end round-trip latency in milliseconds. |
| jitter_ms | Variation in latency across packets or flows. |
| packet_loss_pct | Percentage of packets lost during forwarding. |
| throughput_mbps | Delivered application throughput in megabits per second. |
| bandwidth_utilization_pct | Link utilization percentage. |
| cpu_utilization_pct | Controller or switch CPU percentage. |
| memory_utilization_pct | Controller or switch memory percentage. |
| active_flows | Number of active flows in the simulated network. |
| retransmissions_pct | Retransmitted packet percentage. |
| dropped_packets | Count of dropped packets over the observation window. |
| link_status | Current operational state such as up or down. |
| route_redundancy | Number of alternate paths available. |
| connectivity_score | Relative reachability score from 0.0 to 1.0. |
| fault_scenario | Controlled scenario used to generate the row. |

## File

- network_fault_dataset.csv: generated dataset for model training and evaluation.
- generate_network_fault_dataset.py: deterministic generator used to create the CSV.

## Notes

- The generated dataset is intentionally balanced across labels.
- The values are tuned to match common operational ranges for a small network and should be calibrated against real telemetry before deployment.
- The design supports future augmentation with live Mininet measurements once the Linux test environment is available.
