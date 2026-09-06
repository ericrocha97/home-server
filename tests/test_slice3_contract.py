"""Slice 3 platform foundation contract — Task 1 wiring.

Three named cases asserting the exact site role order, the non-secret
example-inventory contract (with no secret values), and stable Slice 3
ports/defaults. Stdlib only (no PyYAML) so the suite runs on any Python 3.

Task 8 adds the legacy-reference assertion after the active tree is ready
for the final removal check.
"""
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]

SITE = REPO / "ansible/site.yml"
LAB_EXAMPLE = REPO / "ansible/inventories/lab/group_vars/all.example.yml"
PROD_EXAMPLE = REPO / "ansible/inventories/prod/group_vars/all.example.yml"
COMPOSE_DEFAULTS = REPO / "ansible/roles/compose-services/defaults/main.yml"
DOCKER_DEFAULTS = REPO / "ansible/roles/docker-provider/defaults/main.yml"
DOCKER_TASKS = REPO / "ansible/roles/docker-provider/tasks/main.yml"
MONITORING_DEFAULTS = REPO / "ansible/roles/monitoring/defaults/main.yml"
MONITORING_TASKS = REPO / "ansible/roles/monitoring/tasks/main.yml"
PORTAINER_DEFAULTS = REPO / "ansible/roles/portainer/defaults/main.yml"
PORTAINER_TASKS = REPO / "ansible/roles/portainer/tasks/main.yml"
LABMONITOR_DEFAULTS = REPO / "ansible/roles/labmonitor-foundation/defaults/main.yml"
LABMONITOR_TASKS = REPO / "ansible/roles/labmonitor-foundation/tasks/main.yml"
PROVIDER_COMPOSE = REPO / "compose/docker-provider/compose.yaml"

EXPECTED_ORDER = [
    "base",
    "docker",
    "cockpit",
    "k3s",
    "compose-services",
    "docker-provider",
    "firewall",
    "monitoring",
    "portainer",
    "labmonitor-foundation",
    "k8s-platform",
]

# Exact non-secret Slice 3 contract shared by role defaults and example inventories.
EXPECTED_VARS = {
    "docker_socket_proxy_port": "12375",
    "docker_metrics_exporter_port": "9797",
    "monitoring_chart_version": "88.6.1",
    "monitoring_prometheus_service_name": "prometheus",
    "monitoring_prometheus_service_port": "9090",
    "prometheus_nodeport": "30909",
    "monitoring_grafana_service_name": "grafana",
    "monitoring_grafana_service_port": "3000",
    "grafana_nodeport": "30300",
    "monitoring_prometheus_retention": "15d",
    "monitoring_prometheus_storage_size": "20Gi",
    "monitoring_grafana_storage_size": "5Gi",
    "portainer_service_name": "portainer",
    "portainer_service_port": "9000",
    "portainer_nodeport": "30900",
    "labmonitor_namespace": "labmonitor",
    "labmonitor_service_account": "labmonitor-api",
    "jenkins_labmonitor_user": "labmonitor-api",
    "jenkins_prometheus_user": "prometheus-scraper",
    "compose_jenkins_labmonitor_id": "jenkins",
    "compose_n8n_labmonitor_id": "n8n",
    "compose_metabase_labmonitor_id": "metabase",
}

SECRET_KEY_RE = re.compile(r"password|passwd|token|secret|credentials?", re.IGNORECASE)
DIGEST_RE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")

# tecnativa/docker-socket-proxy capability contract (env names verified against
# 0.3.0): read endpoints granted, every mutating section revoked. POST=0 forces
# GET/HEAD only, which is what allows /version, /info, /containers/json,
# /containers/{id}/json, /containers/{id}/stats?stream=false, /images/json and
# /networks while blocking all writes.
PROVIDER_READ_ENV = {
    "CONTAINERS": "1",
    "IMAGES": "1",
    "NETWORKS": "1",
    "INFO": "1",
    "VERSION": "1",
}
PROVIDER_DISABLED_ENV = {
    "POST": "0",
    "BUILD": "0",
    "COMMIT": "0",
    "CONFIGS": "0",
    "DISTRIBUTION": "0",
    "EXEC": "0",
    "PLUGINS": "0",
    "SECRETS": "0",
    "SERVICES": "0",
    "SWARM": "0",
    "SYSTEM": "0",
    "TASKS": "0",
    "VOLUMES": "0",
}
# Mutating capabilities that must never be granted (PUT/PATCH/DELETE/PULL have
# no dedicated env flags; POST=0 blocks those methods globally).
PROVIDER_FORBIDDEN_CAPS = {
    "POST", "PUT", "PATCH", "DELETE", "EXEC", "BUILD",
    "PULL", "VOLUMES", "SECRETS", "CONFIGS", "SWARM",
}


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_simple_vars(path: pathlib.Path) -> dict:
    """Parse flat `key: value` lines; strip quotes/comments. Stdlib fallback for PyYAML."""
    out: dict = {}
    for raw in read(path).splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("-"):
            continue
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        out[key] = val
    return out


