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
from collections.abc import Iterator

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
        # pre-existing Slice 2 Jenkins RW build exception (never read-only) and
        # the Task 6 Portainer Docker Agent RW admin exception (never read-only).
        for project in sorted((REPO / "compose").glob("*/compose.yaml")):
            if project == PROVIDER_COMPOSE:
                continue
            if "/var/run/docker.sock" in read(project):
                self.assertIn(project.parent.name, ("jenkins", "portainer-agent"),
                              f"{project} unexpectedly mounts the Docker socket — "
                              "only jenkins (Slice 2 RW build exception), "
                              "portainer-agent (Task 6 RW admin exception), and "
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
        # Every bare class referenced by the script must be imported; a missing
        # import aborts the script at boot (MissingPropertyException), leaving
        # Jenkins unsecured (anon 200) and the admin checkpoint failing.
        self.assertIn("hudson.model.User", content,
                      f"{PHASE1_GROOVY} uses User.getById and must import hudson.model.User")
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
        # Only the scripting-intended token API survives core upgrades: private
        # store fields (e.g. @apiTokenStore, removed in 2.568.x) abort the boot
        # script with MissingFieldException and leave users without tokens.
        self.assertNotIn("@apiTokenStore", groovy,
                         f"{PHASE2_GROOVY} must not access the removed private apiTokenStore field")
        self.assertIn("addFixedNewToken", groovy,
                      f"{PHASE2_GROOVY} must set Vault tokens via addFixedNewToken")
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

    def test_jenkins_api_tokens_use_jenkins_fixed_format(self):
        """Vault API tokens must match Jenkins addFixedNewToken format (11 + 32 lowercase hex).

        Anything else aborts the phase-two boot script with IllegalArgumentException
        and leaves provider users without tokens (401 on REST).
        """
        tasks = read(COMPOSE_TASKS)
        for var in ("jenkins_labmonitor_api_token", "jenkins_prometheus_api_token"):
            self.assertIn(f"{var} is match('^11[a-f0-9]{{32}}$')", tasks,
                          f"{COMPOSE_TASKS} must validate {var} against the Jenkins fixed-token format")

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
                         sorted(["prometheus:860.v532442b_44e9a_", "matrix-auth:3.3"]),
                         f"{JENKINS_PLUGINS} must pin exactly prometheus:860.v532442b_44e9a_ "
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
        # Debian trixie split the CLI out of docker.io (Recommends only); with
        # --no-install-recommends the image would ship no /usr/bin/docker.
        self.assertIn("docker-cli", dockerfile,
                      f"{JENKINS_DOCKERFILE} must install docker-cli explicitly for the dockersock check")
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
    def test_no_uninterpolated_jinja_dict_keys(self):
        """Task args must not use Jinja as dict keys: Ansible leaves them literal.

        Regression guard for the 422 Secret failure: data["{{ ... }}"] is not a
        valid config key. Dynamic maps must be built as Jinja expressions.
        """
        import re
        for path in (MONITORING_TASKS, PORTAINER_TASKS, LABMONITOR_TASKS,
                     COMPOSE_TASKS, FIREWALL_TASKS, K8S_PLATFORM_TASKS):
            if not path.is_file():
                continue
            for lineno, line in enumerate(read(path).splitlines(), 1):
                self.assertIsNone(
                    re.search(r'''^\s*['"]?\{\{\s*[a-z_][a-z0-9_]*.*\}\}['"]?\s*:''', line),
                    f"{path}:{lineno} must not use Jinja as a dict key — got {line.strip()}")

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
        # Helm v3 binary: the helm modules shell out to it, and v4 removed
        # `helm repo`, so the role must install the pinned v3 before use.
        self.assertEqual(mon.get("monitoring_helm_version"), "v3.21.4",
                         f"{MONITORING_DEFAULTS} Helm must stay pinned v3.21.4")
        self.assertIn("get.helm.sh", mon.get("monitoring_helm_download_url", ""),
                      f"{MONITORING_DEFAULTS} Helm must download from get.helm.sh "
                      f"(GitHub v3.21.4 release has no tarball asset)")
        self.assertRegex(mon.get("monitoring_helm_tarball_sha256", ""),
                         r"^[0-9a-f]{64}$",
                         f"{MONITORING_DEFAULTS} Helm tarball checksum must be pinned")
        tasks = read(MONITORING_TASKS)
        self.assertIn("monitoring_helm_download_url", tasks,
                      f"{MONITORING_TASKS} must download Helm from the pinned URL")
        self.assertIn("helm version --short", tasks,
                      f"{MONITORING_TASKS} must assert the installed Helm version")
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


PORTAINER_SERVER_TEMPLATE = REPO / "ansible/roles/portainer/templates/server.yaml.j2"
PORTAINER_AGENT_TEMPLATE = REPO / "ansible/roles/portainer/templates/kubernetes-agent.yaml.j2"
PORTAINER_AGENT_ENV_TEMPLATE = REPO / "ansible/roles/portainer/templates/portainer-agent.env.j2"
PORTAINER_AGENT_COMPOSE = REPO / "compose/portainer-agent/compose.yaml"
PORTAINER_AGENT_ENV_EXAMPLE = REPO / "compose/portainer-agent/.env.example"
FIREWALL_DEFAULTS = REPO / "ansible/roles/firewall/defaults/main.yml"
FIREWALL_TASKS = REPO / "ansible/roles/firewall/tasks/main.yml"
FIREWALL_DOCKER_USER_TEMPLATE = REPO / "ansible/roles/firewall/templates/home-server-docker-user.sh.j2"
LABMONITOR_RBAC = REPO / "k8s/labmonitor/rbac.yaml"
LABMONITOR_PROVIDER_TEMPLATE = REPO / "ansible/roles/labmonitor-foundation/templates/provider-config.yaml.j2"
LABMONITOR_CATALOG_TEMPLATE = REPO / "ansible/roles/labmonitor-foundation/templates/catalog.yaml.j2"
LABMONITOR_JENKINS_SECRET_TEMPLATE = REPO / "ansible/roles/labmonitor-foundation/templates/jenkins-secret.yaml.j2"
K8S_PLATFORM_TASKS = REPO / "ansible/roles/k8s-platform/tasks/main.yml"
MONITORING_EXPORTER_DEPLOYMENT_TEMPLATE = REPO / "ansible/roles/monitoring/templates/docker-exporter-deployment.yaml.j2"


def top_level_block(content: str, key: str) -> str:
    """Return the lines under a top-level `key:` mapping (stdlib fallback for PyYAML)."""
    lines = content.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(key + ":"))
    block: list = []
    for line in lines[start + 1:]:
        if line.strip() == "" or line.startswith("#"):
            block.append(line)
            continue
        if not line[0].isspace():
            break
        block.append(line)
    return "\n".join(block)


