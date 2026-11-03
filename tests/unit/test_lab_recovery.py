from sdn_controller.lab_recovery import is_recoverable_lab_port


def test_auto_recovery_allows_only_admin_down_ports_on_managed_lab_switch():
    assert is_recoverable_lab_port(True, 1, 1, "s1-eth1", 1)
    assert is_recoverable_lab_port(True, 1, 2, "s1-eth2", 3)


def test_auto_recovery_rejects_non_lab_targets_and_non_admin_faults():
    assert not is_recoverable_lab_port(False, 1, 1, "s1-eth1", 1)
    assert not is_recoverable_lab_port(True, 2, 1, "s1-eth1", 1)
    assert not is_recoverable_lab_port(True, 1, 3, "s1-eth3", 1)
    assert not is_recoverable_lab_port(True, 1, 1, "eth0", 1)
    assert not is_recoverable_lab_port(True, 1, 1, "s1-eth1", 0)
    assert not is_recoverable_lab_port(True, 1, 1, "s1-eth1", True)
