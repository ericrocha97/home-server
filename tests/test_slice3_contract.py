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


if __name__ == "__main__":
    unittest.main()
