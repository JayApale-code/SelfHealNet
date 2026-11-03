INSERT INTO network_metrics (device_name, metric_name, metric_value) VALUES
('core-router-1', 'latency_ms', 32.5),
('core-router-1', 'packet_loss_pct', 0.04),
('edge-switch-2', 'latency_ms', 38.2);

INSERT INTO incidents (incident_type, severity, status) VALUES
('link_congestion', 'medium', 'open'),
('packet_loss', 'high', 'investigating');
