"""Stateful SDN controller adapter used by the recovery orchestrator."""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, Iterable, Optional


class SDNController:
    """Apply recovery changes to controller-managed network state.

    The default transport is an in-process controller state for the simulated
    network. A deployment can provide a transport callable to forward the same
    operations to a real OpenFlow/REST controller.
    """

    def __init__(
        self,
        controller_url: str = "http://localhost:8080",
        links: Optional[Iterable[tuple[str, str]]] = None,
        routes: Optional[Dict[str, list[str]]] = None,
        services: Optional[Iterable[str]] = None,
        transport=None,
    ):
        self.controller_url = controller_url
        self.transport = transport
        self.links: Dict[tuple[str, str], bool] = {
            self._link_key(*link): True for link in (links or [])
        }
        self.routes = dict(routes or {})
        self.flows: Dict[str, Dict[str, Any]] = {}
        self.services = {service: "running" for service in (services or [])}
        self.qos_policies: Dict[str, Dict[str, Any]] = {}
        self.link_weights: Dict[tuple[str, str], float] = {key: 1.0 for key in self.links}
        self.action_log: list[Dict[str, Any]] = []

    def connect(self) -> dict:
        if not self.has_real_connection():
            return {
                "status": "unavailable",
                "controller_url": self.controller_url,
                "reason": "No verified SDN controller transport is configured",
            }
        return {"status": "connected", "controller_url": self.controller_url}

    def has_real_connection(self) -> bool:
        """Require an injected transport to verify its controller connection."""
        if not callable(self.transport):
            return False
        connector = getattr(self.transport, "connect", None)
        if not callable(connector):
            return False
        result = connector()
        return isinstance(result, dict) and result.get("status") == "connected"

    @staticmethod
    def _link_key(source: str, target: str) -> tuple[str, str]:
        return (source, target) if source <= target else (target, source)

    def execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch one recovery action and return the changed controller state."""
        action_type = action.get("type")
        if self.transport is not None:
            result = self.transport(action)
        elif action_type == "disable_link":
            result = self.disable_link(action.get("target"), action.get("source"))
        elif action_type == "enable_backup_link":
            result = self.enable_link(action.get("target"), action.get("source"))
        elif action_type in {"update_routing", "trigger_spf_recalculation"}:
            result = self.update_routing(action)
        elif action_type == "adjust_weights":
            result = self.adjust_weights(action)
        elif action_type in {"apply_qos", "enable_traffic_shaping"}:
            result = self.apply_qos(action)
        elif action_type == "restart_service":
            result = self.restart_service(action.get("target"))
        elif action_type == "rate_limit":
            result = self.apply_qos(action)
        elif action_type in {"verify_bgp_neighbors", "increase_monitoring", "increase_metric_frequency", "alert_ops", "page_on_call_engineer"}:
            result = {"status": "recorded", "action": action_type}
        else:
            raise ValueError(f"Unsupported SDN action: {action_type}")
        self.action_log.append({"action": action, "result": result})
        return result

    def disable_link(self, target: str, source: Optional[str] = None) -> Dict[str, Any]:
        key = self._resolve_link(target, source)
        self.links[key] = False
        removed_routes = self._remove_unavailable_routes()
        return {"status": "applied", "action": "disable_link", "link": list(key), "removed_routes": removed_routes}

    def enable_link(self, target: str, source: Optional[str] = None) -> Dict[str, Any]:
        key = self._resolve_link(target, source)
        self.links[key] = True
        return {"status": "applied", "action": "enable_link", "link": list(key)}

    def update_routing(self, action: Dict[str, Any]) -> Dict[str, Any]:
        flow_id = action.get("flow_id", "default")
        path = action.get("path") or action.get("new_path")
        if path is None and action.get("source") and action.get("target"):
            path = self.compute_path(action["source"], action["target"])
        if not path or not self._path_is_active(path):
            raise ValueError("No active path is available for routing update")
        self.routes[flow_id] = list(path)
        self.flows[flow_id] = {"path": list(path), "status": "active"}
        return {"status": "applied", "action": "update_routing", "flow_id": flow_id, "path": list(path)}

    def reroute_traffic(self, flow_id: str, path: list[str]) -> Dict[str, Any]:
        return self.update_routing({"flow_id": flow_id, "path": path})

    def adjust_weights(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Change link cost or reroute a selected flow through the controller."""
        if action.get("path"):
            return self.update_routing(action)
        key = self._resolve_link(action.get("target"), action.get("source"))
        weight = float(action.get("weight", action.get("new_weight", 1.0)))
        if weight <= 0:
            raise ValueError("Link weight must be greater than zero")
        self.link_weights[key] = weight
        return {"status": "applied", "action": "adjust_weights", "link": list(key), "weight": weight}

    def apply_qos(self, action: Dict[str, Any]) -> Dict[str, Any]:
        target = action.get("target", "default")
        policy = {key: value for key, value in action.items() if key != "type"}
        self.qos_policies[target] = policy
        return {"status": "applied", "action": "apply_qos", "target": target, "policy": policy}

    def restart_service(self, service: str) -> Dict[str, Any]:
        if service not in self.services:
            raise ValueError(f"Service '{service}' is not managed by this controller")
        self.services[service] = "running"
        return {"status": "restarted", "service": service}

    def compute_path(self, source: str, target: str) -> list[str]:
        graph: Dict[str, list[str]] = {}
        for (left, right), active in self.links.items():
            if active:
                graph.setdefault(left, []).append(right)
                graph.setdefault(right, []).append(left)
        queue = deque([(source, [source])])
        visited = {source}
        while queue:
            node, path = queue.popleft()
            if node == target:
                return path
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        return []

    def _resolve_link(self, target: str, source: Optional[str]) -> tuple[str, str]:
        if source:
            return self._link_key(source, target)
        matches = [link for link in self.links if target in link]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(f"Link '{target}' is not known to the controller")
        raise ValueError(f"Link '{target}' is ambiguous; provide source")

    def _path_is_active(self, path: list[str]) -> bool:
        return all(self.links.get(self._link_key(left, right), False) for left, right in zip(path, path[1:]))

    def _remove_unavailable_routes(self) -> list[str]:
        removed = []
        for flow_id, path in list(self.routes.items()):
            if not self._path_is_active(path):
                removed.append(flow_id)
                self.routes.pop(flow_id)
                self.flows.get(flow_id, {}).update(status="reroute_required")
        return removed