class TestSlice3Contract(unittest.TestCase):
    def test_site_order_contains_final_infrastructure_roles(self):
        """ansible/site.yml must list roles in the exact approved Slice 3 order with matching tags."""
        self.assertTrue(SITE.is_file(), f"missing {SITE}")
        content = read(SITE)
        roles = re.findall(r"-\s*role:\s*([A-Za-z0-9_.-]+)", content)
        self.assertEqual(
            roles,
            EXPECTED_ORDER,
            f"{SITE} role order must be {EXPECTED_ORDER} — got {roles}",
        )
        for role in EXPECTED_ORDER:
            self.assertIn(
                f"- role: {role}",
                content,
                f"{SITE} must contain '- role: {role}'",
            )
            self.assertIn(
                f"tags: [{role}]",
                content,
                f"{SITE} role {role} must carry tags: [{role}]",
            )
        # k8s-platform stays last and owns the final Traefik configuration.
        self.assertEqual(roles[-1], "k8s-platform",
                         f"{SITE} last role must be k8s-platform — got {roles[-1]}")
        # Pre-Slice-3 roles stay before compose-services.
        for early in ("base", "docker", "cockpit", "k3s"):
            self.assertLess(roles.index(early), roles.index("compose-services"),
                            f"{SITE}: {early} must precede compose-services — got {roles}")

    def test_example_inventories_have_no_secret_values(self):
        """Both example inventories carry the exact non-secret Slice 3 values and no secrets."""
        for path in (LAB_EXAMPLE, PROD_EXAMPLE):
            self.assertTrue(path.is_file(), f"missing {path}")
            content = read(path)
            parsed = parse_simple_vars(path)
            for key, expected in EXPECTED_VARS.items():
                self.assertIn(
                    key,
                    parsed,
                    f"{path} must define non-secret {key}={expected}",
                )
                self.assertEqual(
                    str(parsed[key]),
                    expected,
                    f"{path} {key} must be {expected} — got {parsed[key]}",
                )
            for raw in content.splitlines():
                stripped = raw.split("#", 1)[0]
                if not stripped.strip() or stripped.lstrip().startswith("-"):
                    continue
                m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", stripped)
                if not m:
                    continue
                self.assertIsNone(
                    SECRET_KEY_RE.search(m.group(1)),
                    f"{path} must not contain secret key {m.group(1)}: {raw.strip()}",
                )

    def test_slice3_defaults_have_stable_ports(self):
        """Role defaults pin stable ports/NodePorts/retention/storage and immutable image refs."""
        for path in (COMPOSE_DEFAULTS, DOCKER_DEFAULTS, MONITORING_DEFAULTS,
                     PORTAINER_DEFAULTS, LABMONITOR_DEFAULTS):
            self.assertTrue(path.is_file(), f"missing {path}")
        merged: dict = {}
        file_of: dict = {}
        for path in (COMPOSE_DEFAULTS, DOCKER_DEFAULTS, MONITORING_DEFAULTS,
                     PORTAINER_DEFAULTS, LABMONITOR_DEFAULTS):
            for key, val in parse_simple_vars(path).items():
                merged.setdefault(key, val)
                file_of.setdefault(key, str(path))
        for key, expected in EXPECTED_VARS.items():
            self.assertIn(key, merged,
                          f"role defaults must define {key}={expected} (checked {file_of})")
            self.assertEqual(str(merged[key]), expected,
                             f"{file_of.get(key)} {key} must be {expected} — got {merged[key]}")
        # Per-role spot checks tie each variable to its owning file.
        self.assertEqual(parse_simple_vars(DOCKER_DEFAULTS).get("docker_socket_proxy_port"),
                         "12375",
                         f"{DOCKER_DEFAULTS} docker_socket_proxy_port must be 12375")
        mon = parse_simple_vars(MONITORING_DEFAULTS)
        self.assertEqual(mon.get("monitoring_chart_version"), "88.6.1",
                         f"{MONITORING_DEFAULTS} monitoring_chart_version must be 88.6.1")
        self.assertEqual(mon.get("prometheus_nodeport"), "30909",
                         f"{MONITORING_DEFAULTS} prometheus_nodeport must be 30909")
        self.assertEqual(mon.get("grafana_nodeport"), "30300",
                         f"{MONITORING_DEFAULTS} grafana_nodeport must be 30300")
        self.assertEqual(
            parse_simple_vars(PORTAINER_DEFAULTS).get("portainer_nodeport"), "30900",
            f"{PORTAINER_DEFAULTS} portainer_nodeport must be 30900")
        lab = parse_simple_vars(LABMONITOR_DEFAULTS)
        self.assertEqual(lab.get("labmonitor_namespace"), "labmonitor",
                         f"{LABMONITOR_DEFAULTS} labmonitor_namespace must be labmonitor")
        self.assertEqual(lab.get("labmonitor_service_account"), "labmonitor-api",
                         f"{LABMONITOR_DEFAULTS} labmonitor_service_account must be labmonitor-api")
        # Preflight assertions must exist in each new role entrypoint.
        for tasks_path, snippet in (
            (DOCKER_TASKS, "docker_socket_proxy_port == 12375"),
            (MONITORING_TASKS, "prometheus_nodeport == 30909"),
            (PORTAINER_TASKS, "portainer_nodeport == 30900"),
            (LABMONITOR_TASKS, "labmonitor_namespace == 'labmonitor'"),
        ):
            self.assertTrue(tasks_path.is_file(), f"missing {tasks_path}")
            self.assertIn(snippet, read(tasks_path),
                          f"{tasks_path} must contain preflight assert '{snippet}'")
        # Image refs: never `latest`; digest refs must match ^.+@sha256:[0-9a-f]{64}$.
        for path in (COMPOSE_DEFAULTS, DOCKER_DEFAULTS, MONITORING_DEFAULTS,
                     PORTAINER_DEFAULTS):
            for key, val in parse_simple_vars(path).items():
                if not key.endswith("_image"):
                    continue
                self.assertNotIn("latest", val.lower(),
                                 f"{path} {key} must not use 'latest' — got {val}")
                if "@sha256:" in val:
                    self.assertRegex(val, DIGEST_RE,
                                     f"{path} {key} digest must match ^.+@sha256:[0-9a-f]{{64}}$ — got {val}")

    def test_socket_proxy_is_the_only_read_only_docker_consumer(self):
        """compose/docker-provider/compose.yaml holds the only :ro socket mount, in docker-socket-proxy."""
        self.assertTrue(PROVIDER_COMPOSE.is_file(), f"missing {PROVIDER_COMPOSE}")
        services = parse_compose_services(PROVIDER_COMPOSE)
        self.assertIn("docker-socket-proxy", services,
                      f"{PROVIDER_COMPOSE} must define service docker-socket-proxy — got {sorted(services)}")
        mounts = {
            name: [v for v in svc["volumes"] if "/var/run/docker.sock" in v]
            for name, svc in services.items()
        }
        total = sum(len(v) for v in mounts.values())
        self.assertEqual(total, 1,
                         f"{PROVIDER_COMPOSE} must contain exactly one docker.sock mount — got {mounts}")
        mount = mounts["docker-socket-proxy"][0]
        self.assertTrue(mount.startswith("/var/run/docker.sock:/var/run/docker.sock"),
                        f"{PROVIDER_COMPOSE} socket mount source must be /var/run/docker.sock — got {mount}")
        self.assertTrue(mount.endswith(":ro"),
                        f"{PROVIDER_COMPOSE} socket mount must be read-only (:ro) — got {mount}")
        # Repo-wide: no other Compose project may mount the socket, except the
        # pre-existing Slice 2 Jenkins RW build exception (never read-only).
        for project in sorted((REPO / "compose").glob("*/compose.yaml")):
            if project == PROVIDER_COMPOSE:
                continue
            if "/var/run/docker.sock" in read(project):
                self.assertEqual(project.parent.name, "jenkins",
                                 f"{project} unexpectedly mounts the Docker socket — "
                                 "only jenkins (Slice 2 RW build exception) and "
                                 "docker-provider (read-only proxy) may do so")

    def test_socket_proxy_has_only_read_mount_and_no_mutating_flags(self):
        """Proxy service mounts only the :ro socket and grants read-only API sections."""
        self.assertTrue(PROVIDER_COMPOSE.is_file(), f"missing {PROVIDER_COMPOSE}")
        services = parse_compose_services(PROVIDER_COMPOSE)
        svc = services["docker-socket-proxy"]
        self.assertEqual(svc["volumes"], ["/var/run/docker.sock:/var/run/docker.sock:ro"],
                         f"{PROVIDER_COMPOSE} docker-socket-proxy must mount only the "
                         f"read-only socket — got {svc['volumes']}")
        env = svc["environment"]
        for key, expected in PROVIDER_READ_ENV.items():
            self.assertEqual(env.get(key), expected,
                             f"{PROVIDER_COMPOSE} {key} must be {expected} — got {env.get(key)}")
        for key, expected in PROVIDER_DISABLED_ENV.items():
            self.assertEqual(env.get(key), expected,
                             f"{PROVIDER_COMPOSE} {key} must be {expected} — got {env.get(key)}")
        for cap in sorted(PROVIDER_FORBIDDEN_CAPS):
            if cap in env:
                self.assertEqual(env[cap], "0",
                                 f"{PROVIDER_COMPOSE} mutating capability {cap} must stay "
                                 f"disabled — got {env[cap]}")

    def test_socket_proxy_publishes_only_port_12375(self):
        """docker-socket-proxy publishes exactly one host port: 12375 -> 2375."""
        self.assertTrue(PROVIDER_COMPOSE.is_file(), f"missing {PROVIDER_COMPOSE}")
        services = parse_compose_services(PROVIDER_COMPOSE)
        for name, svc in services.items():
            if name == "docker-socket-proxy":
                continue
            self.assertEqual(svc["ports"], [],
                             f"{PROVIDER_COMPOSE} service {name} must not publish ports — "
                             f"got {svc['ports']}")
        ports = services["docker-socket-proxy"]["ports"]
        self.assertEqual(len(ports), 1,
                         f"{PROVIDER_COMPOSE} docker-socket-proxy must publish exactly one "
                         f"port — got {ports}")
        entry = ports[0]
        m = re.search(r":(\d+):(\d+)\s*$", entry)
        self.assertIsNotNone(m,
                             f"{PROVIDER_COMPOSE} port entry must be host:container — got {entry}")
        host, container = m.groups() if m is not None else ("", "")
        self.assertEqual(host, "12375",
                         f"{PROVIDER_COMPOSE} host port must be 12375 — got {entry}")
        self.assertEqual(container, "2375",
                         f"{PROVIDER_COMPOSE} container port must be 2375 — got {entry}")
        self.assertIn("DOCKER_SOCKET_PROXY_BIND_IP", entry,
                      f"{PROVIDER_COMPOSE} port entry must bind via "
                      f"DOCKER_SOCKET_PROXY_BIND_IP — got {entry}")