class TestSlice3Task6Portainer(unittest.TestCase):
    def test_portainer_resources_use_portainer_namespace(self):
        """Server and Kubernetes Agent manifests live in the portainer namespace."""
        for path in (PORTAINER_SERVER_TEMPLATE, PORTAINER_AGENT_TEMPLATE):
            self.assertTrue(path.is_file(), f"missing {path}")
            content = read(path)
            self.assertIn('namespace: "{{ portainer_namespace }}"', content,
                          f"{path} must scope namespaced resources to "
                          "'{{ portainer_namespace }}'")
            for other in ("kube-system", "monitoring", "labmonitor", "default",
                          "kube-public"):
                self.assertNotIn(f"namespace: {other}", content,
                                 f"{path} must not place resources in {other}")
                self.assertNotIn(f'namespace: "{other}"', content,
                                 f"{path} must not place resources in {other}")
        defaults = parse_simple_vars(PORTAINER_DEFAULTS)
        self.assertEqual(defaults.get("portainer_namespace"), "portainer",
                         f"{PORTAINER_DEFAULTS} portainer_namespace must be portainer")
        tasks = read(PORTAINER_TASKS)
        self.assertIn("portainer_namespace", tasks,
                      f"{PORTAINER_TASKS} must reference portainer_namespace")
        # Service discovery metadata rides on the Server Service only.
        server = read(PORTAINER_SERVER_TEMPLATE)
        for marker in ('labmonitor.enabled: "true"',
                       'labmonitor.id: "portainer"',
                       'labmonitor.category: "administration"',
                       'labmonitor.icon: "portainer"',
                       'labmonitor.name: "Portainer"',
                       'labmonitor.open.url: "https://portainer.{{ base_domain }}"'):
            self.assertIn(marker, server,
                          f"{PORTAINER_SERVER_TEMPLATE} must carry metadata {marker}")

    def test_labmonitor_service_account_is_not_reused_by_portainer(self):
        """No Portainer file may reference labmonitor-api; agents use dedicated identities."""
        for path in (PORTAINER_SERVER_TEMPLATE, PORTAINER_AGENT_TEMPLATE,
                     PORTAINER_TASKS, PORTAINER_DEFAULTS,
                     PORTAINER_AGENT_ENV_TEMPLATE,
                     PORTAINER_AGENT_COMPOSE, PORTAINER_AGENT_ENV_EXAMPLE):
            self.assertTrue(path.is_file(), f"missing {path}")
            self.assertNotIn("labmonitor-api", read(path),
                             f"{path} must never reuse the labmonitor-api ServiceAccount")
        server = read(PORTAINER_SERVER_TEMPLATE)
        self.assertIn("kind: ServiceAccount", server,
                      f"{PORTAINER_SERVER_TEMPLATE} must define a dedicated ServiceAccount")
        self.assertIn("serviceAccountName:", server,
                      f"{PORTAINER_SERVER_TEMPLATE} must run under its own ServiceAccount")
        agent = read(PORTAINER_AGENT_TEMPLATE)
        self.assertIn("kind: ServiceAccount", agent,
                      f"{PORTAINER_AGENT_TEMPLATE} must define a dedicated Agent ServiceAccount")
        self.assertIn("kind: ClusterRoleBinding", agent,
                      f"{PORTAINER_AGENT_TEMPLATE} must bind its own ClusterRole")
        idx = agent.find("kind: ClusterRoleBinding")
        window = agent[idx:idx + 2000]
        self.assertIn("portainer_k8s_agent_service_name", window,
                      f"{PORTAINER_AGENT_TEMPLATE} ClusterRoleBinding must bind "
                      "the dedicated Agent ServiceAccount")
        # The shared agent credential is a dedicated Secret from Vault, never printed.
        for marker in ("secretKeyRef", "portainer_agent_secret_name"):
            self.assertIn(marker, server,
                          f"{PORTAINER_SERVER_TEMPLATE} must consume {marker}")
            self.assertIn(marker, agent,
                          f"{PORTAINER_AGENT_TEMPLATE} must consume {marker}")
        tasks = read(PORTAINER_TASKS)
        self.assertIn("portainer_agent_secret", tasks,
                      f"{PORTAINER_TASKS} must validate the Vault agent secret")
        self.assertIn("no_log: true", tasks,
                      f"{PORTAINER_TASKS} must never print the agent secret")

    def test_portainer_agent_headless_service_publishes_unready_addresses(self):
        """Agent peer discovery cannot wait for the agent readiness gate."""
        agent = read(PORTAINER_AGENT_TEMPLATE)
        headless_index = agent.index("name: s-portainer-agent-headless")
        headless_service = agent[headless_index:headless_index + 800]
        self.assertIn("clusterIP: None", headless_service,
                      f"{PORTAINER_AGENT_TEMPLATE} must define a headless agent Service")
        self.assertIn("publishNotReadyAddresses: true", headless_service,
                      f"{PORTAINER_AGENT_TEMPLATE} must publish unready endpoints so "
                      "agents can resolve their peer-discovery Service before readiness")

    def test_portainer_docker_agent_is_the_only_new_admin_socket_mount(self):
        """Host Docker Agent is the only new RW socket mount, bound to 9001 via Vault secret."""
        self.assertTrue(PORTAINER_AGENT_COMPOSE.is_file(), f"missing {PORTAINER_AGENT_COMPOSE}")
        services = parse_compose_services(PORTAINER_AGENT_COMPOSE)
        self.assertIn("portainer-agent", services,
                      f"{PORTAINER_AGENT_COMPOSE} must define service portainer-agent "
                      f"— got {sorted(services)}")
        svc = services["portainer-agent"]
        mounts = [v for v in svc["volumes"] if "/var/run/docker.sock" in v]
        self.assertEqual(len(mounts), 1,
                         f"{PORTAINER_AGENT_COMPOSE} must mount the socket exactly once "
                         f"— got {svc['volumes']}")
        self.assertTrue(mounts[0].startswith("/var/run/docker.sock:/var/run/docker.sock"),
                        f"{PORTAINER_AGENT_COMPOSE} socket source must be "
                        f"/var/run/docker.sock — got {mounts[0]}")
        self.assertFalse(mounts[0].endswith(":ro"),
                         f"{PORTAINER_AGENT_COMPOSE} is the explicit admin exception: "
                         f"RW mount, never :ro — got {mounts[0]}")
        self.assertEqual(svc["environment"].get("AGENT_SECRET"), "${AGENT_SECRET:?required}",
                         f"{PORTAINER_AGENT_COMPOSE} AGENT_SECRET must come from Vault "
                         f"— got {svc['environment']}")
        content = read(PORTAINER_AGENT_COMPOSE)
        self.assertNotIn("DOCKER_SOCKET_PROXY", content,
                         f"{PORTAINER_AGENT_COMPOSE} must have no relation to "
                         "docker-socket-proxy credentials")
        self.assertNotIn("labmonitor.open.url", content,
                         f"{PORTAINER_AGENT_COMPOSE} is a provider, not an app card")
        ports = svc["ports"]
        self.assertEqual(len(ports), 1,
                         f"{PORTAINER_AGENT_COMPOSE} must publish exactly one port "
                         f"— got {ports}")
        m = re.search(r":(\d+):(\d+)\s*$", ports[0])
        self.assertIsNotNone(m,
                              f"{PORTAINER_AGENT_COMPOSE} port entry must be "
                              f"host:container — got {ports[0]}")
        host, container = m.groups() if m is not None else ("", "")
        self.assertEqual(host, "9001",
                         f"{PORTAINER_AGENT_COMPOSE} host port must be 9001 — got {ports[0]}")
        self.assertEqual(container, "9001",
                         f"{PORTAINER_AGENT_COMPOSE} container port must be 9001 — got {ports[0]}")
        self.assertIn("PORTAINER_AGENT_BIND_IP", ports[0],
                      f"{PORTAINER_AGENT_COMPOSE} port entry must bind via "
                      f"PORTAINER_AGENT_BIND_IP (server_lan_ip only) — got {ports[0]}")
        # Kubernetes manifests never touch the socket; only the host agent does.
        for path in (PORTAINER_SERVER_TEMPLATE, PORTAINER_AGENT_TEMPLATE):
            self.assertNotIn("docker.sock", read(path),
                             f"{path} must never mount the Docker socket")
        # Repo-wide: exactly the two pre-existing mounts plus the new admin agent.
        mounters = sorted(p.parent.name for p in (REPO / "compose").glob("*/compose.yaml")
                          if "/var/run/docker.sock" in read(p))
        self.assertEqual(mounters, ["docker-provider", "jenkins", "portainer-agent"],
                         "socket mounts are limited to docker-provider (:ro), "
                         f"jenkins (Slice 2 RW), portainer-agent (admin RW) — got {mounters}")

    def test_portainer_uses_fixed_nodeport_30900(self):
        """Server stays on NodePort 30900 for LAN/VPN; agent port 9001 stays pod-only."""
        self.assertEqual(parse_simple_vars(PORTAINER_DEFAULTS).get("portainer_nodeport"),
                         "30900",
                         f"{PORTAINER_DEFAULTS} portainer_nodeport must be 30900")
        server = read(PORTAINER_SERVER_TEMPLATE)
        self.assertIn("type: NodePort", server,
                      f"{PORTAINER_SERVER_TEMPLATE} Server Service must be NodePort")
        self.assertIn("nodePort: {{ portainer_nodeport | int }}", server,
                      f"{PORTAINER_SERVER_TEMPLATE} must render nodePort as native int")
        self.assertIn("port: {{ portainer_service_port | int }}", server,
                      f"{PORTAINER_SERVER_TEMPLATE} must render port as native int")
        self.assertNotIn('port: "{{ portainer_service_port }}"', server,
                         f"{PORTAINER_SERVER_TEMPLATE} must not quote Service port as string")
        self.assertNotIn('nodePort: "{{ portainer_nodeport }}"', server,
                         f"{PORTAINER_SERVER_TEMPLATE} must not quote nodePort as string")
        self.assertNotIn("30900", server,
                         f"{PORTAINER_SERVER_TEMPLATE} must use the variable, not a literal")
        agent = read(PORTAINER_AGENT_TEMPLATE)
        self.assertIn("type: ClusterIP", agent,
                      f"{PORTAINER_AGENT_TEMPLATE} Agent Service must stay ClusterIP")
        self.assertNotIn("nodePort", agent,
                         f"{PORTAINER_AGENT_TEMPLATE} must not expose a NodePort")
        self.assertIn("port: {{ portainer_agent_port | int }}", agent,
                      f"{PORTAINER_AGENT_TEMPLATE} must render port as native int")
        self.assertNotIn('port: "{{ portainer_agent_port }}"', agent,
                         f"{PORTAINER_AGENT_TEMPLATE} must not quote Service port as string")
        fw_defaults = read(FIREWALL_DEFAULTS)
        allowlist = top_level_block(fw_defaults, "firewall_nodeport_allowlist")
        for nodeport in ("30900", "30300", "30909"):
            self.assertIn(nodeport, allowlist,
                          f"{FIREWALL_DEFAULTS} NodePort allowlist must contain {nodeport}")
        self.assertNotIn("12375", allowlist,
                         f"{FIREWALL_DEFAULTS} NodePort allowlist must never contain 12375")
        backhaul = top_level_block(fw_defaults, "firewall_portainer_agent_backhaul_ports")
        self.assertIn("9001", backhaul,
                      f"{FIREWALL_DEFAULTS} agent backhaul must cover 9001")
        self.assertNotIn("12375", read(FIREWALL_TASKS),
                         f"{FIREWALL_TASKS} must not add a literal 12375 rule")
        fw_tasks = read(FIREWALL_TASKS)
        self.assertGreaterEqual(fw_tasks.count("firewall_portainer_agent_backhaul_ports"), 2,
                                f"{FIREWALL_TASKS} must loop the agent backhaul var for "
                                "both the pod-CIDR allow and the LAN/VPN deny")
        self.assertGreaterEqual(fw_tasks.count("rule: deny"), 2,
                                f"{FIREWALL_TASKS} must deny LAN/VPN to the agent port")
        self.assertIn("firewall_nodeport_allowlist", fw_tasks,
                      f"{FIREWALL_TASKS} must open the NodePort allowlist to LAN/VPN")
        docker_user = read(FIREWALL_DOCKER_USER_TEMPLATE)
        self.assertIn("firewall_portainer_agent_backhaul_ports", docker_user,
                      f"{FIREWALL_DOCKER_USER_TEMPLATE} must filter the published "
                      "agent port (Docker bypasses UFW)")


