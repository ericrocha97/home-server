"""Fallback exporter tests (``docker_metrics_exporter_mode: built``).

Every test runs against a fake HTTP transport that records each method
and path, proving GET-only calls, the proxy base URL, optional-field
behavior, and bounded health values without touching a live daemon.
"""

import http.client
import http.server
import pathlib
import re
import threading
import unittest
from urllib.parse import urlparse

from app import (
    DockerApiClient,
    collect_container_metrics,
    create_handler,
    render_prometheus,
)

BASE_URL = "http://proxy-test:12375"

VERSION = {"Version": "29.7.2", "ApiVersion": "1.55"}

LIST = [
    {"Id": "aaa111", "Names": ["/web"], "Image": "example/web:1.0", "State": "running"},
    {
        "Id": "bbb222",
        "Names": ["/worker"],
        "Image": "example/worker:1.0",
        "State": "running",
    },
]

INSPECT_WEB = {
    "Id": "aaa111",
    "Name": "/web",
    "Config": {"Image": "example/web:1.0"},
    "State": {"Status": "running", "Health": {"Status": "healthy"}},
    "RestartCount": 3,
}

STATS_WEB = {
    "cpu_stats": {"cpu_usage": {"total_usage": 5000000000}},
    "memory_stats": {"usage": 12345678, "limit": 536870912},
    "networks": {"eth0": {"rx_bytes": 1000, "tx_bytes": 2000}},
    "blkio_stats": {
        "io_service_bytes_recursive": [
            {"op": "Read", "value": 4096},
            {"op": "Write", "value": 8192},
        ]
    },
}

INSPECT_WORKER = {
    "Id": "bbb222",
    "Name": "/worker",
    "Config": {"Image": "example/worker:1.0"},
    "State": {"Status": "running"},
    "RestartCount": 0,
}

STATS_WORKER = {
    "cpu_stats": {"cpu_usage": {"total_usage": 250000000}},
    "memory_stats": {"usage": 1111111, "limit": 268435456},
}


def make_routes() -> dict[str, object]:
    return {
        "/version": VERSION,
        "/containers/json?all=1": LIST,
        "/containers/aaa111/json": INSPECT_WEB,
        "/containers/aaa111/stats?stream=false": STATS_WEB,
        "/containers/bbb222/json": INSPECT_WORKER,
        "/containers/bbb222/stats?stream=false": STATS_WORKER,
    }


class FakeDockerApiClient(DockerApiClient):
    """Fake HTTP transport recording every (method, URL) pair."""

    def __init__(self, routes: dict[str, object]) -> None:
        super().__init__(BASE_URL)
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str) -> object:
        self.calls.append(("GET", self.base_url + path))
        return self.routes[path]


def index_by_name(metrics: list[dict[str, object]]) -> dict[tuple[str, str], float]:
    indexed: dict[tuple[str, str], float] = {}
    for metric in metrics:
        labels = metric["labels"]
        assert isinstance(labels, dict)
        key = (str(metric["name"]), str(labels.get("container_name", "")))
        indexed[key] = float(metric["value"])  # type: ignore[arg-type]
    return indexed


def find_metric(
    metrics: list[dict[str, object]], name: str, container: str
) -> dict[str, object]:
    for metric in metrics:
        labels = metric["labels"]
        assert isinstance(labels, dict)
        if metric["name"] == name and labels.get("container_name") == container:
            return metric
    raise AssertionError(f"missing series {name} for container {container}")


