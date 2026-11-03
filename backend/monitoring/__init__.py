# monitoring/__init__.py - Network monitoring module

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import logging
import platform
import re
import socket
import subprocess
import threading
import time

try:
    import psutil
except ImportError:  # pragma: no cover - exercised by dependency checks
    psutil = None
try:
    from ..config import config
    from ..database import SessionLocal, NetworkMetric
except ImportError:
    from config import config
    from database import SessionLocal, NetworkMetric

logger = logging.getLogger(__name__)


class NetworkMonitor:
    """
    Collects and stores real-time network metrics.
    Interfaces with various data sources (SNMP, NetFlow, sFlow, custom probes).
    """
    
    def __init__(self):
        self.db = SessionLocal()
        self.metrics_buffer = []
        self.buffer_size = 100
        self._collector_thread = None
        self._collector_stop = None
        self._previous_io = None
        self._previous_io_at = None

    @staticmethod
    def detect_active_interface() -> Dict[str, Any]:
        """Find the active interface selected by the host's default route."""
        if psutil is None:
            return {"name": None, "ip_address": None, "status": "NOT AVAILABLE"}
        addresses = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        route_ip = None
        route_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            route_socket.connect((config.MONITORING_TARGET or "8.8.8.8", config.MONITORING_TARGET_PORT))
            route_ip = route_socket.getsockname()[0]
        except OSError:
            logger.debug("Unable to determine the default-route interface")
        finally:
            route_socket.close()

        candidates = []
        for name, interface_stats in stats.items():
            if not interface_stats.isup or name.lower().startswith(("lo", "loopback")):
                continue
            ipv4 = next(
                (address.address for address in addresses.get(name, []) if address.family == socket.AF_INET),
                None,
            )
            if not ipv4 or ipv4.startswith("127."):
                continue
            candidates.append((name, ipv4))

        selected = next((item for item in candidates if item[1] == route_ip), None)
        if selected is None:
            virtual_interface = re.compile(
                r"(virtual|vethernet|hyper-v|wsl|vmware|virtualbox|bluetooth|tunnel|bridge|docker|container)",
                re.IGNORECASE,
            )
            selected = next(
                (item for item in candidates if not virtual_interface.search(item[0])),
                candidates[0] if candidates else None,
            )
        if selected:
            name, ipv4 = selected
            interface_type = NetworkMonitor._network_type(name)
            return {
                "name": name,
                "ip_address": ipv4,
                "status": "CONNECTED",
                "network_name": NetworkMonitor._detect_network_name(name, interface_type),
                "network_type": interface_type,
            }
        return {"name": None, "ip_address": None, "status": "NOT CONNECTED"}

    @staticmethod
    def _network_type(interface_name: str) -> str:
        normalized = interface_name.lower()
        if "wi-fi" in normalized or "wifi" in normalized or "wlan" in normalized:
            return "Wi-Fi"
        if "ethernet" in normalized or "lan" in normalized:
            return "Ethernet"
        return "Other"

    @staticmethod
    def _detect_network_name(interface_name: str, interface_type: str) -> str:
        """Read the connected SSID/profile name from the current operating system."""
        if platform.system().lower() != "windows":
            return "Network Name Unavailable"
        if interface_type == "Wi-Fi":
            try:
                output = subprocess.run(
                    ["netsh", "wlan", "show", "interfaces"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=5,
                ).stdout
                interface_blocks = re.split(
                    r"(?=^\s*Name\s*:)",
                    output,
                    flags=re.MULTILINE | re.IGNORECASE,
                )
                for block in interface_blocks:
                    name = re.search(r"^\s*Name\s*:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
                    state = re.search(r"^\s*State\s*:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
                    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
                    if (
                        name
                        and name.group(1).strip().casefold() == interface_name.casefold()
                        and state
                        and state.group(1).strip().lower() == "connected"
                        and ssid
                    ):
                        return ssid.group(1).strip()
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            escaped_name = interface_name.replace("'", "''")
            output = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"(Get-NetConnectionProfile -InterfaceAlias '{escaped_name}' -ErrorAction SilentlyContinue).Name"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=5,
            ).stdout.strip()
            if output:
                return output.splitlines()[0].strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return "Network Name Unavailable"

    @staticmethod
    def _probe_packet_loss_pct(target: str) -> Optional[float]:
        """Measure packet loss to the configured target using the system ping utility."""
        if platform.system().lower() == "windows":
            command = ["ping", "-n", "4", "-w", "1000", target]
        else:
            command = ["ping", "-c", "4", "-W", "1", target]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=6,
            )
        except (OSError, subprocess.SubprocessError):
            logger.warning("Packet-loss probe failed for monitoring target %s", target, exc_info=True)
            return None

        output = f"{result.stdout}\n{result.stderr}"
        loss = re.search(r"\((\d+(?:\.\d+)?)%\s*loss\)", output, re.IGNORECASE)
        if loss is None:
            loss = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", output, re.IGNORECASE)
        if loss is None:
            logger.warning("Packet-loss probe returned no recognizable loss summary for %s", target)
            return None
        return float(loss.group(1))

    def _collect_once(self) -> int:
        """Collect actual OS counters and persist them as metric rows."""
        if psutil is None:
            return 0
        cpu_utilization = psutil.cpu_percent(interval=0.1)
        interface = config.MONITORING_INTERFACE or self.detect_active_interface()["name"]
        cpu_node_id = interface or socket.gethostname()
        self.collect_metric(
            cpu_node_id,
            "cpu_utilization_pct",
            float(cpu_utilization),
            "%",
            interface_id=interface,
        )
        memory_metrics = ()
        try:
            memory = psutil.virtual_memory()
            memory_metrics = (
                ("memory_total_mb", memory.total / 1_000_000, "MB"),
                ("memory_used_mb", memory.used / 1_000_000, "MB"),
                ("memory_available_mb", memory.available / 1_000_000, "MB"),
                ("memory_utilization_pct", memory.percent, "%"),
            )
        except (AttributeError, OSError, NotImplementedError):
            logger.exception("System memory metric collection failed")
        for metric_type, value, unit in memory_metrics:
            self.collect_metric(
                cpu_node_id,
                metric_type,
                float(value),
                unit,
                interface_id=interface,
            )
        counters = psutil.net_io_counters(pernic=True)
        if not interface or interface not in counters:
            self.flush_metrics()
            return len(memory_metrics) + 1
        current = counters[interface]
        now = time.monotonic()
        previous = self._previous_io
        previous_at = self._previous_io_at
        self._previous_io = current
        self._previous_io_at = now
        values = [
            ("bytes_sent", float(current.bytes_sent), "bytes"),
            ("bytes_received", float(current.bytes_recv), "bytes"),
            ("packets_sent", float(current.packets_sent), "packets"),
            ("packets_received", float(current.packets_recv), "packets"),
            ("errors_in", float(current.errin), "packets"),
            ("errors_out", float(current.errout), "packets"),
            ("drops_in", float(current.dropin), "packets"),
            ("drops_out", float(current.dropout), "packets"),
        ]
        if previous is not None and previous_at is not None and now > previous_at:
            elapsed = now - previous_at
            sent_delta = current.bytes_sent - previous.bytes_sent
            received_delta = current.bytes_recv - previous.bytes_recv
            if sent_delta >= 0 and received_delta >= 0:
                total_bytes_per_second = (sent_delta + received_delta) / elapsed
                values.extend([
                    ("throughput_sent_bps", sent_delta / elapsed, "bytes_per_second"),
                    ("throughput_received_bps", received_delta / elapsed, "bytes_per_second"),
                    ("throughput_mbps", total_bytes_per_second * 8 / 1_000_000, "Mbps"),
                ])
                interface_stats = getattr(psutil, "net_if_stats", lambda: {})().get(interface)
                capacity_mbps = getattr(interface_stats, "speed", 0) if interface_stats else 0
                if capacity_mbps and capacity_mbps > 0:
                    utilization_pct = total_bytes_per_second * 8 / (capacity_mbps * 1_000_000) * 100
                    values.append(("bandwidth_utilization_pct", utilization_pct, "%"))
            else:
                logger.warning("Interface counters reset; throughput rates resume after the next sample")
        for metric_type, value, unit in values:
            self.collect_metric(interface, metric_type, value, unit, interface_id=interface)
        if config.MONITORING_TARGET:
            packet_loss = self._probe_packet_loss_pct(config.MONITORING_TARGET)
            if packet_loss is not None:
                self.collect_metric(interface, "packet_loss_pct", packet_loss, "%", interface_id=interface)
        self.flush_metrics()
        self._collect_latency(interface)
        return len(values) + len(memory_metrics) + 1

    def _collect_latency(self, interface: str) -> None:
        target = config.MONITORING_TARGET
        if not target:
            return
        started = time.perf_counter()
        try:
            with socket.create_connection((target, config.MONITORING_TARGET_PORT), timeout=2):
                latency_ms = (time.perf_counter() - started) * 1000
        except OSError:
            return
        self.collect_metric(interface, "latency_ms", latency_ms, "ms", interface_id=interface)
        self.flush_metrics()

    def start_collector(self) -> bool:
        if psutil is None or self._collector_thread is not None:
            return psutil is not None
        self._collector_stop = threading.Event()

        def loop() -> None:
            collector = NetworkMonitor()
            try:
                while not self._collector_stop.is_set():
                    try:
                        collector._collect_once()
                    except Exception:
                        logger.exception("Host network metric collection failed")
                    self._collector_stop.wait(max(1, config.MONITORING_INTERVAL))
            finally:
                collector.close()

        self._collector_thread = threading.Thread(target=loop, name="selfhealnet-network-collector", daemon=True)
        self._collector_thread.start()
        return True

    def stop_collector(self) -> None:
        if self._collector_stop is not None:
            self._collector_stop.set()
        if self._collector_thread is not None:
            self._collector_thread.join(timeout=5)
        self._collector_thread = None
        self._collector_stop = None
        
    def collect_metric(
        self,
        node_id: str,
        metric_type: str,
        value: float,
        unit: str = "ms",
        interface_id: str = None
    ) -> NetworkMetric:
        """
        Collect a single network metric.
        
        Args:
            node_id: Network node identifier
            metric_type: Type of metric (latency, packet_loss, bandwidth, etc.)
            value: Metric value
            unit: Unit of measurement
            interface_id: Optional interface identifier
            
        Returns:
            NetworkMetric object
        """
        metric = NetworkMetric(
            node_id=node_id,
            interface_id=interface_id,
            metric_type=metric_type,
            value=value,
            unit=unit,
            timestamp=datetime.utcnow()
        )
        
        self.metrics_buffer.append(metric)
        
        if len(self.metrics_buffer) >= self.buffer_size:
            self.flush_metrics()
            
        return metric
    
    def flush_metrics(self):
        """Write buffered metrics to database"""
        if not self.metrics_buffer:
            return
            
        try:
            self.db.add_all(self.metrics_buffer)
            self.db.commit()
            logger.info(f"Flushed {len(self.metrics_buffer)} metrics to database")
            self.metrics_buffer.clear()
        except Exception as e:
            logger.error(f"Error flushing metrics: {e}")
            self.db.rollback()
    
    def get_latest_metrics(
        self,
        node_id: str = None,
        metric_type: str = None,
        limit: int = 100,
        fresh_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve latest metrics from database.
        
        Args:
            node_id: Optional filter by node
            metric_type: Optional filter by metric type
            limit: Maximum number of metrics to return
            
        Returns:
            List of metric dictionaries
        """
        query = self.db.query(NetworkMetric)
        
        if node_id:
            query = query.filter(NetworkMetric.node_id == node_id)
        
        if metric_type:
            query = query.filter(NetworkMetric.metric_type == metric_type)

        if fresh_only:
            freshness_seconds = max(60, config.MONITORING_INTERVAL * 3)
            cutoff = datetime.utcnow() - timedelta(seconds=freshness_seconds)
            query = query.filter(NetworkMetric.timestamp >= cutoff)

        metrics = query.order_by(NetworkMetric.timestamp.desc()).limit(limit).all()
        
        return [
            {
                "node_id": m.node_id,
                "metric_type": m.metric_type,
                "value": m.value,
                "unit": m.unit,
                "timestamp": m.timestamp.isoformat(),
                "interface_id": m.interface_id
            }
            for m in metrics
        ]
    
    def get_node_baseline(self, node_id: str) -> Dict[str, float]:
        """
        Calculate baseline metrics for anomaly detection.
        Uses last N metrics to compute mean and std deviation.
        
        Args:
            node_id: Network node identifier
            
        Returns:
            Dictionary with baseline statistics per metric type
        """
        metrics = self.db.query(NetworkMetric).filter(
            NetworkMetric.node_id == node_id
        ).order_by(NetworkMetric.timestamp.desc()).limit(1000).all()
        
        if not metrics:
            return {}
        
        # Group by metric type
        metric_groups = {}
        for m in metrics:
            if m.metric_type not in metric_groups:
                metric_groups[m.metric_type] = []
            metric_groups[m.metric_type].append(m.value)
        
        # Calculate statistics
        baseline = {}
        for metric_type, values in metric_groups.items():
            baseline[metric_type] = {
                "mean": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "count": len(values)
            }
        
        return baseline

    def get_network_identity(self) -> Dict[str, Any]:
        """Return only configured or locally detected monitoring identity."""
        hostname = socket.gethostname() or None
        try:
            local_ip = socket.gethostbyname(hostname) if hostname else None
        except (OSError, socket.gaierror):
            local_ip = None
        try:
            interfaces = [name for _, name in socket.if_nameindex()]
        except (AttributeError, OSError):
            interfaces = []

        controller_configured = config.SDN_CONTROLLER_URL != "http://localhost:8080"
        controller_status = "NOT AVAILABLE"
        detected = self.detect_active_interface()
        interface_name = config.MONITORING_INTERFACE or detected["name"]
        interface_ip = detected["ip_address"]
        connected_network_name = detected.get("network_name", "Network Name Unavailable")
        freshness_seconds = max(60, config.MONITORING_INTERVAL * 3)
        cutoff = datetime.utcnow() - timedelta(seconds=freshness_seconds)

        def latest_metric(metric_type: str) -> Optional[NetworkMetric]:
            if not interface_name:
                return None
            return (
                self.db.query(NetworkMetric)
                .filter(NetworkMetric.node_id == interface_name, NetworkMetric.metric_type == metric_type)
                .filter(NetworkMetric.timestamp >= cutoff)
                .order_by(NetworkMetric.timestamp.desc())
                .first()
            )

        latest = (
            self.db.query(NetworkMetric)
            .filter(NetworkMetric.node_id == interface_name)
            .order_by(NetworkMetric.timestamp.desc())
            .first()
            if interface_name else None
        )
        latency_metric = latest_metric("latency_ms")
        upload_metric = latest_metric("throughput_sent_bps")
        download_metric = latest_metric("throughput_received_bps")
        latency = latency_metric.value if latency_metric else None
        upload_throughput = upload_metric.value if upload_metric else None
        download_throughput = download_metric.value if download_metric else None
        capacity = None
        interface_stats = psutil.net_if_stats().get(interface_name) if psutil and interface_name else None
        if interface_stats:
            speed = interface_stats.speed
            capacity = float(speed) if speed and speed > 0 else None
        source_configured = bool(interface_name)
        latest_is_fresh = bool(latest and latest.timestamp >= cutoff)
        live_status = (
            "CONNECTED" if source_configured and latest_is_fresh
            else "DISCONNECTED" if source_configured
            else "NOT AVAILABLE"
        )
        monitoring_status = (
            "LIVE" if source_configured and latest_is_fresh
            else "DATA UNAVAILABLE" if source_configured
            else "NOT CONNECTED"
        )
        return {
            "monitored_network_name": config.MONITORED_NETWORK_NAME or connected_network_name,
            "connected_network_name": connected_network_name,
            "live_connection": {
                "status": live_status,
                "name": connected_network_name,
                "identifier": interface_name,
            },
            "network_type": detected.get("network_type", "Other") if interface_name else None,
            "monitoring_target": config.MONITORING_TARGET or "Target Unavailable",
            "latency_ms": latency,
            "latency_measured_at": latency_metric.timestamp.isoformat() if latency_metric else None,
            "upload_throughput_bps": upload_throughput,
            "upload_throughput_measured_at": upload_metric.timestamp.isoformat() if upload_metric else None,
            "download_throughput_bps": download_throughput,
            "download_throughput_measured_at": download_metric.timestamp.isoformat() if download_metric else None,
            "link_capacity_mbps": capacity,
            "capacity_status": "AVAILABLE" if capacity is not None else "Capacity Unavailable",
            "connection_details": {
                "interface_id": interface_name,
                "host_identifier": hostname,
                "ip_address": interface_ip or local_ip,
                "available_interfaces": interfaces,
                "sdn_controller": {
                    "status": controller_status,
                    "identifier": config.SDN_CONTROLLER_URL if controller_configured else None,
                },
                "last_data_received": latest.timestamp.isoformat() if latest else None,
            },
            "metric_freshness_seconds": freshness_seconds,
            "monitoring_status": monitoring_status,
            "last_detected_at": datetime.now(timezone.utc).isoformat(),
        }
    
    def close(self):
        """Close database connection"""
        self.stop_collector()
        self.flush_metrics()
        self.db.close()


# Global monitor instance
_monitor = None


def get_monitor() -> NetworkMonitor:
    """Get or create global monitor instance"""
    global _monitor
    if _monitor is None:
        _monitor = NetworkMonitor()
    return _monitor


def initialize_monitoring():
    """Initialize monitoring system"""
    monitor = get_monitor()
    monitor.start_collector()
    logger.info("Network monitoring system initialized")
    return monitor


def shutdown_monitoring():
    """Shutdown monitoring system"""
    global _monitor
    if _monitor:
        _monitor.stop_collector()
        _monitor.flush_metrics()
        _monitor.close()
        _monitor = None
    logger.info("Network monitoring system shutdown")
