"""LabMonitor Docker metrics exporter.

Purpose-built platform fallback (``docker_metrics_exporter_mode: built``).

Reads container state from the read-only Docker socket proxy over plain
HTTP ``GET`` and exposes stable ``labmonitor_docker_container_*`` series
for Prometheus. The exporter never opens a local socket file and never
issues mutating Docker API calls: every request uses ``GET``.
"""

from __future__ import annotations

import http.server
import json
import os
import urllib.request
from typing import TypeGuard

from prometheus_client import CollectorRegistry, Gauge, generate_latest

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

BASE_LABELS = ("container_id", "container_name", "image")

# Stable series contract: name -> (help text, label names). Labels stay
# bounded; arbitrary Docker labels are never copied into Prometheus labels.
SERIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "labmonitor_docker_container_info": (
        "Static container identity and state.",
        BASE_LABELS + ("state",),
    ),
    "labmonitor_docker_container_cpu_usage_seconds_total": (
        "Cumulative CPU time consumed by the container in seconds.",
        BASE_LABELS,
    ),
    "labmonitor_docker_container_memory_usage_bytes": (
        "Current memory usage of the container in bytes.",
        BASE_LABELS,
    ),
    "labmonitor_docker_container_memory_limit_bytes": (
        "Memory limit of the container in bytes.",
        BASE_LABELS,
    ),
    "labmonitor_docker_container_network_receive_bytes_total": (
        "Cumulative network bytes received by the container.",
        BASE_LABELS + ("network",),
    ),
    "labmonitor_docker_container_network_transmit_bytes_total": (
        "Cumulative network bytes transmitted by the container.",
        BASE_LABELS + ("network",),
    ),
    "labmonitor_docker_container_block_read_bytes_total": (
        "Cumulative block I/O bytes read by the container.",
        BASE_LABELS,
    ),
    "labmonitor_docker_container_block_write_bytes_total": (
        "Cumulative block I/O bytes written by the container.",
        BASE_LABELS,
    ),
    "labmonitor_docker_container_restarts_total": (
        "Container restart count reported by the Docker daemon.",
        BASE_LABELS,
    ),
    "labmonitor_docker_container_health_status": (
        "Container health state; exactly one series per container with a "
        "bounded health label (healthy, unhealthy, starting, none).",
        BASE_LABELS + ("health",),
    ),
}

HEALTH_VALUES = ("healthy", "unhealthy", "starting", "none")