def split_yaml_docs(text: str) -> list:
    """Split a multi-document YAML file on `---` separator lines (stdlib only)."""
    docs: list = []
    current: list = []
    for line in text.splitlines():
        if line.strip() == "---":
            if any(part.strip() for part in current):
                docs.append("\n".join(current))
            current = []
        else:
            current.append(line)
    if any(part.strip() for part in current):
        docs.append("\n".join(current))
    return [doc for doc in docs if re.search(r"^kind:\s*\S+", doc, re.M)]


def parse_flow_list(value: str) -> list:
    """Parse a YAML flow list like `["a", "b"]` into Python strings."""
    value = value.strip()
    assert value.startswith("[") and value.endswith("]"), f"not a flow list: {value}"
    inner = value[1:-1].strip()
    if not inner:
        return []
    return [part.strip().strip("'\"") for part in inner.split(",")]


def parse_k8s_rules(doc: str) -> list:
    """Parse a top-level `rules:` block into a list of dicts.

    Supports flow lists (`key: ["a"]`) and block lists (`key:` + `- item`).
    RBAC manifests in this repo keep `rules:` at column 0 with 2-space indents.
    """
    lines = doc.splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(r"^rules:\s*$", line))
    rules: list = []
    current: dict | None = None
    pending_key: str | None = None

    def set_key(target: dict, key: str, val: str) -> str | None:
        if val == "":
            target[key] = []
            return key
        if val.startswith("["):
            target[key] = parse_flow_list(val)
            return None
        target[key] = val.strip("'\"")
        return None

    for line in lines[start + 1:]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            item = stripped[2:]
            if indent == 2 and ":" in item:
                current = {}
                rules.append(current)
                pending_key = None
                key, val = item.split(":", 1)
                pending_key = set_key(current, key.strip(), val.strip())
            elif pending_key is not None and current is not None:
                current[pending_key].append(item.strip().strip("'\""))
            else:
                break
        elif ":" in stripped and current is not None:
            key, val = stripped.split(":", 1)
            pending_key = set_key(current, key.strip(), val.strip())
        else:
            break
    return rules


def normalized_rules(rules: list) -> list:
    """Sort every list value so rule comparison is order-insensitive."""
    normalized = []
    for rule in rules:
        normalized.append({key: sorted(val) if isinstance(val, list) else val
                           for key, val in rule.items()})
    return sorted(normalized, key=repr)


