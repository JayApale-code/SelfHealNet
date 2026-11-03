# SDN Simulation Phase

## Goal
Provide a reproducible, deterministic virtual network suitable for SDN recovery experiments.

## Topology model
The simulation creates a layered topology with:
- multiple hosts
- multiple OpenFlow-capable switches
- deterministic redundant paths
- a reproducible link set for test scenarios

## Reproducibility model
The topology builder always creates the same host and switch naming scheme and deterministic link layout for a given host/switch count.

## Fault injection workflow
1. Build topology
2. Verify connectivity
3. Generate traffic
4. Inject link failure
5. Verify alternate route or failover state
6. Recover and validate routing

## Environment note
This design supports real Mininet execution on Linux-based environments and also includes a Python-only fallback for validation in non-Mininet hosts.
