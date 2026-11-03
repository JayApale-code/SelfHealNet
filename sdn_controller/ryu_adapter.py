"""Read-only adapter for Ryu's REST API (not its OpenFlow TCP listener)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import threading
import time
from typing import Any, Optional

import requests


class RyuControllerAdapter:
    """Read switch, port, flow, and topology state from Ryu REST endpoints."""

    write_operations_enabled = False

    def __init__(
        self,
        controller_url: Optional[str],
        timeout_seconds: float = 2.0,
        retry_interval_seconds: float = 2.0,
        username: Optional[str] = None,
        password: Optional[str] = None,
        session: Any = None,
        controller_type: str = "ryu",
    ) -> None:
        self.controller_url = controller_url.rstrip("/") if controller_url else None
        self.timeout_seconds = timeout_seconds
        self.retry_interval_seconds = max(0.1, retry_interval_seconds)
        self.controller_type = controller_type.strip().lower() or "ryu"
        self.controller_name = "OS-Ken lab" if self.controller_type == "os_ken_lab" else "Ryu"
        self.source_name = "os_ken_lab_rest_api" if self.controller_type == "os_ken_lab" else "ryu_rest_api"
        self.credentials_incomplete = bool(username) != bool(password)
        self.auth = (username, password) if username and password else None
        self._session = session or requests.Session()
        self._snapshot_lock = threading.Lock()
        self._cached_snapshot: Optional[dict[str, Any]] = None
        self._cached_at = 0.0
        self._last_connected_at: Optional[str] = None
        self._last_switch_ids: list[str] = []
        self._last_port_counters: dict[tuple[str, str], tuple[int, int]] = {}

    def has_real_connection(self) -> bool:
        return self.snapshot()["status"] == "CONNECTED"

    def snapshot(self) -> dict[str, Any]:
        with self._snapshot_lock:
            now = time.monotonic()
            if self._cached_snapshot is not None and now - self._cached_at < self.retry_interval_seconds:
                return copy.deepcopy(self._cached_snapshot)
            result = self._fetch_snapshot()
            self._cached_snapshot = copy.deepcopy(result)
            self._cached_at = time.monotonic()
            return result

    def _fetch_snapshot(self) -> dict[str, Any]:
        checked_at = datetime.now(timezone.utc).isoformat()
        response: dict[str, Any] = {
            "status": "NOT_CONFIGURED" if not self.controller_url else "DISCONNECTED",
            "source": "none",
            "configured": bool(self.controller_url),
            "controller_url": self.controller_url,
            "mode": "read-only",
            "write_operations_enabled": False,
            "automatic_recovery_enabled": False,
            "automatic_recovery": None,
            "timestamp": checked_at,
            "last_check_at": checked_at,
            "last_connected_at": self._last_connected_at,
            "retry_interval_seconds": self.retry_interval_seconds,
            "connection_state": "NOT_CONFIGURED" if not self.controller_url else "DISCONNECTED",
            "reconnection_pending": False,
            "environment_ready": False,
            "message": None,
            "last_known_switch_ids": list(self._last_switch_ids),
            "error": None,
            "partial_errors": [],
            "topology": {"nodes": [], "links": []},
            "switches": [],
            "flow_count": None,
        }
        if not self.controller_url:
            response["error"] = f"Set SDN_CONTROLLER_URL to the {self.controller_name} REST API base URL."
            response["message"] = "Controller Disconnected"
            return response
        if self.credentials_incomplete:
            response["error"] = "Set both SDN_CONTROLLER_USERNAME and SDN_CONTROLLER_PASSWORD, or neither."
            response["message"] = "Controller Disconnected"
            return response

        try:
            switch_ids = self._get_switch_ids()
        except (requests.RequestException, ValueError, TypeError) as exc:
            response["error"] = self._error_message(exc)
            response["connection_state"] = "RECONNECTING" if self._last_connected_at else "DISCONNECTED"
            response["reconnection_pending"] = bool(self._last_connected_at)
            response["message"] = (
                "Controller Connection Lost - Reconnecting"
                if self._last_connected_at else "Controller Disconnected"
            )
            return response

        response["status"] = "CONNECTED"
        response["source"] = self.source_name
        self._last_connected_at = checked_at
        response["last_connected_at"] = checked_at
        response["error"] = None
        if self.controller_type == "os_ken_lab":
            try:
                health = self._get_json("/healthz")
                if not isinstance(health, dict) or health.get("controller") != "os-ken-lab":
                    raise ValueError("OS-Ken lab /healthz returned an unexpected response.")
                automatic_recovery = health.get("automatic_recovery")
                if isinstance(automatic_recovery, dict):
                    response["automatic_recovery"] = automatic_recovery
                    response["automatic_recovery_enabled"] = bool(automatic_recovery.get("enabled"))
                    if response["automatic_recovery_enabled"]:
                        response["mode"] = "read-only+mininet-lab-auto-recovery"
            except (requests.RequestException, ValueError, TypeError) as exc:
                response["partial_errors"].append({
                    "endpoint": "/healthz",
                    "error": self._error_message(exc),
                })
        switch_ids = list(dict.fromkeys(switch_ids))
        response["switches"] = []
        for switch_id in switch_ids:
            switch = {"dpid": switch_id, "ports": [], "flows": None, "flow_count": None}
            try:
                port_stats = self._read_switch_stats(f"/stats/port/{switch_id}")
            except (requests.RequestException, ValueError, TypeError) as exc:
                port_stats = []
                response["partial_errors"].append({
                    "endpoint": f"/stats/port/{switch_id}",
                    "error": self._error_message(exc),
                })
            try:
                port_descriptions = self._read_switch_stats(f"/stats/portdesc/{switch_id}")
            except (requests.RequestException, ValueError, TypeError) as exc:
                port_descriptions = []
                response["partial_errors"].append({
                    "endpoint": f"/stats/portdesc/{switch_id}",
                    "error": self._error_message(exc),
                })
            switch["ports"] = self._merge_ports(switch_id, port_stats, port_descriptions)
            response["switches"].append(switch)
        switch_by_id = {switch["dpid"]: switch for switch in response["switches"]}

        for switch_id, switch in switch_by_id.items():
            try:
                flows = self._read_switch_stats(f"/stats/flow/{switch_id}")
                switch["flows"] = flows
                switch["flow_count"] = len(flows)
            except (requests.RequestException, ValueError, TypeError) as exc:
                response["partial_errors"].append({
                    "endpoint": f"/stats/flow/{switch_id}",
                    "error": self._error_message(exc),
                })

        known_flow_counts = [
            switch["flow_count"]
            for switch in response["switches"]
            if switch["flow_count"] is not None
        ]
        if known_flow_counts and len(known_flow_counts) == len(response["switches"]):
            response["flow_count"] = sum(known_flow_counts)

        self._read_topology(response)
        if not response["topology"]["nodes"]:
            response["topology"]["nodes"] = [
                {"id": switch_id, "type": "switch", "ports": switch_by_id[switch_id]["ports"]}
                for switch_id in switch_ids
            ]
        if not switch_ids:
            disconnected_switches = bool(self._last_switch_ids)
            response["connection_state"] = "SWITCH_RECONNECTING" if disconnected_switches else "WAITING_FOR_SWITCHES"
            response["reconnection_pending"] = disconnected_switches
            response["message"] = (
                "Switch Connection Lost - Reconnecting"
                if disconnected_switches else "Controller Connected - Waiting for Switches"
            )
            response["error"] = f"{self.controller_name} REST API responded, but no OpenFlow switches are connected."
        else:
            response["connection_state"] = "SWITCHES_CONNECTED"
            response["environment_ready"] = bool(response["switches"]) and all(
                switch["ports"] and all(port["available"] for port in switch["ports"])
                for switch in response["switches"]
            )
            response["message"] = (
                f"Controller Connected - {len(switch_ids)} Switch(es), "
                f"{sum(len(switch['ports']) for switch in response['switches'])} Port(s) Discovered"
                if response["environment_ready"] else
                "Switches Connected - Port Inventory Incomplete"
            )
            self._last_switch_ids = switch_ids
        response["disconnected_switch_ids"] = sorted(set(self._last_switch_ids) - set(switch_ids))
        response["last_known_switch_ids"] = list(self._last_switch_ids)
        active_port_keys = {
            (switch["dpid"], str(port["port_no"]))
            for switch in response["switches"]
            for port in switch["ports"]
            if "port_no" in port
        }
        self._last_port_counters = {
            key: value for key, value in self._last_port_counters.items()
            if key in active_port_keys
        }
        return response

    def _merge_ports(
        self,
        switch_id: str,
        port_stats: list[dict[str, Any]],
        descriptions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        stats_by_port = {str(item["port_no"]): item for item in port_stats if "port_no" in item}
        descriptions_by_port = {str(item["port_no"]): item for item in descriptions if "port_no" in item}
        port_ids = sorted(set(stats_by_port) | set(descriptions_by_port), key=lambda value: int(value))
        ports = []
        for port_id in port_ids:
            description = descriptions_by_port.get(port_id, {})
            stats = stats_by_port.get(port_id, {})
            port = {**description, **stats}
            port["available"] = bool(description)
            config_flags = self._flag_value(description.get("config", stats.get("config")))
            state_flags = self._flag_value(description.get("state", stats.get("state")))
            port["admin_state"] = (
                "DISABLED" if config_flags is not None and config_flags & 1
                else "ENABLED" if config_flags is not None
                else "UNKNOWN"
            )
            port["link_state"] = (
                "DOWN" if state_flags is not None and state_flags & 1
                else "UP" if state_flags is not None and state_flags & 4
                else "UNKNOWN"
            )
            port["operational_state"] = (
                "ADMIN_DOWN" if port["admin_state"] == "DISABLED"
                else "DOWN" if port["link_state"] == "DOWN"
                else "BLOCKED" if state_flags is not None and state_flags & 2
                else "UP" if port["link_state"] == "UP"
                else "UNKNOWN"
            )
            port["forwarding_state"] = (
                "BLOCKED" if state_flags is not None and state_flags & 2
                else "NOT_BLOCKED" if state_flags is not None
                else "UNKNOWN"
            )
            port["traffic_state"] = self._traffic_state(switch_id, port_id, stats)
            ports.append(port)
        return ports

    @staticmethod
    def _flag_value(value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value, 0)
            except ValueError:
                return None
        return None

    def _traffic_state(self, switch_id: str, port_id: str, stats: dict[str, Any]) -> str:
        counters = (stats.get("rx_packets"), stats.get("tx_packets"))
        if any(not isinstance(value, (int, float)) for value in counters):
            return "UNKNOWN"
        key = (switch_id, port_id)
        current = (int(counters[0]), int(counters[1]))
        previous = self._last_port_counters.get(key)
        self._last_port_counters[key] = current
        if previous is None:
            return "UNKNOWN"
        return "TRAFFIC_OBSERVED" if current[0] > previous[0] or current[1] > previous[1] else "NO_RECENT_TRAFFIC"

    def _get_switch_ids(self) -> list[str]:
        payload = self._get_json("/stats/switches")
        if not isinstance(payload, list):
            raise ValueError(f"{self.controller_name} /stats/switches returned an unexpected response shape.")
        switch_ids = []
        for switch_id in payload:
            if isinstance(switch_id, (str, int)) and not isinstance(switch_id, bool):
                switch_ids.append(str(switch_id))
            else:
                raise ValueError(f"{self.controller_name} /stats/switches returned an invalid switch identifier.")
        return switch_ids

    def _read_switch_stats(self, path: str) -> list[dict[str, Any]]:
        payload = self._get_json(path)
        if not isinstance(payload, dict) or len(payload) != 1:
            raise ValueError(f"{self.controller_name} {path} returned an unexpected response shape.")
        stats = next(iter(payload.values()))
        if not isinstance(stats, list) or any(not isinstance(item, dict) for item in stats):
            raise ValueError(f"{self.controller_name} {path} returned malformed statistics.")
        return stats

    def _read_topology(self, response: dict[str, Any]) -> None:
        for endpoint, key in (
            ("/v1.0/topology/switches", "nodes"),
            ("/v1.0/topology/links", "links"),
        ):
            try:
                payload = self._get_json(endpoint)
                if not isinstance(payload, list):
                        raise ValueError(f"{self.controller_name} {endpoint} returned an unexpected response shape.")
                if any(not isinstance(item, dict) for item in payload):
                    raise ValueError(f"{self.controller_name} {endpoint} returned malformed topology data.")
                if key == "nodes":
                    response["topology"]["nodes"] = [
                        {
                            "id": str(item["dpid"]),
                            "type": "switch",
                            "ports": item.get("ports", []),
                        }
                        for item in payload
                        if "dpid" in item
                    ]
                    if len(response["topology"]["nodes"]) != len(payload):
                        raise ValueError(f"{self.controller_name} {endpoint} omitted a switch identifier.")
                else:
                    response["topology"]["links"] = [
                        {
                            "source": str(item["src"]["dpid"]),
                            "source_port": item["src"]["port_no"],
                            "target": str(item["dst"]["dpid"]),
                            "target_port": item["dst"]["port_no"],
                        }
                        for item in payload
                        if isinstance(item.get("src"), dict)
                        and isinstance(item.get("dst"), dict)
                        and "dpid" in item["src"]
                        and "dpid" in item["dst"]
                        and "port_no" in item["src"]
                        and "port_no" in item["dst"]
                    ]
                    if len(response["topology"]["links"]) != len(payload):
                        raise ValueError(f"{self.controller_name} {endpoint} returned malformed links.")
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                response["partial_errors"].append({
                    "endpoint": endpoint,
                    "error": self._error_message(exc),
                })

    def _get_json(self, path: str) -> Any:
        result = self._session.get(
            f"{self.controller_url}{path}",
            auth=self.auth,
            timeout=self.timeout_seconds,
        )
        try:
            result.raise_for_status()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                raise ValueError(
                    f"{self.controller_name} REST endpoint {path} is unavailable (HTTP 404); "
                    f"verify that the corresponding {self.controller_name} REST application is running."
                ) from exc
            raise
        try:
            return result.json()
        except ValueError as exc:
            raise ValueError(f"{self.controller_name} {path} returned invalid JSON.") from exc

    def _error_message(self, exc: Exception) -> str:
        if isinstance(exc, requests.Timeout):
            return f"Timed out contacting the {self.controller_name} REST API."
        if isinstance(exc, requests.HTTPError):
            status = exc.response.status_code if exc.response is not None else "unknown"
            return f"{self.controller_name} REST API returned HTTP {status}."
        if isinstance(exc, requests.RequestException):
            return f"Could not connect to the {self.controller_name} REST API."
        return str(exc)

    def execute_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Reject switch writes: this integration intentionally remains read-only."""
        return {
            "status": "blocked",
            "action": action.get("type"),
            "reason": "Controller adapter is read-only; switch flow changes are not enabled.",
        }
