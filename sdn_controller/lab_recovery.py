"""Safety checks for the fixed SelfHealNet Mininet lab recovery action."""

LAB_SWITCH_DPID = 1
LAB_PORTS = {1: "s1-eth1", 2: "s1-eth2"}
LAB_MARKER = "selfhealnet-mininet-v1"
PORT_DOWN_FLAG = 1


def is_recoverable_lab_port(
    enabled: bool,
    dpid: int,
    port_no: int,
    port_name: str,
    config: int,
) -> bool:
    return (
        enabled
        and isinstance(dpid, int)
        and not isinstance(dpid, bool)
        and isinstance(port_no, int)
        and not isinstance(port_no, bool)
        and dpid == LAB_SWITCH_DPID
        and LAB_PORTS.get(port_no) == port_name
        and isinstance(config, int)
        and not isinstance(config, bool)
        and config & PORT_DOWN_FLAG != 0
    )
