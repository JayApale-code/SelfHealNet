from demo.phase16_fault_injection import FaultInjectionDemo


def test_link_failure_demo_self_heals_and_changes_path():
    result = FaultInjectionDemo().run("link_failure")

    assert result["dashboard_status"] == "SELF-HEALED"
    assert result["diagnosis"]["fault_type"] == "LINK_FAILURE"
    assert result["controller_state"]["routes"]["flow-a-b"] == ["host-a", "switch-1", "router-a", "host-b"]
    assert result["verification"]["result"] == "RECOVERY_SUCCESSFUL"


def test_congestion_and_connectivity_demos_self_heal():
    congestion = FaultInjectionDemo().run("congestion")
    connectivity = FaultInjectionDemo().run("connectivity_failure")

    assert congestion["dashboard_status"] == "SELF-HEALED"
    assert congestion["controller_state"]["qos_policies"]["router-a"]["rate_mbps"] == 100
    assert connectivity["dashboard_status"] == "SELF-HEALED"
    assert connectivity["controller_state"]["flows"]["flow-a-b"]["status"] == "active"


def test_failed_recovery_fallback_is_bounded():
    result = FaultInjectionDemo().run_fallback_demo()

    assert result["dashboard_status"] == "SELF-HEALED"
    assert len(result["recovery"]["attempts"]) == 2
    assert result["recovery"]["successful_attempt"] == 2