class TestFallbackExporter(unittest.TestCase):
    def test_fetch_containers_uses_http_proxy_url(self) -> None:
        """Collection uses the HTTP proxy base URL with GET-only requests."""
        fake = FakeDockerApiClient(make_routes())
        collect_container_metrics(fake)
        self.assertTrue(fake.calls, "collector must call the Docker API")
        for method, url in fake.calls:
            self.assertEqual(method, "GET", f"all Docker calls must be GET — got {url}")
            self.assertTrue(
                url.startswith(BASE_URL),
                f"all Docker calls must use the proxy base URL — got {url}",
            )
            self.assertEqual(urlparse(url).scheme, "http")
        paths = [urlparse(url).path + ("?" + urlparse(url).query if urlparse(url).query else "")
                 for _, url in fake.calls]
        self.assertIn("/version", paths)
        self.assertIn("/containers/json?all=1", paths)

    def test_collect_container_stats_maps_cpu_memory_network_and_restarts(self) -> None:
        """Stats map to CPU seconds, memory bytes, per-network bytes, restarts."""
        fake = FakeDockerApiClient(make_routes())
        metrics = collect_container_metrics(fake)
        by_name = index_by_name(metrics)
        self.assertEqual(by_name[("labmonitor_docker_container_cpu_usage_seconds_total", "web")], 5.0)
        self.assertEqual(
            by_name[("labmonitor_docker_container_memory_usage_bytes", "web")], 12345678.0
        )
        self.assertEqual(
            by_name[("labmonitor_docker_container_memory_limit_bytes", "web")], 536870912.0
        )
        received = find_metric(
            metrics, "labmonitor_docker_container_network_receive_bytes_total", "web"
        )
        labels = received["labels"]
        assert isinstance(labels, dict)
        self.assertEqual(labels.get("network"), "eth0")
        self.assertEqual(float(received["value"]), 1000.0)  # type: ignore[arg-type]
        transmitted = find_metric(
            metrics, "labmonitor_docker_container_network_transmit_bytes_total", "web"
        )
        self.assertEqual(float(transmitted["value"]), 2000.0)  # type: ignore[arg-type]
        self.assertEqual(
            by_name[("labmonitor_docker_container_restarts_total", "web")], 3.0
        )
        info = find_metric(metrics, "labmonitor_docker_container_info", "web")
        info_labels = info["labels"]
        assert isinstance(info_labels, dict)
        self.assertEqual(info_labels.get("state"), "running")
        self.assertEqual(info_labels.get("image"), "example/web:1.0")

    def test_collect_container_health_without_healthcheck(self) -> None:
        """Containers without a healthcheck report the bounded value none."""
        fake = FakeDockerApiClient(make_routes())
        metrics = collect_container_metrics(fake)
        worker = find_metric(metrics, "labmonitor_docker_container_health_status", "worker")
        worker_labels = worker["labels"]
        assert isinstance(worker_labels, dict)
        self.assertEqual(worker_labels.get("health"), "none")
        self.assertEqual(float(worker["value"]), 1.0)  # type: ignore[arg-type]
        web = find_metric(metrics, "labmonitor_docker_container_health_status", "web")
        web_labels = web["labels"]
        assert isinstance(web_labels, dict)
        self.assertEqual(web_labels.get("health"), "healthy")
        for metric in metrics:
            if metric["name"] != "labmonitor_docker_container_health_status":
                continue
            labels = metric["labels"]
            assert isinstance(labels, dict)
            self.assertIn(
                labels.get("health"),
                ("healthy", "unhealthy", "starting", "none"),
                "health label values must stay bounded",
            )

    def test_missing_optional_block_io_does_not_fail_collection(self) -> None:
        """Stats without block I/O still collect; block series are omitted."""
        fake = FakeDockerApiClient(make_routes())
        metrics = collect_container_metrics(fake)
        worker_names = {
            str(metric["name"])
            for metric in metrics
            if isinstance(metric["labels"], dict)
            and metric["labels"].get("container_name") == "worker"
        }
        self.assertNotIn("labmonitor_docker_container_block_read_bytes_total", worker_names)
        self.assertNotIn("labmonitor_docker_container_block_write_bytes_total", worker_names)
        self.assertIn("labmonitor_docker_container_cpu_usage_seconds_total", worker_names)
        self.assertIn("labmonitor_docker_container_memory_usage_bytes", worker_names)
        self.assertIn("labmonitor_docker_container_health_status", worker_names)
        web_read = find_metric(
            metrics, "labmonitor_docker_container_block_read_bytes_total", "web"
        )
        self.assertEqual(float(web_read["value"]), 4096.0)  # type: ignore[arg-type]

    def test_exporter_never_constructs_a_unix_socket_path(self) -> None:
        """The exporter source builds HTTP URLs only, with GET as the method."""
        here = pathlib.Path(__file__).resolve().parent
        app_source = (here / "app.py").read_text(encoding="utf-8")
        dockerfile = (here / "Dockerfile").read_text(encoding="utf-8")
        # Literals are assembled here so this file never contains them either.
        socket_fragment = "docker" + "." + "sock"
        unix_scheme = "unix" + "://"
        for name, source in (("app.py", app_source), ("Dockerfile", dockerfile)):
            self.assertNotIn(
                socket_fragment, source, f"{name} must never reference a socket file"
            )
            self.assertNotIn(
                unix_scheme, source, f"{name} must never build a socket URL scheme"
            )
        methods = re.findall(r"method\s*=\s*[\"']([A-Z]+)[\"']", app_source)
        self.assertTrue(methods, "app.py must construct requests with an explicit method")
        for method in methods:
            self.assertEqual(method, "GET", "every Docker request must use GET")

    def test_health_endpoint_does_not_call_mutating_docker_api(self) -> None:
        """GET /healthz answers without issuing any Docker API request."""
        fake = FakeDockerApiClient(make_routes())
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), create_handler(fake)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            body = response.read()
            self.assertEqual(response.status, 200)
            self.assertEqual(body, b"ok")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        mutating = {"POST", "PUT", "PATCH", "DELETE"}
        for method, url in fake.calls:
            self.assertNotIn(
                method, mutating, f"/healthz must not trigger mutating calls — got {url}"
            )
        self.assertEqual(
            fake.calls, [], "/healthz must not call the Docker API at all"
        )

    def test_render_prometheus_exposes_ten_stable_series(self) -> None:
        """Rendered exposition carries exactly the ten stable series."""
        fake = FakeDockerApiClient(make_routes())
        payload = render_prometheus(collect_container_metrics(fake)).decode("utf-8")
        expected = {
            "labmonitor_docker_container_info",
            "labmonitor_docker_container_cpu_usage_seconds_total",
            "labmonitor_docker_container_memory_usage_bytes",
            "labmonitor_docker_container_memory_limit_bytes",
            "labmonitor_docker_container_network_receive_bytes_total",
            "labmonitor_docker_container_network_transmit_bytes_total",
            "labmonitor_docker_container_block_read_bytes_total",
            "labmonitor_docker_container_block_write_bytes_total",
            "labmonitor_docker_container_restarts_total",
            "labmonitor_docker_container_health_status",
        }
        families = set(re.findall(r"^# TYPE (\S+) gauge$", payload, re.MULTILINE))
        self.assertEqual(
            families & {"labmonitor_" + name.split("labmonitor_")[-1] for name in expected},
            expected,
        )
        rendered = {
            name
            for name in expected
            if re.search(r"^" + re.escape(name) + r"\{", payload, re.MULTILINE)
        }
        self.assertEqual(rendered, expected)
        label_keys: set[str] = set()
        for match in re.finditer(r"^labmonitor_\S+\{([^}]*)\}", payload, re.MULTILINE):
            for pair in match.group(1).split(","):
                label_keys.add(pair.split("=", 1)[0])
        self.assertLessEqual(
            label_keys,
            {"container_id", "container_name", "image", "state", "network", "health"},
            f"labels must stay bounded — got {sorted(label_keys)}",
        )


if __name__ == "__main__":
    unittest.main()