class TestSlice3Task7Labmonitor(unittest.TestCase):
    def test_labmonitor_rbac_has_only_required_read_verbs(self):
        """labmonitor RBAC grants get/list/watch only on nodes/pods/services/namespaces/deployments."""
        self.assertTrue(LABMONITOR_RBAC.is_file(), f"missing {LABMONITOR_RBAC}")
        docs = split_yaml_docs(read(LABMONITOR_RBAC))

        def doc_kind(doc: str) -> str:
            match = re.search(r"^kind:\s*(\S+)", doc, re.M)
            self.assertIsNotNone(match, f"{LABMONITOR_RBAC} doc must declare a kind")
            assert match is not None
            return match.group(1)

        kinds = sorted(doc_kind(doc) for doc in docs)
        self.assertEqual(kinds, ["ClusterRole", "ClusterRoleBinding", "Namespace",
                                "Role", "RoleBinding", "ServiceAccount"],
                         f"{LABMONITOR_RBAC} must hold exactly the six foundation resources — got {kinds}")

        def single(kind: str) -> str:
            matches = [doc for doc in docs
                       if re.search(rf"^kind:\s*{kind}\s*$", doc, re.M)]
            self.assertEqual(len(matches), 1,
                             f"{LABMONITOR_RBAC} must hold exactly one {kind} — got {len(matches)}")
            return matches[0]

        namespace = single("Namespace")
        self.assertIn("name: labmonitor", namespace,
                      f"{LABMONITOR_RBAC} Namespace must be labmonitor")
        account = single("ServiceAccount")
        self.assertIn("name: labmonitor-api", account,
                      f"{LABMONITOR_RBAC} ServiceAccount must be labmonitor-api")
        self.assertIn("namespace: labmonitor", account,
                      f"{LABMONITOR_RBAC} ServiceAccount must live in labmonitor")
        cluster_role = single("ClusterRole")
        self.assertIn("name: labmonitor-reader", cluster_role,
                      f"{LABMONITOR_RBAC} ClusterRole must be labmonitor-reader")
        self.assertEqual(
            normalized_rules(parse_k8s_rules(cluster_role)),
            normalized_rules([
                {"apiGroups": [""], "resources": ["nodes", "pods", "services", "namespaces"],
                 "verbs": ["get", "list", "watch"]},
                {"apiGroups": ["apps"], "resources": ["deployments"],
                 "verbs": ["get", "list", "watch"]},
            ]),
            f"{LABMONITOR_RBAC} ClusterRole must grant get/list/watch only on "
            "nodes/pods/services/namespaces + apps/deployments",
        )
        role = single("Role")
        self.assertIn("namespace: labmonitor", role,
                      f"{LABMONITOR_RBAC} Role must live in labmonitor")
        self.assertEqual(
            normalized_rules(parse_k8s_rules(role)),
            normalized_rules([
                {"apiGroups": [""], "resources": ["configmaps"],
                 "resourceNames": ["labmonitor-catalog", "labmonitor-provider-config"],
                 "verbs": ["get"]},
            ]),
            f"{LABMONITOR_RBAC} Role must allow get only on the two named ConfigMaps",
        )
        for kind, ref_kind, ref_name in (("ClusterRoleBinding", "ClusterRole", "labmonitor-reader"),
                                        ("RoleBinding", "Role", "labmonitor-config-reader")):
            binding = single(kind)
            subjects = re.findall(r"-\s*kind:\s*(\S+)\s*\n\s*name:\s*(\S+)\s*\n\s*namespace:\s*(\S+)",
                                  binding)
            self.assertEqual(subjects, [("ServiceAccount", "labmonitor-api", "labmonitor")],
                             f"{LABMONITOR_RBAC} {kind} must bind only "
                             "system:serviceaccount:labmonitor:labmonitor-api — got {subjects}")
            self.assertIn(f"kind: {ref_kind}", binding,
                          f"{LABMONITOR_RBAC} {kind} must reference {ref_kind}")
            self.assertIn(f"name: {ref_name}", binding,
                          f"{LABMONITOR_RBAC} {kind} must reference {ref_name}")
        # No token Secret: the future Deployment uses a projected token.
        self.assertNotIn("kind: Secret", read(LABMONITOR_RBAC),
                         f"{LABMONITOR_RBAC} must not create a token Secret")

    def test_labmonitor_rbac_has_no_secret_permissions(self):
        """No Secret/event/workload-write/cluster-admin grant anywhere in the LabMonitor foundation."""
        self.assertTrue(LABMONITOR_RBAC.is_file(), f"missing {LABMONITOR_RBAC}")
        rbac = read(LABMONITOR_RBAC)
        lowered = rbac.lower()
        for forbidden in ("secret", "cluster-admin", "events", "daemonsets",
                          "statefulsets", "persistentvolumes"):
            self.assertNotIn(forbidden, lowered,
                             f"{LABMONITOR_RBAC} must not mention {forbidden}")
        for verb in ('"create"', '"delete"', '"update"', '"patch"',
                     '"deletecollection"', '"*"'):
            self.assertNotIn(verb, rbac,
                             f"{LABMONITOR_RBAC} must not grant write verb {verb}")
        self.assertNotIn("token", lowered,
                         f"{LABMONITOR_RBAC} must not create or reference a token")
        # The Jenkins Secret carries only the Vault username + api-token, never a password.
        self.assertTrue(LABMONITOR_JENKINS_SECRET_TEMPLATE.is_file(),
                        f"missing {LABMONITOR_JENKINS_SECRET_TEMPLATE}")
        secret_template = read(LABMONITOR_JENKINS_SECRET_TEMPLATE)
        self.assertIn("kind: Secret", secret_template,
                      f"{LABMONITOR_JENKINS_SECRET_TEMPLATE} must render a Secret")
        self.assertIn("labmonitor_jenkins_secret_name", secret_template,
                      f"{LABMONITOR_JENKINS_SECRET_TEMPLATE} must use the role secret-name var")
        self.assertIn('"{{ jenkins_labmonitor_user }}"', secret_template,
                      f"{LABMONITOR_JENKINS_SECRET_TEMPLATE} must take username from Vault")
        self.assertIn('"{{ jenkins_labmonitor_api_token }}"', secret_template,
                      f"{LABMONITOR_JENKINS_SECRET_TEMPLATE} must take api-token from Vault")
        string_data = secret_template.split("stringData:", 1)[1]
        keys = re.findall(r"^\s{2}(\S+):", string_data, re.M)
        self.assertEqual(sorted(keys), ["api-token", "username"],
                         f"{LABMONITOR_JENKINS_SECRET_TEMPLATE} must carry exactly "
                         f"username + api-token — got {keys}")
        for path in (LABMONITOR_JENKINS_SECRET_TEMPLATE, LABMONITOR_PROVIDER_TEMPLATE,
                     LABMONITOR_CATALOG_TEMPLATE, LABMONITOR_TASKS):
            self.assertNotIn("password", read(path).lower(),
                             f"{path} must never mention a password")
        tasks = read(LABMONITOR_TASKS)
        self.assertIn("jenkins_labmonitor_api_token", tasks,
                      f"{LABMONITOR_TASKS} must validate the Vault api token")
        self.assertIn("no_log: true", tasks,
                      f"{LABMONITOR_TASKS} must never print Vault values")

    def test_provider_config_contains_internal_endpoints_only(self):
        """Provider ConfigMap exposes only internal endpoints with the single environment IP."""
        self.assertTrue(LABMONITOR_PROVIDER_TEMPLATE.is_file(),
                        f"missing {LABMONITOR_PROVIDER_TEMPLATE}")
        template = read(LABMONITOR_PROVIDER_TEMPLATE)
        for marker in ("schema: labmonitor.providers/v1",
                       "base_url: http://prometheus.monitoring.svc.cluster.local:9090",
                       "base_url: http://{{ server_lan_ip }}:12375",
                       "base_url: http://{{ server_lan_ip }}:18080",
                       "mode: in_cluster"):
            self.assertIn(marker, template,
                          f"{LABMONITOR_PROVIDER_TEMPLATE} must contain {marker}")
        providers = re.findall(r"^  ([a-z]+):\s*$", template, re.M)
        self.assertEqual(sorted(providers), ["docker", "jenkins", "kubernetes", "prometheus"],
                         f"{LABMONITOR_PROVIDER_TEMPLATE} must define exactly the four "
                         f"providers — got {providers}")
        jinja_vars = set(re.findall(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\b", template))
        self.assertEqual(jinja_vars, {"server_lan_ip"},
                         f"{LABMONITOR_PROVIDER_TEMPLATE} must vary only on server_lan_ip "
                         f"— got {jinja_vars}")
        for forbidden in ("password", "token", "secret", "credential", "nodeport",
                          "ingress", "https://", "192.168.", "192.0.2.",
                          "lab.arpa", "home.arpa"):
            self.assertNotIn(forbidden, template.lower(),
                             f"{LABMONITOR_PROVIDER_TEMPLATE} must not contain {forbidden}")
        tasks = read(LABMONITOR_TASKS)
        self.assertIn("labmonitor_provider_config_name", tasks,
                      f"{LABMONITOR_TASKS} must apply the provider ConfigMap by role var")
        self.assertIn("provider-config.yaml.j2", tasks,
                      f"{LABMONITOR_TASKS} must render {LABMONITOR_PROVIDER_TEMPLATE.name}")
        self.assertNotIn("NodePort", tasks,
                         f"{LABMONITOR_TASKS} must not expose a provider NodePort")
        self.assertNotIn("kind: Ingress", tasks,
                         f"{LABMONITOR_TASKS} must not expose a provider Ingress")

    def test_catalog_contains_cockpit_only_for_host_native_services(self):
        """Catalog holds exactly the initial Cockpit entry; providers stay out of navigation."""
        self.assertTrue(LABMONITOR_CATALOG_TEMPLATE.is_file(),
                        f"missing {LABMONITOR_CATALOG_TEMPLATE}")
        template = read(LABMONITOR_CATALOG_TEMPLATE)
        for marker in ("schema: labmonitor.services/v1",
                       "- id: cockpit",
                       "enabled: true",
                       "name: Cockpit",
                       "category: administration",
                       "icon: cockpit",
                       "open_url: https://cockpit.{{ base_domain }}",
                       "runtime: host"):
            self.assertIn(marker, template,
                          f"{LABMONITOR_CATALOG_TEMPLATE} must contain {marker}")
        ids = re.findall(r"^  - id:\s*(\S+)\s*$", template, re.M)
        self.assertEqual(ids, ["cockpit"],
                         f"{LABMONITOR_CATALOG_TEMPLATE} must list exactly cockpit — got {ids}")
        for forbidden in ("postgres", "proxy", "exporter", "agent", "prometheus",
                          "grafana", "portainer", "jenkins", "n8n", "metabase"):
            self.assertNotIn(forbidden, template.lower(),
                             f"{LABMONITOR_CATALOG_TEMPLATE} must not list {forbidden}")
        jinja_vars = set(re.findall(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\b", template))
        self.assertEqual(jinja_vars, {"base_domain"},
                         f"{LABMONITOR_CATALOG_TEMPLATE} must vary only on base_domain "
                         f"— got {jinja_vars}")
        tasks = read(LABMONITOR_TASKS)
        self.assertIn("labmonitor_catalog_name", tasks,
                      f"{LABMONITOR_TASKS} must apply the catalog ConfigMap by role var")
        self.assertIn("catalog.yaml.j2", tasks,
                      f"{LABMONITOR_TASKS} must render {LABMONITOR_CATALOG_TEMPLATE.name}")

    def test_catalog_and_kubernetes_services_use_one_environment_domain(self):
        """Catalog + Grafana/Prometheus/Portainer Services share the selected base_domain."""
        for path in (LABMONITOR_CATALOG_TEMPLATE, MONITORING_TASKS,
                     PORTAINER_SERVER_TEMPLATE):
            self.assertTrue(path.is_file(), f"missing {path}")
        monitoring = read(MONITORING_TASKS)
        portainer = read(PORTAINER_SERVER_TEMPLATE)
        catalog = read(LABMONITOR_CATALOG_TEMPLATE)
        for text, marker in (
            (catalog, "open_url: https://cockpit.{{ base_domain }}"),
            (monitoring, 'labmonitor.id: "grafana"'),
            (monitoring, "labmonitor.open.url: \"https://grafana.{{ base_domain }}\""),
            (monitoring, 'labmonitor.id: "prometheus"'),
            (monitoring, "labmonitor.open.url: \"https://prometheus.{{ base_domain }}\""),
            (portainer, 'labmonitor.id: "portainer"'),
            (portainer, 'labmonitor.open.url: "https://portainer.{{ base_domain }}"'),
        ):
            self.assertIn(marker, text, f"discovery contract must contain {marker}")
        for text, expected_id, expected_category in (
            (monitoring, "grafana", "observability"),
            (monitoring, "prometheus", "observability"),
            (portainer, "portainer", "administration"),
        ):
            self.assertIn(f'labmonitor.id: "{expected_id}"', text,
                          f"Service metadata must pin id {expected_id}")
            self.assertIn(f'labmonitor.category: "{expected_category}"', text,
                          f"Service {expected_id} must use category {expected_category}")
            self.assertIn(f'labmonitor.icon: "{expected_id}"', text,
                          f"Service {expected_id} must use icon {expected_id}")
            self.assertIn('labmonitor.enabled: "true"', text,
                          f"Service {expected_id} must set labmonitor.enabled")
        for path in (LABMONITOR_CATALOG_TEMPLATE, LABMONITOR_PROVIDER_TEMPLATE,
                     LABMONITOR_RBAC, MONITORING_TASKS, PORTAINER_SERVER_TEMPLATE):
            content = read(path)
            for forbidden in ("lab.arpa", "home.arpa", "192.168.", "192.0.2."):
                self.assertNotIn(forbidden, content,
                                 f"{path} must use {{{{ base_domain }}}}, not literal {forbidden}")
        # Discovery metadata rides on the Service only, never on a Deployment.
        self.assertNotIn("kind: Deployment", monitoring,
                         f"{MONITORING_TASKS} must not define a Deployment discovery source")
        self.assertNotIn("labmonitor.", read(MONITORING_EXPORTER_DEPLOYMENT_TEMPLATE),
                         f"{MONITORING_EXPORTER_DEPLOYMENT_TEMPLATE} must not carry discovery metadata")
        service_docs = [doc for doc in split_yaml_docs(portainer) if "labmonitor." in doc]
        self.assertEqual(len(service_docs), 1,
                         f"{PORTAINER_SERVER_TEMPLATE} must carry discovery metadata "
                         "on exactly one document")
        self.assertIn("kind: Service", service_docs[0],
                      f"{PORTAINER_SERVER_TEMPLATE} discovery metadata must sit on the Service")
        platform_tasks = read(K8S_PLATFORM_TASKS)
        for marker in ("monitoring_namespace", "portainer_namespace", "labmonitor"):
            self.assertIn(marker, platform_tasks,
                          f"{K8S_PLATFORM_TASKS} must gate the discovery contract ({marker})")


PLATFORM_INGRESS_TEMPLATE = REPO / "ansible/roles/k8s-platform/templates/platform-ingress.yaml.j2"
PLATFORM_DEFAULTS = REPO / "ansible/roles/k8s-platform/defaults/main.yml"
TRAEFIK_HELMCHART_TEMPLATE = REPO / "ansible/roles/k8s-platform/templates/traefik-helmchartconfig.yaml.j2"
HOSTS_GENERATOR = REPO / "scripts/hosts/generate-hosts.sh"
LAB_HOSTS_EXAMPLE = REPO / "scripts/hosts/lab.hosts.example"
PROD_HOSTS_EXAMPLE = REPO / "scripts/hosts/prod.hosts.example"
ROOT_README = REPO / "README.md"
K8S_README = REPO / "k8s/README.md"
INGRESS_README = REPO / "k8s/ingress/README.md"

# Final navigable services (Task 8): the legacy dashboard is gone, so the
# helper and examples emit exactly these seven names.
EXPECTED_ACTIVE_SERVICES = (
    "cockpit",
    "grafana",
    "jenkins",
    "metabase",
    "n8n",
    "portainer",
    "prometheus",
)

# Human HTTPS routes: Compose/Cockpit stay on the Traefik file provider,
# Kubernetes apps use Ingress-to-Service routing.
FILE_PROVIDER_SERVICES = ("cockpit", "jenkins", "n8n", "metabase")
INGRESS_SERVICES = {
    "grafana": ("monitoring_namespace", "monitoring_grafana_service_name",
                "monitoring_grafana_service_port"),
    "prometheus": ("monitoring_namespace", "monitoring_prometheus_service_name",
                   "monitoring_prometheus_service_port"),
    "portainer": ("portainer_namespace", "portainer_service_name",
                  "portainer_service_port"),
}


def hosts_example_services(path: pathlib.Path) -> list:
    """Parse `<ip> <service>.<domain>` lines into service names."""
    services: list = []
    for raw in read(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        self_host = parts[-1]
        self_service = self_host.split(".")[0]
        services.append(self_service)
    return services


def iter_active_files() -> Iterator[pathlib.Path]:
    """Yield every active-tree text file (ansible/compose/k8s/scripts + READMEs).

    Excludes tests/ (assertions legitimately name legacy concepts), the
    vendored xanmanning.k3s role, and ignored history (docs/, old/).
    """
    roots = [REPO / "ansible", REPO / "compose", REPO / "k8s", REPO / "scripts"]
    skip_dirs = {"__pycache__", "xanmanning.k3s"}
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in skip_dirs for part in path.parts):
                continue
            yield path
    for path in (ROOT_README, K8S_README, INGRESS_README):
        if path.is_file():
            yield path


class TestSlice3Task8FinalRoutes(unittest.TestCase):
    def test_hosts_generator_lists_only_active_services(self):
        """Helper and examples emit exactly the seven active services, no legacy."""
        self.assertTrue(HOSTS_GENERATOR.is_file(), f"missing {HOSTS_GENERATOR}")
        helper = read(HOSTS_GENERATOR)
        m = re.search(r"^for service in (.+?); do\s*$", helper, re.M)
        self.assertIsNotNone(m,
                             f"{HOSTS_GENERATOR} must iterate a fixed service list")
        assert m is not None
        helper_services = m.group(1).split()
        self.assertEqual(sorted(helper_services), sorted(EXPECTED_ACTIVE_SERVICES),
                         f"{HOSTS_GENERATOR} must list exactly "
                         f"{sorted(EXPECTED_ACTIVE_SERVICES)} — got {sorted(helper_services)}")
        self.assertNotIn("glance", helper,
                         f"{HOSTS_GENERATOR} must not list the legacy dashboard")
        for path, domain in ((LAB_HOSTS_EXAMPLE, "lab.arpa"),
                             (PROD_HOSTS_EXAMPLE, "home.arpa")):
            self.assertTrue(path.is_file(), f"missing {path}")
            services = hosts_example_services(path)
            self.assertEqual(len(services), 7,
                             f"{path} must hold exactly seven lines — got {services}")
            self.assertEqual(sorted(services), sorted(EXPECTED_ACTIVE_SERVICES),
                             f"{path} must list exactly "
                             f"{sorted(EXPECTED_ACTIVE_SERVICES)} — got {sorted(services)}")
            for raw in read(path).splitlines():
                if raw.strip():
                    self.assertIn(domain, raw,
                                  f"{path} line must use domain {domain} — got {raw!r}")

    def test_no_active_glance_or_builds_api_runtime_reference(self):
        """No active Ansible/Compose/K8s/script/README path loads legacy concepts."""
        legacy_res = (
            re.compile(r"glance", re.IGNORECASE),
            re.compile(r"builds[-_]?api", re.IGNORECASE),
            re.compile(r"slice\s*[-_]?4", re.IGNORECASE),
        )
        offenders: list = []
        scanned = 0
        for path in iter_active_files():
            try:
                content = read(path)
            except (UnicodeDecodeError, OSError):
                continue
            scanned += 1
            for rx in legacy_res:
                if rx.search(content):
                    offenders.append(f"{path.relative_to(REPO)} matches {rx.pattern}")
        self.assertGreater(scanned, 0, "active-tree scan must cover real files")
        self.assertEqual(offenders, [],
                         "active tree must not reference legacy runtime concepts — "
                         f"got {offenders}")

    def test_ingress_routes_only_human_interfaces(self):
        """File provider + Ingress cover exactly the seven human HTTPS hosts."""
        self.assertTrue(PLATFORM_INGRESS_TEMPLATE.is_file(),
                        f"missing {PLATFORM_INGRESS_TEMPLATE}")
        self.assertTrue(TRAEFIK_HELMCHART_TEMPLATE.is_file(),
                        f"missing {TRAEFIK_HELMCHART_TEMPLATE}")
        ingress = read(PLATFORM_INGRESS_TEMPLATE)
        provider = read(TRAEFIK_HELMCHART_TEMPLATE)
        # File provider keeps the four Compose/Cockpit human routes.
        for service in FILE_PROVIDER_SERVICES:
            marker = "Host(`" + service + ".{{ base_domain }}`)"
            self.assertIn(marker, provider,
                          f"{TRAEFIK_HELMCHART_TEMPLATE} must route human host {marker}")
        # Ingress covers exactly the three Kubernetes human interfaces.
        docs = split_yaml_docs(ingress)
        self.assertEqual(len(docs), 3,
                         f"{PLATFORM_INGRESS_TEMPLATE} must hold exactly three "
                         f"Ingress docs — got {len(docs)}")
        rule_hosts = re.findall(r"^\s*-\s*host:\s*\"?([a-z]+)\.\{\{\s*base_domain\s*\}\}\"?",
                                ingress, re.M)
        tls_hosts = re.findall(r"^\s*-\s*\"?([a-z]+)\.\{\{\s*base_domain\s*\}\}\"?",
                               ingress, re.M)
        for origin, found in (("rule", rule_hosts), ("TLS", tls_hosts)):
            self.assertEqual(sorted(found), ["grafana", "portainer", "prometheus"],
                             f"{PLATFORM_INGRESS_TEMPLATE} every Ingress needs one "
                             f"{origin} host — got {found}")
        self.assertEqual(ingress.count("ingressClassName: traefik"), 3,
                         f"{PLATFORM_INGRESS_TEMPLATE} every Ingress must set "
                         "ingressClassName: traefik")
        self.assertEqual(ingress.count("pathType: Prefix"), 3,
                         f"{PLATFORM_INGRESS_TEMPLATE} every Ingress must use "
                         "pathType: Prefix")
        # Backends resolve through role vars to the Ready Services.
        merged: dict = {}
        for path in (MONITORING_DEFAULTS, PORTAINER_DEFAULTS):
            merged.update(parse_simple_vars(path))
        for service, (ns_var, name_var, port_var) in INGRESS_SERVICES.items():
            for var in (ns_var, name_var, port_var):
                self.assertIn("{{ %s }}" % var, ingress,
                              f"{PLATFORM_INGRESS_TEMPLATE} {service} must stay "
                              f"variable-driven via {{{{ {var} }}}}")
            self.assertIn('name: "%s"' % service,
                          ingress.replace("{{ %s }}" % name_var, service),
                          f"{PLATFORM_INGRESS_TEMPLATE} {service} backend must "
                          f"resolve to Service {service}")
            self.assertIn("number: %s" % merged[port_var], ingress.replace(
                "{{ %s }}" % port_var, merged[port_var]),
                f"{PLATFORM_INGRESS_TEMPLATE} {service} backend must resolve "
                f"to port {merged[port_var]}")
        # No Ingress for the future API, the Docker proxy, or the exporter.
        for forbidden in ("labmonitor", "12375", "9797", "exporter", "proxy"):
            self.assertNotIn(forbidden, ingress,
                             f"{PLATFORM_INGRESS_TEMPLATE} must not route {forbidden}")
        routers_block = provider.split("routers:", 1)[1].split("services:", 1)[0]
        routers = re.findall(r"^ {14}([a-z0-9-]+):\s*$", routers_block, re.M)
        self.assertEqual(sorted(routers), sorted(FILE_PROVIDER_SERVICES),
                         f"{TRAEFIK_HELMCHART_TEMPLATE} routers must stay exactly "
                         f"{sorted(FILE_PROVIDER_SERVICES)} — got {sorted(routers)}")

    def test_provider_ports_have_no_ingress_or_nodeport(self):
        """12375/exporter ports stay ClusterIP-only: no Ingress, NodePort, or host port."""
        tasks = read(K8S_PLATFORM_TASKS)
        # k8s-platform stays the only Traefik owner with the explicit final order:
        # TLS Secret -> HelmChartConfig -> wait Traefik -> platform Ingress ->
        # wait backends. The Task 7 discovery gate stays ahead of the Ingress stage.
        order_markers = (
            "Aplicar Secret TLS do Traefik",
            "Aplicar HelmChartConfig do Traefik bundled",
            "Aguardar Deployment do Traefik",
            "Assert LabMonitor discovery metadata on Services",
            "Renderizar Ingress da plataforma",
            "Aplicar Ingress da plataforma",
            "Aguardar backends do Ingress da plataforma",
        )
        indexes = [tasks.find(marker) for marker in order_markers]
        for marker, idx in zip(order_markers, indexes):
            self.assertNotEqual(idx, -1,
                                f"{K8S_PLATFORM_TASKS} must contain stage '{marker}'")
        self.assertEqual(indexes, sorted(indexes),
                         f"{K8S_PLATFORM_TASKS} Traefik stages must stay ordered "
                         f"{list(order_markers)}")
        self.assertIn("k8s_platform_ingress_path", tasks,
                      f"{K8S_PLATFORM_TASKS} must render the Ingress via "
                      "k8s_platform_ingress_path")
        self.assertIn("k8s_platform_ingress_path", read(PLATFORM_DEFAULTS),
                      f"{PLATFORM_DEFAULTS} must define k8s_platform_ingress_path")
        # No NodePort may carry a provider port anywhere in the active tree.
        # NodePorts stay variable-driven, so resolve each reference via defaults.
        all_defaults: dict = {}
        for defaults_path in sorted((REPO / "ansible/roles").glob("*/defaults/main.yml")):
            all_defaults.update(parse_simple_vars(defaults_path))
        nodeports: list = []
        for path in iter_active_files():
            if path.suffix not in (".yml", ".yaml", ".j2"):
                continue
            try:
                content = read(path)
            except (UnicodeDecodeError, OSError):
                continue
            for match in re.finditer(
                    r"nodePort:\s*[\"']?(?:(\d+)[\"']?|\{\{\s*([A-Za-z_][A-Za-z0-9_]*))",
                    content):
                if match.group(1) is not None:
                    nodeports.append(match.group(1))
                else:
                    var = match.group(2)
                    self.assertIn(var, all_defaults,
                                  f"{path} nodePort var {var} must resolve via role defaults")
                    nodeports.append(str(all_defaults[var]))
        self.assertEqual(sorted(set(nodeports)), ["30300", "30900", "30909"],
                         "active tree NodePorts must stay exactly the human "
                         f"contracts 30300/30909/30900 — got {sorted(set(nodeports))}")
        for path in (EXPORTER_DEPLOYMENT, EXPORTER_SERVICE, EXPORTER_SERVICEMONITOR,
                     PROVIDER_COMPOSE):
            content = read(path)
            self.assertNotIn("kind: Ingress", content,
                             f"{path} provider must not define an Ingress")
            self.assertNotIn("NodePort", content,
                             f"{path} provider must not use a NodePort")
        # The provider host port never gains a hostname.
        for text, origin in ((read(PLATFORM_INGRESS_TEMPLATE), "platform Ingress"),
                             (read(TRAEFIK_HELMCHART_TEMPLATE), "file provider")):
            self.assertNotIn("12375", text,
                             f"{origin} must not expose the Docker proxy port")


VERIFY_SCRIPT = REPO / "scripts/verify/slice3.sh"

SECRET_VALUE_RE = re.compile(
    r"\$\{?(?:[A-Z_]*(?:PASSWORD|TOKEN|SECRET)|grafana_password|PROBE_JENKINS_TOKEN)"
)


class TestSlice3Task9Verification(unittest.TestCase):
    def test_verification_script_does_not_print_env_files(self):
        """slice3.sh never dumps generated env files and never logs credential values."""
        self.assertTrue(VERIFY_SCRIPT.is_file(), f"missing {VERIFY_SCRIPT}")
        self.assertTrue(VERIFY_SCRIPT.stat().st_mode & 0o111,
                        f"{VERIFY_SCRIPT} must be executable")
        content = read(VERIFY_SCRIPT)
        # No dump command that could target a generated env file. (`awk print`
        # of pod names elsewhere in the script is unrelated to env files, so
        # the dump check is scoped to .env proximity; the blanket .env ban
        # below makes the guarantee absolute.)
        for rx in (r"\bcat\b[^\n]*\.env", r"\.env[^\n]*\bcat\b",
                   r"\bprint\w*\b[^\n]*\.env", r"\.env[^\n]*\bprint\w*\b"):
            self.assertIsNone(re.search(rx, content),
                              f"{VERIFY_SCRIPT} must never dump a generated env file ({rx})")
        self.assertIsNone(re.search(r"(?:^|[\s;&|])cat(?:\s|$)", content),
                          f"{VERIFY_SCRIPT} must never invoke 'cat'")
        self.assertIsNone(re.search(r"\.env(?:\s|$|[\"'])", content),
                          f"{VERIFY_SCRIPT} must not reference generated .env files at all")
        # Credentials come from the process environment or live Secret
        # objects, never from files, and are never expanded into log output.
        self.assertIn("process environment", content,
                      f"{VERIFY_SCRIPT} must document the env-only credential contract")
        self.assertIn("Secret", content,
                      f"{VERIFY_SCRIPT} must consume credentials via Secret references")
        for lineno, raw in enumerate(content.splitlines(), 1):
            code = raw.split("#", 1)[0]
            for segment in re.split(r"\|\||&&|;|\{|\}", code):
                segment = segment.strip()
                if re.match(r"(echo|printf|log|pass|fail)\b", segment):
                    self.assertIsNone(
                        SECRET_VALUE_RE.search(segment),
                        f"{VERIFY_SCRIPT}:{lineno} logs a credential value: {raw.strip()}",
                    )

    def test_verification_script_checks_all_provider_boundaries(self):
        """slice3.sh covers Prometheus, Docker, Jenkins, Kubernetes, discovery, Portainer."""
        self.assertTrue(VERIFY_SCRIPT.is_file(), f"missing {VERIFY_SCRIPT}")
        content = read(VERIFY_SCRIPT)
        lowered = content.lower()
        for keyword in ("prometheus", "docker", "jenkins",
                        "kubernetes", "discovery", "portainer"):
            self.assertIn(keyword, lowered,
                          f"{VERIFY_SCRIPT} must check the {keyword} boundary")
        for marker in ("12375", "18080", "labmonitor", "targets", "/metrics"):
            self.assertIn(marker, content,
                          f"{VERIFY_SCRIPT} must contain functional marker {marker}")

    def test_verification_script_never_exposes_provider_ports_with_ufw_allow_all(self):
        """slice3.sh inspects the firewall read-only; it never opens provider ports."""
        self.assertTrue(VERIFY_SCRIPT.is_file(), f"missing {VERIFY_SCRIPT}")
        content = read(VERIFY_SCRIPT)
        self.assertIn("set -Eeuo pipefail", content,
                      f"{VERIFY_SCRIPT} must start with 'set -Eeuo pipefail'")
        self.assertIn("KUBECONFIG", content,
                      f"{VERIFY_SCRIPT} must resolve KUBECONFIG")
        self.assertIn("/etc/rancher/k3s/k3s.yaml", content,
                      f"{VERIFY_SCRIPT} must default to /etc/rancher/k3s/k3s.yaml")
        self.assertIsNone(
            re.search(r"\bufw\s+(allow|deny|enable|disable|delete|insert|route)\b",
                      content, re.IGNORECASE),
            f"{VERIFY_SCRIPT} must never mutate UFW state (read-only 'ufw status' only)",
        )
        self.assertIsNone(
            re.search(r"\biptables\s+(-A|-I|-D|-F|-X|-Z)\b", content),
            f"{VERIFY_SCRIPT} must never mutate iptables (read-only '-S'/'-L' only)",
        )


class TestSlice3FinalFixWave(unittest.TestCase):
    """Final review fix-wave: conditional reset, non-2xx gate, int ports,
    full NodePort allowlist, exporter prod story."""

    def test_jenkins_reset_is_conditional_no_wipe_when_clean_unconfirmed(self):
        """Destruction is gated on the one-shot marker + explicit opt-in."""
        tasks = read(COMPOSE_TASKS)
        # One-shot marker gates every destructive path.
        self.assertIn(".clean-baseline-complete", tasks,
                      f"{COMPOSE_TASKS} must stat/create the one-shot marker")
        self.assertIn("jenkins_baseline_marker", tasks,
                      f"{COMPOSE_TASKS} must gate destruction on the marker fact")
        # Every `state: absent` removal of the exact Jenkins path is conditional.
        absent_blocks = [m.start() for m in re.finditer(r"state:\s*absent", tasks)]
        self.assertGreaterEqual(len(absent_blocks), 2,
                                f"{COMPOSE_TASKS} must keep exact-path removals — got {len(absent_blocks)}")
        for idx in absent_blocks:
            window = tasks[max(0, idx - 500):idx + 800]
            self.assertIn("/srv/home-server/data/jenkins", window,
                          f"{COMPOSE_TASKS} absent removal must target the exact Jenkins path")
            self.assertIn("jenkins_baseline_marker", window,
                          f"{COMPOSE_TASKS} absent removal must check the marker (no unconditional wipe)")
            self.assertIn("jenkins_clean_reset_confirmed", window,
                          f"{COMPOSE_TASKS} absent removal must require explicit opt-in")
        # Container removal is equally gated.
        self.assertIn("jenkins_clean_reset_confirmed is sameas true", tasks,
                      f"{COMPOSE_TASKS} must keep explicit opt-in (sameas true)")
        # Skip-with-warning when clean+unconfirmed; steady-state no-op when marked.
        self.assertIn("jenkins_preflight_clean", tasks,
                      f"{COMPOSE_TASKS} must compute preflight-clean for skip-vs-fail")
        lowered = tasks.lower()
        self.assertIn("no-op", lowered,
                      f"{COMPOSE_TASKS} must document the steady-state no-op rerun")
        self.assertIn("skipping destructive reset", lowered,
                      f"{COMPOSE_TASKS} must warn (not fail) when clean+unconfirmed")
        # Fail-closed + invariants preserved.
        self.assertIn('compose_jenkins_data_dir == "/srv/home-server/data/jenkins"', tasks,
                      f"{COMPOSE_TASKS} must keep the exact path check")
        self.assertIn("jobs[name,builds[number]]", tasks,
                      f"{COMPOSE_TASKS} must keep the zero jobs/builds preflight query")
        self.assertIn("no_log: true", tasks,
                      f"{COMPOSE_TASKS} must keep no_log around secrets")
        for forbidden in ("backup", "restore", "migration"):
            for line in tasks.splitlines():
                if forbidden in line.lower() and not line.strip().startswith("#"):
                    self.fail(f"{COMPOSE_TASKS} must not add {forbidden} path — found: {line.strip()}")
        # One-shot revert is documented in role comments and README.
        self.assertIn("To re-run one-shot, remove", tasks,
                      f"{COMPOSE_TASKS} must document the one-shot revert")
        self.assertIn("one-shot", read(REPO / "README.md").lower(),
                      "README.md must document the Jenkins one-shot revert")

    def test_firewall_anon_gate_is_non_2xx(self):
        """Anonymous /api/json gate aligns to the Task 3 non-2xx contract."""
        tasks = read(FIREWALL_TASKS)
        self.assertIn("is not match('^2..')", tasks,
                      f"{FIREWALL_TASKS} until must assert non-2xx")
        self.assertIn("is match('^2..')", tasks,
                      f"{FIREWALL_TASKS} failed_when must stay fail-closed on 2xx")
        self.assertNotIn('stdout == "403"', tasks,
                         f"{FIREWALL_TASKS} must not require exactly 403")
        self.assertNotIn('stdout != "403"', tasks,
                         f"{FIREWALL_TASKS} must not fail on non-403 non-2xx")

    def test_k8s_service_ports_render_as_native_ints(self):
        """Service port/nodePort render with | int and parse as int when rendered."""
        server = read(PORTAINER_SERVER_TEMPLATE)
        agent = read(PORTAINER_AGENT_TEMPLATE)
        monitoring = read(MONITORING_TASKS)
        # Templates render unquoted native ints (rendered manifests safe_load as int).
        for path, content, markers in (
            (PORTAINER_SERVER_TEMPLATE, server,
             ("port: {{ portainer_service_port | int }}",
              "nodePort: {{ portainer_nodeport | int }}")),
            (PORTAINER_AGENT_TEMPLATE, agent,
             ("port: {{ portainer_agent_port | int }}",)),
        ):
            for marker in markers:
                self.assertIn(marker, content,
                              f"{path} must render {marker} as native int")
        # Ansible task definitions stay valid YAML (quoted) but convert via | int,
        # so the templated dict carries native ints.
        for marker in ("port: \"{{ monitoring_prometheus_service_port | int }}\"",
                       "port: \"{{ monitoring_grafana_service_port | int }}\""):
            self.assertIn(marker, monitoring,
                          f"{MONITORING_TASKS} must render {marker} (| int)")
        for content, quoted in (
            (server, ['port: "{{ portainer_service_port }}"',
                      'nodePort: "{{ portainer_nodeport }}"']),
            (agent, ['port: "{{ portainer_agent_port }}"']),
            (monitoring, ['port: "{{ monitoring_prometheus_service_port }}"',
                          'port: "{{ monitoring_grafana_service_port }}"']),
        ):
            for marker in quoted:
                self.assertNotIn(marker, content,
                                 f"must not render quoted string without | int: {marker}")
        # Render with dummy ints and verify yaml parses port/nodePort as int.
        try:
            import yaml as _yaml
        except Exception:
            self.skipTest("PyYAML unavailable for int parse check")
            return
        rendered_server = server.replace("{{ portainer_service_port | int }}", "9000") \
            .replace("{{ portainer_nodeport | int }}", "30900") \
            .replace("{{ portainer_namespace }}", "portainer") \
            .replace("{{ portainer_service_name }}", "portainer") \
            .replace("{{ portainer_data_size }}", "5Gi") \
            .replace("{{ portainer_agent_secret_name }}", "portainer-agent") \
            .replace("{{ base_domain }}", "lab.arpa")
        docs = [d for d in _yaml.safe_load_all(rendered_server) if isinstance(d, dict)]
        svc = next(d for d in docs if d.get("kind") == "Service")
        for key in ("port", "nodePort"):
            val = svc["spec"]["ports"][0][key]
            self.assertIsInstance(val, int,
                                  f"server Service {key} must parse as int — got {val!r}")
        self.assertEqual(svc["spec"]["ports"][0]["port"], 9000)
        self.assertEqual(svc["spec"]["ports"][0]["nodePort"], 30900)

    def test_firewall_allowlist_covers_all_human_nodeports(self):
        """UFW allowlist is LAN/VPN-scoped for 30900 + 30300 + 30909."""
        fw_defaults = read(FIREWALL_DEFAULTS)
        allowlist = top_level_block(fw_defaults, "firewall_nodeport_allowlist")
        for nodeport in ("30900", "30300", "30909"):
            self.assertIn(nodeport, allowlist,
                          f"{FIREWALL_DEFAULTS} allowlist must contain {nodeport}")
        self.assertNotIn("12375", allowlist,
                         f"{FIREWALL_DEFAULTS} allowlist must never contain 12375")
        self.assertNotIn("9001", allowlist,
                         f"{FIREWALL_DEFAULTS} allowlist must never contain pod-only 9001")
        fw_tasks = read(FIREWALL_TASKS)
        self.assertIn("firewall_nodeport_allowlist", fw_tasks,
                      f"{FIREWALL_TASKS} must loop the NodePort allowlist to LAN/VPN")
        self.assertIn("resolved_firewall_trusted_cidrs", fw_tasks,
                      f"{FIREWALL_TASKS} NodePort allow must stay LAN/VPN-scoped")

    def test_exporter_prod_override_is_documented(self):
        """Lab keeps local build+import; prod override path is commented in defaults+examples."""
        defaults = read(MONITORING_DEFAULTS)
        self.assertIn('docker_metrics_exporter_image: "labmonitor-docker-exporter:1.0.0"',
                      defaults,
                      f"{MONITORING_DEFAULTS} must keep the lab local build image")
        self.assertIn("docker_metrics_exporter_mode: built", defaults,
                      f"{MONITORING_DEFAULTS} must keep lab built mode")
        for marker in ("ignored inventory", "registry.", "@sha256:",
                       "docker_metrics_exporter_image",
                       "lab keeps", "never use `latest`"):
            self.assertIn(marker.lower(), defaults.lower(),
                          f"{MONITORING_DEFAULTS} must document prod override ({marker})")
        for path in (LAB_EXAMPLE, PROD_EXAMPLE):
            example = read(path)
            self.assertIn("docker_metrics_exporter_image", example,
                          f"{path} must document the exporter override var")
            self.assertIn("@sha256:", example,
                          f"{path} must show a digest-pinned registry example")
            self.assertIn("ignored inventory", example.lower(),
                          f"{path} must point at the ignored inventory override path")
        # Lab build+import flow stays intact.
        tasks = read(MONITORING_TASKS)
        for marker in ("docker save", "k3s ctr images import",
                       "docker_metrics_exporter_mode == 'built'"):
            self.assertIn(marker, tasks,
                          f"{MONITORING_TASKS} must keep the lab build+import flow")


if __name__ == "__main__":
    unittest.main()
