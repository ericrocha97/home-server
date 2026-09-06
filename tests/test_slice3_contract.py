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


JENKINS_PLUGINS = REPO / "compose/jenkins/plugins.txt"
JENKINS_DOCKERFILE = REPO / "compose/jenkins/Dockerfile"
JENKINS_COMPOSE = REPO / "compose/jenkins/compose.yaml"
JENKINS_ENV_EXAMPLE = REPO / "compose/jenkins/.env.example"
JENKINS_ENV_TEMPLATE = REPO / "ansible/roles/compose-services/templates/jenkins.env.j2"
PHASE1_GROOVY = REPO / "ansible/roles/compose-services/templates/jenkins-init-admin.groovy.j2"
PHASE2_GROOVY = REPO / "ansible/roles/compose-services/templates/jenkins-provider-users.groovy.j2"
COMPOSE_TASKS = REPO / "ansible/roles/compose-services/tasks/main.yml"
N8N_COMPOSE = REPO / "compose/n8n/compose.yaml"
METABASE_COMPOSE = REPO / "compose/metabase/compose.yaml"
N8N_ENV_EXAMPLE = REPO / "compose/n8n/.env.example"
METABASE_ENV_EXAMPLE = REPO / "compose/metabase/.env.example"
N8N_ENV_TEMPLATE = REPO / "ansible/roles/compose-services/templates/n8n.env.j2"
METABASE_ENV_TEMPLATE = REPO / "ansible/roles/compose-services/templates/metabase.env.j2"
POSTGRES_COMPOSE = REPO / "compose/postgres/compose.yaml"