def parse_compose_services(path: pathlib.Path) -> dict:
    """Minimal indentation-based Compose parser (stdlib only).

    Returns {service_name: {"volumes": [...], "ports": [...], "environment": {k: v}}}.
    Supports mapping-style (`KEY: "v"`) and list-style (`- KEY=v`) environment entries.
    """
    services: dict = {}
    current_service: str | None = None
    current_key: str | None = None
    in_services = False
    for raw in read(path).splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or line.strip() == "---":
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0:
            in_services = stripped == "services:"
            current_service = None
            current_key = None
            continue
        if not in_services:
            continue
        if indent == 2 and stripped.endswith(":"):
            current_service = stripped[:-1]
            services[current_service] = {"volumes": [], "ports": [], "environment": {}}
            current_key = None
        elif indent == 4 and current_service is not None:
            if stripped.endswith(":"):
                key = stripped[:-1]
                current_key = key if key in ("volumes", "ports", "environment") else None
            else:
                current_key = None
        elif indent == 6 and current_service is not None and current_key in ("volumes", "ports"):
            m = re.match(r"^-\s+(.*)$", stripped)
            if m:
                val = m.group(1).strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                    val = val[1:-1]
                services[current_service][current_key].append(val)
        elif indent == 6 and current_service is not None and current_key == "environment":
            if stripped.startswith("-"):
                m = re.match(r"^-\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$", stripped)
                if m:
                    services[current_service]["environment"][m.group(1)] = m.group(2).strip().strip("'\"")
            elif ":" in stripped:
                key, val = stripped.split(":", 1)
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                    val = val[1:-1]
                services[current_service]["environment"][key.strip()] = val
    return services


if __name__ == "__main__":
    unittest.main()