class DockerApiClient:
    """Minimal HTTP client for the read-only Docker proxy API (GET only)."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_json(self, path: str) -> object:
        """GET ``path`` against the proxy base URL and decode the JSON body."""
        request = urllib.request.Request(self.base_url + path, method="GET")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _collect_one(
    client: DockerApiClient, entry: dict[str, object]
) -> list[dict[str, object]]:
    container_id = str(entry.get("Id", ""))
    inspect = client.get_json("/containers/%s/json" % container_id)
    stats = client.get_json("/containers/%s/stats?stream=false" % container_id)
    if not isinstance(inspect, dict):
        inspect = {}
    if not isinstance(stats, dict):
        stats = {}

    state = inspect.get("State")
    state_map = state if isinstance(state, dict) else {}
    status = str(state_map.get("Status") or entry.get("State") or "")
    name = str(inspect.get("Name") or "")
    if not name:
        names = entry.get("Names")
        if isinstance(names, list) and names:
            name = str(names[0])
    name = name.lstrip("/")
    config = inspect.get("Config")
    config_map = config if isinstance(config, dict) else {}
    image = str(config_map.get("Image") or entry.get("Image") or "")

    base = {"container_id": container_id, "container_name": name, "image": image}
    metrics: list[dict[str, object]] = [
        {
            "name": "labmonitor_docker_container_info",
            "labels": dict(base, state=status),
            "value": 1.0,
        }
    ]

    cpu_stats = stats.get("cpu_stats")
    cpu_map = cpu_stats if isinstance(cpu_stats, dict) else {}
    cpu_usage = cpu_map.get("cpu_usage")
    usage_map = cpu_usage if isinstance(cpu_usage, dict) else {}
    total_usage = usage_map.get("total_usage")
    if _is_number(total_usage):
        metrics.append(
            {
                "name": "labmonitor_docker_container_cpu_usage_seconds_total",
                "labels": dict(base),
                "value": float(total_usage) / 1e9,
            }
        )

    memory_stats = stats.get("memory_stats")
    memory_map = memory_stats if isinstance(memory_stats, dict) else {}
    mem_usage = memory_map.get("usage")
    if _is_number(mem_usage):
        metrics.append(
            {
                "name": "labmonitor_docker_container_memory_usage_bytes",
                "labels": dict(base),
                "value": float(mem_usage),
            }
        )
    mem_limit = memory_map.get("limit")
    if _is_number(mem_limit):
        metrics.append(
            {
                "name": "labmonitor_docker_container_memory_limit_bytes",
                "labels": dict(base),
                "value": float(mem_limit),
            }
        )

    networks = stats.get("networks")
    networks_map = networks if isinstance(networks, dict) else {}
    for network_name, counters in networks_map.items():
        counters_map = counters if isinstance(counters, dict) else {}
        received = counters_map.get("rx_bytes")
        if _is_number(received):
            metrics.append(
                {
                    "name": "labmonitor_docker_container_network_receive_bytes_total",
                    "labels": dict(base, network=str(network_name)),
                    "value": float(received),
                }
            )
        transmitted = counters_map.get("tx_bytes")
        if _is_number(transmitted):
            metrics.append(
                {
                    "name": "labmonitor_docker_container_network_transmit_bytes_total",
                    "labels": dict(base, network=str(network_name)),
                    "value": float(transmitted),
                }
            )

    blkio_stats = stats.get("blkio_stats")
    blkio_map = blkio_stats if isinstance(blkio_stats, dict) else {}
    io_entries = blkio_map.get("io_service_bytes_recursive")
    read_total = 0.0
    write_total = 0.0
    saw_read = False
    saw_write = False
    if isinstance(io_entries, list):
        for item in io_entries:
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if not _is_number(value):
                continue
            if item.get("op") == "Read":
                read_total += float(value)
                saw_read = True
            elif item.get("op") == "Write":
                write_total += float(value)
                saw_write = True
    if saw_read:
        metrics.append(
            {
                "name": "labmonitor_docker_container_block_read_bytes_total",
                "labels": dict(base),
                "value": read_total,
            }
        )
    if saw_write:
        metrics.append(
            {
                "name": "labmonitor_docker_container_block_write_bytes_total",
                "labels": dict(base),
                "value": write_total,
            }
        )

    restarts = inspect.get("RestartCount", 0)
    metrics.append(
        {
            "name": "labmonitor_docker_container_restarts_total",
            "labels": dict(base),
            "value": float(restarts) if _is_number(restarts) else 0.0,
        }
    )

    health = state_map.get("Health")
    health_map = health if isinstance(health, dict) else {}
    health_value = str(health_map.get("Status") or "none")
    if health_value not in HEALTH_VALUES:
        health_value = "none"
    metrics.append(
        {
            "name": "labmonitor_docker_container_health_status",
            "labels": dict(base, health=health_value),
            "value": 1.0,
        }
    )
    return metrics


def collect_container_metrics(client: DockerApiClient) -> list[dict[str, object]]:
    """Collect the stable metric dicts for every visible container.

    Requests ``GET /version``, ``GET /containers/json?all=1`` and then
    ``GET /containers/{id}/json`` plus
    ``GET /containers/{id}/stats?stream=false`` per container. A failing
    container is skipped so one bad response never breaks the scrape.
    """
    client.get_json("/version")
    containers = client.get_json("/containers/json?all=1")
    if not isinstance(containers, list):
        return []
    collected: list[dict[str, object]] = []
    for entry in containers:
        if not isinstance(entry, dict):
            continue
        try:
            collected.extend(_collect_one(client, entry))
        except Exception:
            continue
    return collected


def render_prometheus(metrics: list[dict[str, object]]) -> bytes:
    """Render collected metric dicts in Prometheus exposition format."""
    registry = CollectorRegistry()
    gauges: dict[str, Gauge] = {}
    for metric in metrics:
        name = str(metric.get("name", ""))
        spec = SERIES.get(name)
        if spec is None:
            continue
        _, label_names = spec
        gauge = gauges.get(name)
        if gauge is None:
            gauge = Gauge(name, spec[0], label_names, registry=registry)
            gauges[name] = gauge
        raw_labels = metric.get("labels")
        label_map = raw_labels if isinstance(raw_labels, dict) else {}
        labels = {key: str(label_map.get(key, "")) for key in label_names}
        value = metric.get("value", 0.0)
        gauge.labels(**labels).set(float(value) if _is_number(value) else 0.0)
    return generate_latest(registry)


def create_handler(client: DockerApiClient) -> type[http.server.BaseHTTPRequestHandler]:
    """Build an HTTP handler serving ``/metrics`` and ``/healthz``."""

    class ExporterHandler(http.server.BaseHTTPRequestHandler):
        server_version = "LabMonitorDockerExporter/1.0"

        def do_GET(self) -> None:
            if self.path == "/healthz":
                # Liveness only: never touches the Docker API, so this
                # endpoint cannot issue any Docker request at all.
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/metrics":
                try:
                    payload = render_prometheus(collect_container_metrics(client))
                except Exception as exc:
                    body = ("collection failed: %s" % exc).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", CONTENT_TYPE)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
            else:
                self.send_error(404)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    return ExporterHandler


def main() -> None:
    """Serve the exporter on ``METRICS_PORT`` (default 9797)."""
    base_url = os.environ.get("DOCKER_API_URL", "http://127.0.0.1:12375")
    port = int(os.environ.get("METRICS_PORT", "9797"))
    client = DockerApiClient(base_url)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), create_handler(client))
    server.serve_forever()


if __name__ == "__main__":
    main()