class TestSlice3Task3JenkinsProviders(unittest.TestCase):
    def test_jenkins_phase_one_does_not_create_provider_users(self):
        """Phase-one Groovy bootstraps admin only; provider users belong to phase two."""
        self.assertTrue(PHASE1_GROOVY.is_file(), f"missing {PHASE1_GROOVY}")
        self.assertTrue(PHASE2_GROOVY.is_file(), f"missing {PHASE2_GROOVY}")
        phase1 = read(PHASE1_GROOVY).lower()
        for marker in ("labmonitor-api", "prometheus-scraper", "apitokenproperty",
                       "jenkins_labmonitor", "jenkins_prometheus",
                       "labmonitor_api_token", "prometheus_api_token"):
            self.assertNotIn(marker, phase1,
                             f"{PHASE1_GROOVY} must not reference provider marker '{marker}'")
        # Phase one still bootstraps the existing admin without logging secrets.
        original = read(PHASE1_GROOVY)
        self.assertIn("JENKINS_ADMIN_ID", original,
                      f"{PHASE1_GROOVY} must preserve the existing admin account")
        self.assertIn("JENKINS_ADMIN_PASSWORD", original,
                      f"{PHASE1_GROOVY} must validate the existing admin password")
        self.assertIn("HudsonPrivateSecurityRealm", original,
                      f"{PHASE1_GROOVY} must use HudsonPrivateSecurityRealm")
        self.assertNotIn("println", original.replace("println(\"Created admin user", ""),
                         f"{PHASE1_GROOVY} must not log passwords or tokens")
        # Ansible render of the phase-one script must hide secrets.
        tasks = read(COMPOSE_TASKS)
        idx = tasks.find("jenkins-init-admin.groovy.j2")
        self.assertNotEqual(idx, -1, f"{COMPOSE_TASKS} must render jenkins-init-admin.groovy.j2")
        window = tasks[idx:idx + 2000]
        self.assertIn("no_log: true", window,
                      f"{COMPOSE_TASKS} phase-one render must use no_log: true")

    def test_jenkins_uses_fine_grained_authorization(self):
        """Phase one migrates FullControlOnceLoggedIn to GlobalMatrixAuthorizationStrategy."""
        self.assertTrue(PHASE1_GROOVY.is_file(), f"missing {PHASE1_GROOVY}")
        content = read(PHASE1_GROOVY)
        self.assertIn("GlobalMatrixAuthorizationStrategy", content,
                      f"{PHASE1_GROOVY} must install GlobalMatrixAuthorizationStrategy")
        self.assertIn("Jenkins.ADMINISTER", content,
                      f"{PHASE1_GROOVY} must grant admin via Jenkins.ADMINISTER constant")
        self.assertNotIn("FullControlOnceLoggedInAuthorizationStrategy", content,
                         f"{PHASE1_GROOVY} must not retain FullControlOnceLoggedInAuthorizationStrategy")
        self.assertIn("JenkinsLocationConfiguration", content,
                      f"{PHASE1_GROOVY} must set the Jenkins URL from the generated .arpa value")
        self.assertIn("JENKINS_URL", content,
                      f"{PHASE1_GROOVY} must read JENKINS_URL for the .arpa hostname")
        # Permission constants, not free-form strings, and no anonymous grant.
        self.assertNotIn("setAllowAnonymousRead(true)", content,
                         f"{PHASE1_GROOVY} must disable anonymous read access")
        self.assertNotIn('"Overall/Administer"', content,
                         f"{PHASE1_GROOVY} must use permission constants, not free-form strings")
        self.assertNotIn("'Overall/Administer'", content,
                         f"{PHASE1_GROOVY} must use permission constants, not free-form strings")
        # Phase two preserves the fine-grained strategy instead of replacing it.
        phase2 = read(PHASE2_GROOVY)
        self.assertIn("GlobalMatrixAuthorizationStrategy", phase2,
                      f"{PHASE2_GROOVY} must reconcile against GlobalMatrixAuthorizationStrategy")

    def test_jenkins_admin_checkpoint_precedes_provider_user_render(self):
        """Admin checkpoint (login, anon non-2xx, health, strategy) precedes phase-two render."""
        self.assertTrue(COMPOSE_TASKS.is_file(), f"missing {COMPOSE_TASKS}")
        tasks = read(COMPOSE_TASKS)
        phase1_idx = tasks.find("jenkins-init-admin.groovy.j2")
        phase2_idx = tasks.find("jenkins-provider-users.groovy.j2")
        self.assertNotEqual(phase1_idx, -1, f"{COMPOSE_TASKS} must render phase-one script")
        self.assertNotEqual(phase2_idx, -1, f"{COMPOSE_TASKS} must render phase-two script")
        self.assertLess(phase1_idx, phase2_idx,
                        f"{COMPOSE_TASKS} phase-one render must precede phase-two render")
        lower = tasks.lower()
        # Checkpoint markers: admin login, anonymous denial, health endpoint, strategy.
        admin_idx = lower.find("admin login")
        if admin_idx == -1:
            admin_idx = tasks.find("jenkins_admin_password")
        anon_idx = lower.find("anonymous")
        health_idx = lower.find("health endpoint")
        if health_idx == -1:
            health_idx = tasks.find("/login")
        strategy_idx = tasks.find("GlobalMatrixAuthorizationStrategy")
        for name, idx in (("admin login checkpoint", admin_idx),
                          ("anonymous non-2xx checkpoint", anon_idx),
                          ("health endpoint checkpoint", health_idx),
                          ("fine-grained strategy checkpoint", strategy_idx)):
            self.assertNotEqual(idx, -1, f"{COMPOSE_TASKS} must contain {name}")
            self.assertLess(idx, phase2_idx,
                            f"{COMPOSE_TASKS} {name} must precede phase-two render")
        # Negative checks require non-2xx, never one single status code.
        self.assertIn("^2", tasks,
                      f"{COMPOSE_TASKS} anonymous/forbidden checks must assert non-2xx (e.g. ^2xx)")
        self.assertNotIn('stdout == "403"', tasks,
                         f"{COMPOSE_TASKS} must not assert a single 403 code for Jenkins denial")
        self.assertNotIn("status_code: [403]", tasks,
                         f"{COMPOSE_TASKS} must not require one single HTTP error code")
        # Metrics scrape contract uses the trailing-slash endpoint with separate credential.
        self.assertIn("/prometheus/", tasks,
                      f"{COMPOSE_TASKS} must reference the /prometheus/ endpoint with trailing slash")

    def test_jenkins_provider_users_use_separate_credentials(self):
        """Phase two reconciles two least-privilege users with separate Vault credentials."""
        self.assertTrue(PHASE2_GROOVY.is_file(), f"missing {PHASE2_GROOVY}")
        groovy = read(PHASE2_GROOVY)
        for marker in ("JENKINS_LABMONITOR_USER", "JENKINS_PROMETHEUS_USER",
                       "JENKINS_LABMONITOR_PASSWORD", "JENKINS_PROMETHEUS_PASSWORD",
                       "JENKINS_LABMONITOR_API_TOKEN", "JENKINS_PROMETHEUS_API_TOKEN"):
            self.assertIn(marker, groovy,
                          f"{PHASE2_GROOVY} must reference separate credential {marker}")
        self.assertIn("hudson.model.User", groovy,
                      f"{PHASE2_GROOVY} must use hudson.model.User")
        self.assertIn("jenkins.security.ApiTokenProperty", groovy,
                      f"{PHASE2_GROOVY} must apply tokens via ApiTokenProperty")
        self.assertIn("IllegalStateException", groovy,
                      f"{PHASE2_GROOVY} must fail when the pinned API cannot set a Vault token")
        self.assertNotIn("JENKINS_ADMIN_PASSWORD", groovy,
                         f"{PHASE2_GROOVY} must not alter the existing admin credential")
        # Least privilege: read-only constants only.
        for perm in ("Jenkins.READ", "Item.READ", "View.READ"):
            self.assertIn(perm, groovy,
                          f"{PHASE2_GROOVY} must grant least-privilege constant {perm}")
        self.assertIn("Run.READ", groovy,
                      f"{PHASE2_GROOVY} must grant run/build read via Run.READ")
        for forbidden in ("Jenkins.ADMINISTER", "Item.BUILD", "Item.CONFIGURE", "Item.DELETE"):
            self.assertNotIn(forbidden, groovy,
                             f"{PHASE2_GROOVY} must not grant forbidden permission {forbidden}")
        self.assertNotIn("println", groovy.replace("println(\"Reconciled provider user", ""),
                         f"{PHASE2_GROOVY} must not print secrets")
        # Vault-backed environment carries four distinct secrets with no_log.
        env_template = read(JENKINS_ENV_TEMPLATE)
        for var in ("jenkins_labmonitor_password", "jenkins_labmonitor_api_token",
                    "jenkins_prometheus_password", "jenkins_prometheus_api_token"):
            self.assertIn(var, env_template,
                          f"{JENKINS_ENV_TEMPLATE} must map Vault secret {var}")
        tasks = read(COMPOSE_TASKS)
        for var in ("jenkins_labmonitor_password", "jenkins_prometheus_password",
                    "jenkins_labmonitor_api_token", "jenkins_prometheus_api_token"):
            self.assertIn(var, tasks,
                          f"{COMPOSE_TASKS} must validate Vault secret {var}")
        self.assertIn("no_log: true", tasks,
                      f"{COMPOSE_TASKS} must never print provider secrets")
        # Examples carry placeholders, never Vault interpolation or real secrets.
        example = read(JENKINS_ENV_EXAMPLE)
        self.assertIn("JENKINS_LABMONITOR_USER=labmonitor-api", example,
                      f"{JENKINS_ENV_EXAMPLE} must document the labmonitor user")
        self.assertIn("JENKINS_PROMETHEUS_USER=prometheus-scraper", example,
                      f"{JENKINS_ENV_EXAMPLE} must document the prometheus user")
        self.assertNotIn("{{", example,
                         f"{JENKINS_ENV_EXAMPLE} must not interpolate Vault values")
        self.assertNotIn("jenkins_labmonitor_password", example,
                         f"{JENKINS_ENV_EXAMPLE} must not embed Vault variable names")

    def test_compose_apps_have_environment_derived_labmonitor_labels(self):
        """Jenkins/n8n/Metabase expose the six labmonitor.* labels via environment interpolation."""
        required_labels = [
            'labmonitor.enabled: "${LABMONITOR_ENABLED:-true}"',
            'labmonitor.id: "${LABMONITOR_ID:?required}"',
            'labmonitor.name: "${LABMONITOR_NAME:?required}"',
            'labmonitor.category: "${LABMONITOR_CATEGORY:?required}"',
            'labmonitor.icon: "${LABMONITOR_ICON:?required}"',
            'labmonitor.open.url: "${LABMONITOR_OPEN_URL:?required}"',
        ]
        for path in (JENKINS_COMPOSE, N8N_COMPOSE, METABASE_COMPOSE):
            self.assertTrue(path.is_file(), f"missing {path}")
            content = read(path)
            for label in required_labels:
                self.assertIn(label, content,
                              f"{path} must contain label {label}")
        # Each Ansible .env template renders exactly one environment-specific URL from base_domain.
        for template in (JENKINS_ENV_TEMPLATE, N8N_ENV_TEMPLATE, METABASE_ENV_TEMPLATE):
            self.assertTrue(template.is_file(), f"missing {template}")
            content = read(template)
            self.assertIn("LABMONITOR_OPEN_URL", content,
                          f"{template} must render LABMONITOR_OPEN_URL")
            self.assertIn("base_domain", content,
                          f"{template} must derive the URL from base_domain")
            self.assertEqual(content.count("LABMONITOR_OPEN_URL"), 1,
                             f"{template} must render exactly one LABMONITOR_OPEN_URL")
            for var in ("LABMONITOR_ENABLED", "LABMONITOR_ID", "LABMONITOR_NAME",
                        "LABMONITOR_CATEGORY", "LABMONITOR_ICON"):
                self.assertIn(var, content,
                              f"{template} must render {var}")

    def test_compose_apps_have_stable_labmonitor_ids(self):
        """labmonitor.id values are stable literals, never computed from runtime names."""
        defaults = parse_simple_vars(COMPOSE_DEFAULTS)
        self.assertEqual(defaults.get("compose_jenkins_labmonitor_id"), "jenkins",
                         f"{COMPOSE_DEFAULTS} jenkins id must be stable 'jenkins'")
        self.assertEqual(defaults.get("compose_n8n_labmonitor_id"), "n8n",
                         f"{COMPOSE_DEFAULTS} n8n id must be stable 'n8n'")
        self.assertEqual(defaults.get("compose_metabase_labmonitor_id"), "metabase",
                         f"{COMPOSE_DEFAULTS} metabase id must be stable 'metabase'")
        for path in (JENKINS_COMPOSE, N8N_COMPOSE, METABASE_COMPOSE):
            content = read(path)
            self.assertIn('labmonitor.id: "${LABMONITOR_ID:?required}"', content,
                          f"{path} labmonitor.id must use LABMONITOR_ID interpolation")
            self.assertNotIn("COMPOSE_PROJECT", content,
                             f"{path} labmonitor.id must not derive from the Compose project name")
            self.assertNotIn("container_name", content.split("labmonitor.id")[1].splitlines()[0],
                             f"{path} labmonitor.id must not derive from container_name")
        examples = {
            JENKINS_ENV_EXAMPLE: "LABMONITOR_ID=jenkins",
            N8N_ENV_EXAMPLE: "LABMONITOR_ID=n8n",
            METABASE_ENV_EXAMPLE: "LABMONITOR_ID=metabase",
        }
        for path, expected in examples.items():
            self.assertTrue(path.is_file(), f"missing {path}")
            self.assertIn(expected, read(path),
                          f"{path} must pin stable {expected}")

    def test_postgres_and_provider_projects_have_no_navigable_labmonitor_url(self):
        """PostgreSQL, the socket proxy, and the exporter are providers, not app cards."""
        for path in (POSTGRES_COMPOSE, PROVIDER_COMPOSE):
            self.assertTrue(path.is_file(), f"missing {path}")
            content = read(path)
            self.assertNotIn("labmonitor.open.url", content,
                             f"{path} must not expose a navigable labmonitor URL")
            self.assertNotIn("LABMONITOR_OPEN_URL", content,
                             f"{path} must not interpolate a navigable labmonitor URL")
        # Positive control: the three Compose applications do expose exactly one URL each.
        for path in (JENKINS_COMPOSE, N8N_COMPOSE, METABASE_COMPOSE):
            self.assertIn("labmonitor.open.url", read(path),
                          f"{path} must expose one navigable labmonitor URL")

    def test_jenkins_plugin_file_has_exact_versions(self):
        """plugins.txt pins the two Slice 3 plugins; Dockerfile installs via the image CLI."""
        self.assertTrue(JENKINS_PLUGINS.is_file(), f"missing {JENKINS_PLUGINS}")
        lines = [ln.strip() for ln in read(JENKINS_PLUGINS).splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        self.assertEqual(sorted(lines),
                         sorted(["prometheus:860.v532442b_44e9_", "matrix-auth:3.3"]),
                         f"{JENKINS_PLUGINS} must pin exactly prometheus:860.v532442b_44e9_ "
                         f"and matrix-auth:3.3 — got {lines}")
        self.assertEqual(len(lines), 2,
                         f"{JENKINS_PLUGINS} must contain exactly two pinned plugins — got {lines}")
        for line in lines:
            self.assertNotIn("latest", line.lower(),
                             f"{JENKINS_PLUGINS} must never use 'latest' — got {line}")
        dockerfile = read(JENKINS_DOCKERFILE)
        self.assertIn("ARG JENKINS_BASE_IMAGE", dockerfile,
                      f"{JENKINS_DOCKERFILE} must keep the base image in a required build arg")
        self.assertIn("FROM ${JENKINS_BASE_IMAGE}", dockerfile,
                      f"{JENKINS_DOCKERFILE} must build FROM ${{JENKINS_BASE_IMAGE}}")
        self.assertNotIn("FROM jenkins/jenkins:", dockerfile,
                         f"{JENKINS_DOCKERFILE} must not hardcode the base image reference")
        self.assertIn("plugins.txt", dockerfile,
                      f"{JENKINS_DOCKERFILE} must copy plugins.txt")
        self.assertIn("jenkins-plugin-cli", dockerfile,
                      f"{JENKINS_DOCKERFILE} must run the image-provided plugin installer")
        tasks = read(COMPOSE_TASKS)
        self.assertIn("plugins.txt", tasks,
                      f"{COMPOSE_TASKS} must ship plugins.txt to the host and fingerprint it")


EXPORTER_DEPLOYMENT = REPO / "ansible/roles/monitoring/templates/docker-exporter-deployment.yaml.j2"
EXPORTER_SERVICE = REPO / "ansible/roles/monitoring/templates/docker-exporter-service.yaml.j2"
EXPORTER_SERVICEMONITOR = REPO / "ansible/roles/monitoring/templates/docker-exporter-servicemonitor.yaml.j2"
EXPORTER_RECORDING_RULES = REPO / "ansible/roles/monitoring/templates/docker-exporter-recording-rules.yaml.j2"
EXPORTER_APP = REPO / "k8s/monitoring/docker-metrics-exporter/app.py"
EXPORTER_TEST = REPO / "k8s/monitoring/docker-metrics-exporter/test_app.py"
EXPORTER_REQUIREMENTS = REPO / "k8s/monitoring/docker-metrics-exporter/requirements.txt"
EXPORTER_DOCKERFILE = REPO / "k8s/monitoring/docker-metrics-exporter/Dockerfile"

REQUIRED_EXPORTER_SERIES = [
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
]


class TestSlice3Task4DockerExporter(unittest.TestCase):
    def test_exporter_mode_is_built_with_immutable_image(self):
        """Gate result is recorded as built with a pinned local image."""
        mon = parse_simple_vars(MONITORING_DEFAULTS)
        self.assertEqual(mon.get("docker_metrics_exporter_mode"), "built",
                         f"{MONITORING_DEFAULTS} mode must be built after the failed gate")
        image = mon.get("docker_metrics_exporter_image", "")
        self.assertTrue(image.startswith("labmonitor-docker-exporter:"),
                        f"{MONITORING_DEFAULTS} built image must be the local fallback — got {image}")
        self.assertNotIn("latest", image.lower(),
                         f"{MONITORING_DEFAULTS} exporter image must not use latest — got {image}")
        self.assertEqual(mon.get("docker_metrics_exporter_port"), "9797",
                         f"{MONITORING_DEFAULTS} docker_metrics_exporter_port must be 9797")

    def test_exporter_deployment_uses_proxy_url_and_no_socket(self):
        """Deployment points at the proxy URL, exposes 9797, mounts nothing."""
        self.assertTrue(EXPORTER_DEPLOYMENT.is_file(), f"missing {EXPORTER_DEPLOYMENT}")
        content = read(EXPORTER_DEPLOYMENT)
        for marker in ("DOCKER_API_URL", "server_lan_ip", "docker_socket_proxy_port",
                       "METRICS_PORT", "9797", "docker_metrics_exporter_image",
                       "imagePullPolicy: IfNotPresent", "/healthz", "/metrics",
                       "runAsNonRoot", "docker-metrics-exporter"):
            self.assertIn(marker, content,
                          f"{EXPORTER_DEPLOYMENT} must contain {marker}")
        # Port and address stay variable-driven, never literals.
        self.assertNotIn("12375", content,
                         f"{EXPORTER_DEPLOYMENT} must use docker_socket_proxy_port, not a literal")
        self.assertIsNone(re.search(r"192\.168\.\d+", content),
                          f"{EXPORTER_DEPLOYMENT} must not embed a LAN IP literal")
        for forbidden in ("hostPort", "hostNetwork", "NodePort", "portainer",
                          "privileged: true", "2375", "latest"):
            self.assertNotIn(forbidden.lower(), content.lower(),
                             f"{EXPORTER_DEPLOYMENT} must not contain {forbidden}")
        # Socket references are assembled here so this file never holds them.
        socket_fragment = "docker" + "." + "sock"
        unix_scheme = "unix" + "://"
        self.assertNotIn(socket_fragment, content,
                         f"{EXPORTER_DEPLOYMENT} must not mount a socket file")
        self.assertNotIn(unix_scheme, content,
                         f"{EXPORTER_DEPLOYMENT} must not build a socket URL")

    def test_exporter_service_is_clusterip_metrics_only(self):
        """Service is a ClusterIP named docker-metrics-exporter on 9797."""
        self.assertTrue(EXPORTER_SERVICE.is_file(), f"missing {EXPORTER_SERVICE}")
        content = read(EXPORTER_SERVICE)
        for marker in ("kind: Service", "type: ClusterIP", "name: docker-metrics-exporter",
                       "port: 9797", "targetPort: 9797", "app: docker-metrics-exporter"):
            self.assertIn(marker, content,
                          f"{EXPORTER_SERVICE} must contain {marker}")
        for forbidden in ("NodePort", "LoadBalancer", "hostPort", "portainer"):
            self.assertNotIn(forbidden, content,
                             f"{EXPORTER_SERVICE} must not contain {forbidden}")

    def test_exporter_servicemonitor_scrapes_metrics(self):
        """ServiceMonitor is selected by the Prometheus release on /metrics."""
        self.assertTrue(EXPORTER_SERVICEMONITOR.is_file(), f"missing {EXPORTER_SERVICEMONITOR}")
        content = read(EXPORTER_SERVICEMONITOR)
        for marker in ("kind: ServiceMonitor", "monitoring_release_name", "path: /metrics",
                       "port: metrics", "app: docker-metrics-exporter",
                       "monitoring_namespace"):
            self.assertIn(marker, content,
                          f"{EXPORTER_SERVICEMONITOR} must contain {marker}")
        self.assertNotIn("portainer", content.lower(),
                         f"{EXPORTER_SERVICEMONITOR} must not reference Portainer")

    def test_exporter_artifacts_match_selected_mode(self):
        """Built mode ships fallback source and skips recording rules; upstream is the reverse."""
        mode = parse_simple_vars(MONITORING_DEFAULTS).get("docker_metrics_exporter_mode")
        if mode == "built":
            for path in (EXPORTER_APP, EXPORTER_TEST, EXPORTER_REQUIREMENTS, EXPORTER_DOCKERFILE):
                self.assertTrue(path.is_file(), f"missing {path} in built mode")
            self.assertFalse(EXPORTER_RECORDING_RULES.exists(),
                             f"{EXPORTER_RECORDING_RULES} must not exist in built mode "
                             "(fallback names are already stable)")
            dockerfile = read(EXPORTER_DOCKERFILE)
            self.assertRegex(dockerfile, r"FROM python:3\.12-slim@sha256:[0-9a-f]{64}",
                             f"{EXPORTER_DOCKERFILE} must pin the Python base by digest")
            self.assertNotIn("latest", dockerfile.lower(),
                             f"{EXPORTER_DOCKERFILE} must not use latest")
            for marker in ("USER 65534", "EXPOSE 9797", "HEALTHCHECK", "/healthz"):
                self.assertIn(marker, dockerfile,
                              f"{EXPORTER_DOCKERFILE} must contain {marker}")
            requirements = read(EXPORTER_REQUIREMENTS).strip()
            self.assertRegex(requirements, r"^prometheus_client==\d+\.\d+\.\d+\s*$",
                             f"{EXPORTER_REQUIREMENTS} must pin one exact client version")
        else:
            for path in (EXPORTER_APP, EXPORTER_TEST, EXPORTER_REQUIREMENTS, EXPORTER_DOCKERFILE):
                self.assertFalse(path.exists(),
                                 f"{path} must not exist in upstream mode")

    def test_fallback_collector_covers_required_series(self):
        """Fallback source defines the interfaces, paths, series, and bounded labels."""
        self.assertTrue(EXPORTER_APP.is_file(), f"missing {EXPORTER_APP}")
        content = read(EXPORTER_APP)
        for marker in ("class DockerApiClient", "def get_json", "def collect_container_metrics",
                       "def render_prometheus", "/version", "/containers/json?all=1",
                       "/containers/%s/json", "stats?stream=false"):
            self.assertIn(marker, content,
                          f"{EXPORTER_APP} must contain {marker}")
        for series in REQUIRED_EXPORTER_SERIES:
            self.assertIn(series, content,
                          f"{EXPORTER_APP} must expose stable series {series}")
        for label in ("container_id", "container_name", "image", "state", "network", "health"):
            self.assertIn(label, content,
                          f"{EXPORTER_APP} must use bounded label {label}")
        for value in ("healthy", "unhealthy", "starting", "none"):
            self.assertIn(value, content,
                          f"{EXPORTER_APP} must bound health values (missing {value})")
        socket_fragment = "docker" + "." + "sock"
        unix_scheme = "unix" + "://"
        self.assertNotIn(socket_fragment, content,
                         f"{EXPORTER_APP} must never reference a socket file")
        self.assertNotIn(unix_scheme, content,
                         f"{EXPORTER_APP} must never build a socket URL")

    def test_exporter_tasks_cover_build_and_deploy(self):
        """Monitoring tasks build/import the fallback image and apply the manifests."""
        self.assertTrue(MONITORING_TASKS.is_file(), f"missing {MONITORING_TASKS}")
        tasks = read(MONITORING_TASKS)
        for marker in ("docker_metrics_exporter_mode in ['upstream', 'built']",
                       "docker save", "k3s ctr images import",
                       "docker-exporter-deployment.yaml",
                       "docker-exporter-service.yaml",
                       "docker-exporter-servicemonitor.yaml",
                       "deployment/docker-metrics-exporter"):
            self.assertIn(marker, tasks,
                          f"{MONITORING_TASKS} must contain {marker}")


MONITORING_VALUES = REPO / "ansible/roles/monitoring/templates/values.yaml.j2"
MONITORING_SCRAPE = REPO / "ansible/roles/monitoring/templates/additional-scrape-configs.yaml.j2"
DASHBOARD_DIR = REPO / "k8s/monitoring/dashboards"

EXPECTED_DASHBOARDS = ("host.json", "docker.json", "kubernetes.json", "jenkins.json")

HOST_SERIES = [
    "node_cpu_seconds_total",
    "node_memory_MemAvailable_bytes",
    "node_memory_SwapFree_bytes",
    "node_filesystem_avail_bytes",
    "node_disk_read_bytes_total",
    "node_network_receive_bytes_total",
]

KUBERNETES_SERIES = [
    "kube_node_info",
    "kube_pod_info",
    "kube_deployment_status_replicas_available",
    "container_cpu_usage_seconds_total",
    "container_memory_working_set_bytes",
]

JENKINS_SERIES = [
    "default_jenkins_up",
    "default_jenkins_uptime",
    "default_jenkins_executors_busy",
    "default_jenkins_executors_queue_length",
    "default_jenkins_nodes_online",
    "default_jenkins_builds_success_build_count",
]


def values_block(content: str, header: str, width: int = 400) -> str:
    """Return the text window following a top-level values header."""
    idx = content.find(header)
    assert idx != -1, f"values template must contain header {header}"
    return content[idx:idx + width]


def dashboard_exprs(path: pathlib.Path) -> list:
    """Collect every PromQL expr from a Grafana dashboard JSON file."""
    import json as _json
    doc = _json.loads(read(path))
    exprs: list = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key == "expr" and isinstance(val, str):
                    exprs.append(val)
                else:
                    walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc.get("panels", []))
    return exprs


