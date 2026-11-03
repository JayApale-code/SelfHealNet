"""Local-only OpenFlow 1.3 learning switch and read-only stats API for the lab."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
from typing import Any
from urllib.parse import urlsplit

from os_ken.base import app_manager
from os_ken import cfg
from os_ken.controller import controller as _controller  # Register OpenFlow options.
from os_ken.controller import ofp_event
from os_ken.controller.handler import (
    CONFIG_DISPATCHER,
    DEAD_DISPATCHER,
    MAIN_DISPATCHER,
    set_ev_cls,
)
from os_ken.lib import hub
from os_ken.lib.packet import ethernet, ether_types, packet
from os_ken.ofproto import ofproto_v1_3

from sdn_controller.lab_recovery import is_recoverable_lab_port

LOG = logging.getLogger("selfhealnet.sdn_lab")
_REQUIRED_APP = ["os_ken.controller.ofp_handler"]
_AUTO_RECOVERY_PROFILE = "mininet-admin-down-port-v1"


class _StatsServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: "OsKenLabController") -> None:
        super().__init__(address, _StatsHandler)
        self.app = app


class _StatsHandler(BaseHTTPRequestHandler):
    server: _StatsServer

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        try:
            payload = self.server.app.rest_payload(path)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        if payload is None:
            self._send_json(404, {"error": "endpoint not found"})
            return
        self._send_json(200, payload)

    def do_POST(self) -> None:
        self._send_json(405, {"error": "read-only endpoint"})

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        LOG.info("REST %s - %s", self.address_string(), format % args)


class OsKenLabController(app_manager.OSKenApp):
    """Minimal learning switch with local, read-only Ryu-compatible telemetry."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lock = threading.RLock()
        self._datapaths: dict[int, Any] = {}
        self._mac_to_port: dict[int, dict[str, int]] = defaultdict(dict)
        self._ports: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self._port_descriptions: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
        self._flows: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self._httpd: _StatsServer | None = None
        self._http_thread: threading.Thread | None = None
        self._poller: Any = None
        self._poll_interval = 2.0
        self._auto_recovery_enabled = cfg.CONF.selfhealnet_lab_auto_recovery_enabled
        self._auto_recovery_attempted: set[tuple[int, int]] = set()
        self._auto_recovery = {
            "enabled": self._auto_recovery_enabled,
            "attempts": 0,
            "last_result": None,
            "last_port": None,
            "last_updated_at": None,
        }

    def start(self) -> Any:
        thread = super().start()
        host = cfg.CONF.selfhealnet_rest_host
        port = cfg.CONF.selfhealnet_rest_port
        try:
            self._httpd = _StatsServer((host, port), self)
            self._http_thread = threading.Thread(
                target=self._httpd.serve_forever,
                name="selfhealnet-osken-rest",
                daemon=True,
            )
            self._http_thread.start()
        except OSError:
            thread.kill()
            raise
        self._poller = hub.spawn(self._poll_stats)
        LOG.info(
            "OS-Ken lab controller listening for OpenFlow on %s:%s; read-only REST on %s:%s; lab auto-recovery=%s",
            cfg.CONF.ofp_listen_host,
            cfg.CONF.ofp_tcp_listen_port,
            host,
            port,
            self._auto_recovery_enabled,
        )
        return thread

    def close(self) -> None:
        if self._poller is not None:
            self._poller.kill()
            self._poller = None
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        super().close()

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change(self, ev: Any) -> None:
        datapath = ev.datapath
        dpid = datapath.id
        with self._lock:
            if ev.state == MAIN_DISPATCHER:
                self._datapaths[dpid] = datapath
                LOG.info("OpenFlow switch connected: dpid=%016x", dpid)
            elif self._datapaths.pop(dpid, None) is not None:
                self._mac_to_port.pop(dpid, None)
                self._ports.pop(dpid, None)
                self._port_descriptions.pop(dpid, None)
                self._flows.pop(dpid, None)
                self._auto_recovery_attempted = {
                    key for key in self._auto_recovery_attempted if key[0] != dpid
                }
                LOG.info("OpenFlow switch disconnected: dpid=%016x", dpid)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features(self, ev: Any) -> None:
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, 0, parser.OFPMatch(), actions, idle_timeout=0)
        with self._lock:
            self._port_descriptions[datapath.id] = {
                item.port_no: self._port_description(item)
                for item in getattr(ev.msg, "ports", {}).values()
            }
        for port in getattr(ev.msg, "ports", {}).values():
            self._restore_admin_down_lab_port(datapath, port)
        LOG.info("OpenFlow features received: dpid=%016x ports=%d", datapath.id, len(self._port_descriptions[datapath.id]))

    @staticmethod
    def _port_description(port: Any) -> dict[str, Any]:
        return {
            "port_no": port.port_no,
            "name": port.name.decode(errors="replace").rstrip("\x00"),
            "config": port.config,
            "state": port.state,
            "curr": getattr(port, "curr", None),
            "advertised": getattr(port, "advertised", None),
            "supported": getattr(port, "supported", None),
            "peer": getattr(port, "peer", None),
        }

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def _port_status(self, ev: Any) -> None:
        datapath = ev.msg.datapath
        port = ev.msg.desc
        port_name = port.name.decode(errors="replace").rstrip("\x00")
        key = (datapath.id, port.port_no)
        should_recover = False
        with self._lock:
            if ev.msg.reason == datapath.ofproto.OFPPR_DELETE:
                self._port_descriptions[datapath.id].pop(port.port_no, None)
                self._ports[datapath.id] = [
                    item for item in self._ports[datapath.id]
                    if item.get("port_no") != port.port_no
                ]
                self._auto_recovery_attempted.discard(key)
            else:
                self._port_descriptions[datapath.id][port.port_no] = self._port_description(port)
                if port.config & datapath.ofproto.OFPPC_PORT_DOWN:
                    should_recover = True
                elif key in self._auto_recovery_attempted:
                    self._auto_recovery_attempted.discard(key)
                    self._auto_recovery.update({
                        "last_result": "verified",
                        "last_port": f"{datapath.id}:{port_name}",
                        "last_updated_at": datetime.now(timezone.utc).isoformat(),
                    })
                    LOG.info(
                        "Mininet lab port recovery verified: dpid=%016x port=%s",
                        datapath.id,
                        port_name,
                    )
        if should_recover:
            self._restore_admin_down_lab_port(datapath, port)
        LOG.info("OpenFlow port inventory changed: dpid=%016x port=%d", datapath.id, port.port_no)

    def _restore_admin_down_lab_port(self, datapath: Any, port: Any) -> None:
        port_name = port.name.decode(errors="replace").rstrip("\x00")
        if not is_recoverable_lab_port(
            self._auto_recovery_enabled,
            datapath.id,
            port.port_no,
            port_name,
            port.config,
        ):
            return

        key = (datapath.id, port.port_no)
        with self._lock:
            if key in self._auto_recovery_attempted:
                return

        with self._lock:
            if key in self._auto_recovery_attempted:
                return
            self._auto_recovery_attempted.add(key)
            self._auto_recovery.update({
                "attempts": self._auto_recovery["attempts"] + 1,
                "last_result": "requested",
                "last_port": f"{datapath.id}:{port_name}",
                "last_updated_at": datetime.now(timezone.utc).isoformat(),
            })

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        try:
            datapath.send_msg(
                parser.OFPPortMod(
                    datapath=datapath,
                    port_no=port.port_no,
                    hw_addr=port.hw_addr,
                    config=0,
                    mask=ofproto.OFPPC_PORT_DOWN,
                    advertise=port.curr,
                )
            )
        except Exception:
            with self._lock:
                self._auto_recovery_attempted.discard(key)
                self._auto_recovery.update({
                    "last_result": "failed",
                    "last_updated_at": datetime.now(timezone.utc).isoformat(),
                })
            LOG.exception(
                "Failed to restore allowlisted Mininet port: dpid=%016x port=%s",
                datapath.id,
                port_name,
            )
            raise

        LOG.warning(
            "Mininet lab auto-recovery requested: clearing administrative-down on dpid=%016x port=%s",
            datapath.id,
            port_name,
        )

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in(self, ev: Any) -> None:
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match.get("in_port")
        if in_port is None:
            return
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        table = self._mac_to_port[datapath.id]
        table[eth.src] = in_port
        out_port = table.get(eth.dst, ofproto.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst)
            self._add_flow(datapath, 10, match, actions)

        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        datapath.send_msg(
            parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=data,
            )
        )

    @staticmethod
    def _add_flow(
        datapath: Any,
        priority: int,
        match: Any,
        actions: list[Any],
        idle_timeout: int = 60,
    ) -> None:
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        instructions = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        datapath.send_msg(
            parser.OFPFlowMod(
                datapath=datapath,
                priority=priority,
                match=match,
                instructions=instructions,
                idle_timeout=idle_timeout,
            )
        )

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply(self, ev: Any) -> None:
        with self._lock:
            self._ports[ev.msg.datapath.id] = [
                {
                    "port_no": stat.port_no,
                    "rx_bytes": stat.rx_bytes,
                    "tx_bytes": stat.tx_bytes,
                    "rx_packets": stat.rx_packets,
                    "tx_packets": stat.tx_packets,
                    "rx_dropped": stat.rx_dropped,
                    "tx_dropped": stat.tx_dropped,
                    "rx_errors": stat.rx_errors,
                    "tx_errors": stat.tx_errors,
                }
                for stat in ev.msg.body
            ]

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply(self, ev: Any) -> None:
        with self._lock:
            self._flows[ev.msg.datapath.id] = [
                {
                    "table_id": stat.table_id,
                    "priority": stat.priority,
                    "packet_count": stat.packet_count,
                    "byte_count": stat.byte_count,
                    "duration_sec": stat.duration_sec,
                    "match": str(stat.match),
                    "instructions": [str(item) for item in stat.instructions],
                }
                for stat in ev.msg.body
            ]

    def _poll_stats(self) -> None:
        while True:
            with self._lock:
                datapaths = list(self._datapaths.values())
            for datapath in datapaths:
                parser = datapath.ofproto_parser
                ofproto = datapath.ofproto
                try:
                    datapath.send_msg(
                        parser.OFPPortStatsRequest(
                            datapath=datapath,
                            flags=0,
                            port_no=ofproto.OFPP_ANY,
                        )
                    )
                    datapath.send_msg(
                        parser.OFPFlowStatsRequest(
                            datapath=datapath,
                            flags=0,
                            table_id=ofproto.OFPTT_ALL,
                            out_port=ofproto.OFPP_ANY,
                            out_group=ofproto.OFPG_ANY,
                            match=parser.OFPMatch(),
                        )
                    )
                except Exception:
                    LOG.exception("Failed requesting stats from dpid=%016x", datapath.id)
            hub.sleep(self._poll_interval)

    def rest_payload(self, path: str) -> Any:
        with self._lock:
            dpids = sorted(self._datapaths)
            if path == "/healthz":
                return {
                    "status": "ok",
                    "controller": "os-ken-lab",
                    "switch_count": len(dpids),
                    "openflow_host": cfg.CONF.ofp_listen_host,
                    "openflow_port": cfg.CONF.ofp_tcp_listen_port,
                    "openflow_version": "OpenFlow13",
                    "rest_host": cfg.CONF.selfhealnet_rest_host,
                    "rest_port": cfg.CONF.selfhealnet_rest_port,
                    "automatic_recovery": dict(self._auto_recovery),
                    "automatic_recovery_profile": (
                        _AUTO_RECOVERY_PROFILE if self._auto_recovery_enabled else None
                    ),
                }
            if path == "/stats/switches":
                return dpids
            if path == "/v1.0/topology/switches":
                return [
                    {"dpid": str(dpid), "ports": self._port_inventory(dpid)}
                    for dpid in dpids
                ]
            if path == "/v1.0/topology/links":
                return []
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[:2] == ["stats", "portdesc"]:
                try:
                    dpid = int(parts[2], 0)
                except ValueError as exc:
                    raise ValueError("switch DPID must be an integer") from exc
                return {str(dpid): list(self._port_descriptions.get(dpid, {}).values())}
            if len(parts) == 3 and parts[0] == "stats" and parts[1] in {"port", "flow"}:
                try:
                    dpid = int(parts[2], 0)
                except ValueError as exc:
                    raise ValueError("switch DPID must be an integer") from exc
                if parts[1] == "port":
                    return {str(dpid): self._port_inventory(dpid)}
                return {str(dpid): list(self._flows.get(dpid, []))}
        return None

    def _port_inventory(self, dpid: int) -> list[dict[str, Any]]:
        stats_by_port = {item["port_no"]: item for item in self._ports.get(dpid, [])}
        descriptions = self._port_descriptions.get(dpid, {})
        port_numbers = sorted(set(descriptions) | set(stats_by_port))
        return [
            {**descriptions.get(port_no, {"port_no": port_no}), **stats_by_port.get(port_no, {})}
            for port_no in port_numbers
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openflow-host", default="127.0.0.1")
    parser.add_argument("--openflow-port", type=int, default=6633)
    parser.add_argument("--rest-host", default="127.0.0.1")
    parser.add_argument("--rest-port", type=int, default=8080)
    parser.add_argument("--enable-lab-auto-recovery", action="store_true")
    args = parser.parse_args()

    cfg.CONF.set_override("ofp_listen_host", args.openflow_host)
    cfg.CONF.set_override("ofp_tcp_listen_port", args.openflow_port)
    cfg.CONF.set_override("selfhealnet_rest_host", args.rest_host)
    cfg.CONF.set_override("selfhealnet_rest_port", args.rest_port)
    cfg.CONF.set_override("selfhealnet_lab_auto_recovery_enabled", args.enable_lab_auto_recovery)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app_manager.AppManager.run_apps([__spec__.name])


cfg.CONF.register_opt(cfg.StrOpt("selfhealnet_rest_host", default="127.0.0.1"))
cfg.CONF.register_opt(cfg.IntOpt("selfhealnet_rest_port", default=8080))
cfg.CONF.register_opt(cfg.BoolOpt("selfhealnet_lab_auto_recovery_enabled", default=False))


if __name__ == "__main__":
    main()