class TestSlice3Task5Monitoring(unittest.TestCase):
    def test_monitoring_values_enable_required_exporters(self):
        """Values enable nodeExporter, kubeStateMetrics, kubelet/cAdvisor; exporter stays scraped."""
        self.assertTrue(MONITORING_VALUES.is_file(), f"missing {MONITORING_VALUES}")
        content = read(MONITORING_VALUES)
        for header in ("nodeExporter:", "kubeStateMetrics:", "kubelet:"):
            self.assertIn(header, content,
                          f"{MONITORING_VALUES} must contain {header}")
            self.assertIn("enabled: true", values_block(content, header),
                          f"{MONITORING_VALUES} {header} must set enabled: true")
        self.assertIn("cAdvisor: true", values_block(content, "kubelet:", 800),
                      f"{MONITORING_VALUES} kubelet must enable cAdvisor collection")
        # Docker exporter target stays covered by the Task 4 ServiceMonitor.
        self.assertTrue(EXPORTER_SERVICEMONITOR.is_file(),
                        f"missing {EXPORTER_SERVICEMONITOR}")
        servicemonitor = read(EXPORTER_SERVICEMONITOR)
        for marker in ("app: docker-metrics-exporter", "port: metrics",
                       "path: /metrics"):
            self.assertIn(marker, servicemonitor,
                          f"{EXPORTER_SERVICEMONITOR} must contain {marker}")

    def test_monitoring_values_pin_retention_storage_and_nodeports(self):
        """Defaults and values pin retention, local-path storage, NodePorts, and image refs."""
        self.assertTrue(MONITORING_VALUES.is_file(), f"missing {MONITORING_VALUES}")
        content = read(MONITORING_VALUES)
        mon = parse_simple_vars(MONITORING_DEFAULTS)
        self.assertEqual(mon.get("monitoring_chart_version"), "88.6.1",
                         f"{MONITORING_DEFAULTS} chart must stay 88.6.1")
        self.assertEqual(mon.get("monitoring_prometheus_retention"), "15d",
                         f"{MONITORING_DEFAULTS} retention must stay 15d")
        self.assertEqual(mon.get("monitoring_prometheus_storage_size"), "20Gi",
                         f"{MONITORING_DEFAULTS} prometheus storage must stay 20Gi")
        self.assertEqual(mon.get("monitoring_grafana_storage_size"), "5Gi",
                         f"{MONITORING_DEFAULTS} grafana storage must stay 5Gi")
        self.assertEqual(mon.get("prometheus_nodeport"), "30909",
                         f"{MONITORING_DEFAULTS} prometheus_nodeport must stay 30909")
        self.assertEqual(mon.get("grafana_nodeport"), "30300",
                         f"{MONITORING_DEFAULTS} grafana_nodeport must stay 30300")
        self.assertEqual(mon.get("monitoring_jenkins_metrics_path"), "/prometheus/",
                         f"{MONITORING_DEFAULTS} Jenkins metrics path must stay /prometheus/")
        for marker in ("monitoring_prometheus_retention",
                       "monitoring_prometheus_storage_size",
                       "monitoring_grafana_storage_size",
                       "prometheus_nodeport", "grafana_nodeport",
                       "storageClassName: local-path",
                       "storageSpec:", "volumeClaimTemplate:",
                       "persistence:", "retention:"):
            self.assertIn(marker, content,
                          f"{MONITORING_VALUES} must contain {marker}")
        self.assertGreaterEqual(content.count("local-path"), 2,
                                f"{MONITORING_VALUES} must use local-path for "
                                "Prometheus and Grafana storage")
        # Grafana admin and scrape-config references stay Secret-backed.
        self.assertIn("monitoring_grafana_admin_secret_name", content,
                      f"{MONITORING_VALUES} must reference the Grafana admin secret var")
        self.assertEqual(mon.get("monitoring_grafana_admin_secret_name"), "grafana-admin",
                         f"{MONITORING_DEFAULTS} Grafana admin secret must be grafana-admin")
        for marker in ("monitoring_additional_scrape_configs_name",
                       "monitoring_additional_scrape_configs_key"):
            self.assertIn(marker, content,
                          f"{MONITORING_VALUES} must contain {marker}")
        self.assertEqual(mon.get("monitoring_additional_scrape_configs_name"),
                         "prometheus-additional-scrape-configs",
                         f"{MONITORING_DEFAULTS} scrape Secret name mismatch")
        self.assertEqual(mon.get("monitoring_additional_scrape_configs_key"),
                         "additional-scrape-configs.yaml",
                         f"{MONITORING_DEFAULTS} scrape Secret key mismatch")
        # Every component image pin variable must feed the chart values.
        for var in ("monitoring_prometheus_image", "monitoring_grafana_image",
                    "monitoring_node_exporter_image",
                    "monitoring_kube_state_metrics_image",
                    "monitoring_alertmanager_image", "monitoring_operator_image",
                    "monitoring_config_reloader_image"):
            self.assertIn(var, content,
                          f"{MONITORING_VALUES} must set chart images from {var}")
        # Helm release identity and the stable ClusterIP contract in tasks.
        tasks = read(MONITORING_TASKS)
        for marker in ("prometheus-community/kube-prometheus-stack",
                       "monitoring_chart_version", "monitoring_release_name",
                       "monitoring_prometheus_service_name",
                       "monitoring_prometheus_service_port",
                       "operator.prometheus.io/name",
                       "monitoring_release_name }}-kube-prometheus-prometheus",
                       "targetPort: 9090"):
            self.assertIn(marker, tasks,
                          f"{MONITORING_TASKS} must contain {marker}")

    def test_monitoring_dashboard_files_have_expected_panels(self):
        """Four technical dashboards query real stack metrics; no LabMonitor content."""
        import json as _json
        for name in EXPECTED_DASHBOARDS:
            path = DASHBOARD_DIR / name
            self.assertTrue(path.is_file(), f"missing {path}")
            doc = _json.loads(read(path))
            panels = doc.get("panels", [])
            self.assertGreaterEqual(len(panels), 3,
                                    f"{path} must define at least three panels")
            for panel in panels:
                targets = panel.get("targets", [])
                self.assertTrue(targets,
                                f"{path} panel {panel.get('title')} must have targets")
                for target in targets:
                    self.assertIn("expr", target,
                                  f"{path} panel {panel.get('title')} target must query expr")
        host_exprs = dashboard_exprs(DASHBOARD_DIR / "host.json")
        for series in HOST_SERIES:
            self.assertTrue(any(series in expr for expr in host_exprs),
                            f"host.json must query {series}")
        docker_exprs = dashboard_exprs(DASHBOARD_DIR / "docker.json")
        for series in REQUIRED_EXPORTER_SERIES:
            self.assertTrue(any(series in expr for expr in docker_exprs),
                            f"docker.json must query {series}")
        kubernetes_exprs = dashboard_exprs(DASHBOARD_DIR / "kubernetes.json")
        for series in KUBERNETES_SERIES:
            self.assertTrue(any(series in expr for expr in kubernetes_exprs),
                            f"kubernetes.json must query {series}")
        jenkins_exprs = dashboard_exprs(DASHBOARD_DIR / "jenkins.json")
        for series in JENKINS_SERIES:
            self.assertTrue(any(series in expr for expr in jenkins_exprs),
                            f"jenkins.json must query {series}")
        self.assertTrue(any('up{job="jenkins"}' in expr or "up{job='jenkins'}" in expr
                            for expr in jenkins_exprs),
                        "jenkins.json must include the up{job=\"jenkins\"} scrape-health panel")
        # Technical dashboards only: no product navigation, cards, categories,
        # or LabMonitor API panels. (The docker.json PromQL legitimately
        # queries the labmonitor_docker_container_* exporter series.)
        for name in EXPECTED_DASHBOARDS:
            path = DASHBOARD_DIR / name
            content = read(path)
            for forbidden in ("labmonitor.open.url", "labmonitor.enabled",
                              "labmonitor.id", "labmonitor-api", "LABMONITOR",
                              "cards", "category"):
                self.assertNotIn(forbidden, content,
                                 f"{path} must not contain product marker {forbidden!r}")
            lowered = content.lower()
            self.assertIn("prometheus", lowered,
                          f"{path} must use the Prometheus datasource")

    def test_prometheus_scrape_config_has_no_inline_secret_values(self):
        """Scrape template uses the pinned path, host target, and Vault credential only."""
        self.assertTrue(MONITORING_SCRAPE.is_file(), f"missing {MONITORING_SCRAPE}")
        content = read(MONITORING_SCRAPE)
        for marker in ("job_name:", "metrics_path:",
                       "monitoring_jenkins_metrics_path",
                       "server_lan_ip", "compose_jenkins_port",
                       "basic_auth:", "jenkins_prometheus_user",
                       "jenkins_prometheus_api_token"):
            self.assertIn(marker, content,
                          f"{MONITORING_SCRAPE} must contain {marker}")
        mon = parse_simple_vars(MONITORING_DEFAULTS)
        self.assertEqual(mon.get("monitoring_jenkins_metrics_path"), "/prometheus/",
                         f"{MONITORING_DEFAULTS} metrics path must stay /prometheus/")
        for path in (LAB_EXAMPLE, PROD_EXAMPLE):
            example = parse_simple_vars(path)
            self.assertEqual(example.get("monitoring_jenkins_metrics_path"), "/prometheus/",
                             f"{path} must pin monitoring_jenkins_metrics_path=/prometheus/")
        # Every password line must interpolate Vault; never carry a literal.
        for raw in content.splitlines():
            line = raw.split("#", 1)[0]
            if "password" in line.lower() and ":" in line:
                self.assertIn("{{", line,
                              f"{MONITORING_SCRAPE} password must interpolate Vault — got {raw!r}")
        self.assertIsNone(re.search(r"(?m)^\s*token\s*:", content),
                          f"{MONITORING_SCRAPE} must use basic_auth, not an inline token field")
        self.assertNotIn("changeme", content.lower(),
                         f"{MONITORING_SCRAPE} must not contain placeholder secrets")
        self.assertIsNone(re.search(r"192\.168\.\d+", content),
                          f"{MONITORING_SCRAPE} must use server_lan_ip, not a LAN literal")
        # Secret creation must hide values from logs.
        tasks = read(MONITORING_TASKS)
        for marker in ("monitoring_grafana_admin_password",
                       "jenkins_prometheus_api_token",
                       "additional-scrape-configs.yaml"):
            self.assertIn(marker, tasks,
                          f"{MONITORING_TASKS} must contain {marker}")
        self.assertGreaterEqual(tasks.count("no_log: true"), 3,
                                f"{MONITORING_TASKS} must hide the Vault assert and both Secrets")

    def test_monitoring_tasks_install_and_wait_for_stack(self):
        """Role installs the pinned chart, stable Service, dashboards, then waits Ready."""
        self.assertTrue(MONITORING_TASKS.is_file(), f"missing {MONITORING_TASKS}")
        tasks = read(MONITORING_TASKS)
        for marker in ("Ensure monitoring namespace exists",
                       "prometheus-community",
                       "values_files",
                       "grafana-dashboard-",
                       "{name: host, file: host.json}",
                       "{name: docker, file: docker.json}",
                       "{name: kubernetes, file: kubernetes.json}",
                       "{name: jenkins, file: jenkins.json}",
                       "monitoring_dashboard_sidecar_label",
                       "app.kubernetes.io/name=grafana",
                       "app.kubernetes.io/name=prometheus",
                       "prometheus-node-exporter",
                       "kube-state-metrics",
                       "deployment/docker-metrics-exporter"):
            self.assertIn(marker, tasks,
                          f"{MONITORING_TASKS} must contain {marker}")
        namespace_idx = tasks.find("Ensure monitoring namespace exists")
        helm_idx = tasks.find("prometheus-community/kube-prometheus-stack")
        exporter_idx = tasks.find("docker-exporter-service.yaml")
        dashboards_idx = tasks.find("grafana-dashboard-")
        self.assertNotEqual(helm_idx, -1, f"{MONITORING_TASKS} must install the chart")
        self.assertLess(namespace_idx, helm_idx,
                        f"{MONITORING_TASKS} namespace must precede the chart install")
        self.assertLess(helm_idx, exporter_idx,
                        f"{MONITORING_TASKS} chart install must precede exporter "
                        "ServiceMonitor apply (CRD dependency)")
        self.assertLess(helm_idx, dashboards_idx,
                        f"{MONITORING_TASKS} chart install must precede dashboards")


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
