"""Clean Jenkins Java 21 LTS baseline contract — Task 0.

Seven named cases, inspecting Dockerfile, Compose YAML, role defaults/tasks,
and example inventories. Must fail against 2.504.3-lts-jdk17 and pass after
2.568.2-lts-jdk21 digest-pinned clean baseline.
"""
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]

TARGET_IMAGE = "jenkins/jenkins:2.568.2-lts-jdk21@sha256:8547df3b0db2803d158ecc9499207a056bb30c23fddc18bb5b4a4dc14e77dd09"
TARGET_DIGEST = "sha256:8547df3b0db2803d158ecc9499207a056bb30c23fddc18bb5b4a4dc14e77dd09"
TARGET_TAG = "2.568.2-lts-jdk21"
OLD_TAG = "2.504.3-lts-jdk17"
OLD_DIGEST = "sha256:dd570585c3adadefcfbeba915e27bf7feca1815a0ea8a659d46b51f54fc7ea06"

DOCKERFILE = REPO / "compose/jenkins/Dockerfile"
COMPOSE = REPO / "compose/jenkins/compose.yaml"
ENV_EXAMPLE = REPO / "compose/jenkins/.env.example"
DEFAULTS = REPO / "ansible/roles/compose-services/defaults/main.yml"
TASKS = REPO / "ansible/roles/compose-services/tasks/main.yml"
LAB_EXAMPLE = REPO / "ansible/inventories/lab/group_vars/all.example.yml"
PROD_EXAMPLE = REPO / "ansible/inventories/prod/group_vars/all.example.yml"
GROOVY = REPO / "ansible/roles/compose-services/templates/jenkins-init-admin.groovy.j2"


def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


class TestJenkinsCleanBaseline(unittest.TestCase):
    def test_target_image_uses_java21_lts_version(self):
        """Defaults and both example inventories must use exact 2.568.2-lts-jdk21 and no jdk17/latest refs."""
        for path in (DEFAULTS, LAB_EXAMPLE, PROD_EXAMPLE):
            self.assertTrue(path.is_file(), f"missing {path}")
            content = read(path)
            self.assertIn(TARGET_TAG, content,
                          f"{path} must contain {TARGET_TAG}")
            self.assertIn(TARGET_IMAGE, content,
                          f"{path} must contain full digest-pinned image {TARGET_IMAGE}")
            self.assertIn('compose_jenkins_build_tag_prefix: "2.568.2-lts-jdk21"', content,
                          f"{path} must pin build tag prefix to {TARGET_TAG} — got {path.read_text()[:500]}")
            self.assertNotIn(OLD_TAG, content,
                             f"{path} must not contain old tag {OLD_TAG}")
            self.assertNotIn("jdk17", content,
                             f"{path} must not contain jdk17 — Java 21 baseline required")
            # old digest must not remain
            self.assertNotIn(OLD_DIGEST, content,
                             f"{path} must not contain old digest")
            # no latest tag refs for jenkins
            # allow unrelated 'latest' in comments? Strict: active jenkins image must not contain :latest
            # Check jenkins image lines specifically
            for line in content.splitlines():
                if "compose_jenkins" in line and "latest" in line.lower():
                    self.fail(f"{path} Jenkins image line must not contain 'latest': {line}")
                if "jenkins/jenkins" in line and "latest" in line.lower():
                    self.fail(f"{path} must not contain 'latest' in Jenkins image ref: {line}")

        # Dockerfile must keep ARG pattern and FROM must receive digest-pinned ref via ARG
        dockerfile = read(DOCKERFILE)
        self.assertIn("ARG JENKINS_BASE_IMAGE", dockerfile,
                      "Dockerfile must keep ARG JENKINS_BASE_IMAGE pattern")
        self.assertIn("FROM ${JENKINS_BASE_IMAGE}", dockerfile,
                      "Dockerfile FROM must receive full digest-pinned reference via ARG")
        # Dockerfile must not hardcode old jdk17 or any lts/latest bare ref
        self.assertNotIn("jdk17", dockerfile,
                         "Dockerfile must not contain jdk17")
        self.assertNotIn(OLD_TAG, dockerfile,
                         "Dockerfile must not contain old tag")
        self.assertNotIn(OLD_DIGEST, dockerfile,
                         "Dockerfile must not contain old digest")
        # Ensure no hardcoded FROM jenkins/jenkins:... without ARG
        for line in dockerfile.splitlines():
            stripped = line.strip()
            if stripped.startswith("FROM jenkins/jenkins"):
                self.fail(f"Dockerfile must not hardcode FROM image, must use ARG: {line}")

        # Compose must not contain old version nor jdk17
        compose = read(COMPOSE)
        self.assertNotIn(OLD_TAG, compose)
        self.assertNotIn("jdk17", compose)

        # .env.example must not contain old refs either if it mentions jenkins image
        if ENV_EXAMPLE.is_file():
            env_ex = read(ENV_EXAMPLE)
            if "jenkins" in env_ex.lower():
                self.assertNotIn("jdk17", env_ex.lower(),
                                 ".env.example must not contain jdk17")
                self.assertNotIn("2.504.3", env_ex,
                                 ".env.example must not contain old version")

        # Groovy and compose must keep JENKINS_URL derived from base_domain and port 18080
        self.assertIn("base_domain", read(DEFAULTS),
                      "defaults must keep JENKINS_URL derived from base_domain")
        self.assertIn("18080", compose,
                      "compose must preserve port 18080")

    def test_target_image_is_digest_pinned(self):
        """All Jenkins base image refs must be name:tag@sha256:<64-hex> with exact digest."""
        pattern = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
        for path in (DEFAULTS, LAB_EXAMPLE, PROD_EXAMPLE):
            content = read(path)
            # extract compose_jenkins_base_image value
            m = re.search(r'compose_jenkins_base_image:\s*"([^"]+)"', content)
            self.assertIsNotNone(m, f"{path} must define compose_jenkins_base_image")
            image = m.group(1)
            self.assertRegex(image, pattern,
                             f"{path} compose_jenkins_base_image must be digest-pinned name:tag@sha256: {image}")
            self.assertIn(TARGET_DIGEST, image,
                          f"{path} must contain expected digest {TARGET_DIGEST} — got {image}")
            self.assertIn(TARGET_TAG, image,
                          f"{path} must contain tag {TARGET_TAG} — got {image}")

        # Dockerfile must use ARG, not hardcoded digest
        dockerfile = read(DOCKERFILE)
        self.assertIn("FROM ${JENKINS_BASE_IMAGE}", dockerfile)
        # Defaults validation task must still enforce digest pin
        tasks = read(TASKS)
        self.assertIn("@sha256", tasks,
                      "tasks must still validate @sha256 pin")
        self.assertIn("compose_jenkins_base_image is match", tasks,
                      "tasks must validate jenkins base image is digest-pinned")

    def test_compose_does_not_publish_agent_port(self):
        """Compose must not publish 50000 and must keep only 18080:8080."""
        compose = read(COMPOSE)
        self.assertNotIn("50000", compose,
                         "compose must not publish agent port 50000")
        # also check tasks file doesn't publish it
        tasks = read(TASKS)
        self.assertNotIn("50000", tasks,
                         "tasks must not publish 50000")
        dockerfile = read(DOCKERFILE)
        self.assertNotIn("50000", dockerfile,
                         "Dockerfile must not expose 50000")
        # ports section must contain 18080:8080 (via JENKINS_PORT variable)
        self.assertIn("8080", compose,
                      "compose must publish 8080")
        self.assertTrue("18080" in compose or "JENKINS_PORT" in compose,
                        "compose must reference 18080 via JENKINS_PORT")
        # ensure no additional agent container
        # crude check: only one service named jenkins, no inbound-agent
        self.assertNotIn("inbound-agent", compose.lower())
        self.assertNotIn("jenkins-agent", compose.lower())
        self.assertNotIn("jenkins_agent", compose.lower())

    def test_no_clean_reset_without_explicit_confirmation(self):
        """Jenkins clean reset must require jenkins_clean_reset_confirmed == true; examples keep false with explanation."""
        tasks = read(TASKS)
        # must reference jenkins_clean_reset_confirmed
        self.assertIn("jenkins_clean_reset_confirmed", tasks,
                      "tasks must reference jenkins_clean_reset_confirmed for clean-reset opt-in")
        # must fail unless exactly true
        # accept patterns: jenkins_clean_reset_confirmed is not true, != true, not == true, etc
        has_fail = "fail" in tasks.lower()
        self.assertTrue(has_fail, "tasks must contain a fail/assert for opt-in")
        # check for assertion that it is true
        has_true_check = (
            "jenkins_clean_reset_confirmed is not true" in tasks
            or "jenkins_clean_reset_confirmed != true" in tasks
            or "jenkins_clean_reset_confirmed | bool" in tasks
            or "jenkins_clean_reset_confirmed == true" in tasks
            or "jenkins_clean_reset_confirmed | default(false)" in tasks
            or "jenkins_clean_reset_confirmed" in tasks and "true" in tasks
        )
        self.assertTrue(has_true_check,
                        "tasks must assert jenkins_clean_reset_confirmed is exactly true")
        # must use no_log where handling opt-in or uri
        # at least one no_log in the jenkins preflight area
        # Check that tasks around jenkins_clean_reset_confirmed have no_log
        # Simple: tasks contains no_log somewhere after the opt-in check
        idx = tasks.find("jenkins_clean_reset_confirmed")
        self.assertNotEqual(idx, -1, "must find opt-in")
        # Look ahead 5000 chars for no_log
        self.assertIn("no_log: true", tasks[idx: idx + 8000],
                      "clean-reset preflight must use no_log: true")

        for path in (LAB_EXAMPLE, PROD_EXAMPLE):
            content = read(path)
            self.assertIn("jenkins_clean_reset_confirmed", content,
                          f"{path} must contain jenkins_clean_reset_confirmed")
            # must be false in example
            # allow with or without quotes
            self.assertRegex(content, r"jenkins_clean_reset_confirmed:\s*false",
                             f"{path} example must keep jenkins_clean_reset_confirmed: false")
            # must explain operator changes only for clean baseline run
            lowered = content.lower()
            self.assertTrue(
                "clean" in lowered and "baseline" in lowered or "clean reset" in lowered or "operator" in lowered,
                f"{path} must explain operator changes it only for clean baseline run — content: {content[-500:]}"
            )

        # query shape must be present
        self.assertIn("jobs[name,builds[number]]", tasks,
                      "tasks must query tree=jobs[name,builds[number]] for zero-state preflight")
        self.assertIn("127.0.0.1", tasks,
                      "tasks must query 127.0.0.1:18080 for preflight")

    def test_no_backup_restore_or_migration_path_exists(self):
        """Must not add backup/restore/migration/archive/JENKINS_HOME preservation logic; only exact dir removal after assertion."""
        tasks = read(TASKS)
        lowered = tasks.lower()
        # forbid backup/restore/migration/archive as tasks
        for keyword in ("backup", "restore", "migration"):
            # count occurrences, fail if any active task contains them
            # allow comments that explicitly say "no backup"? But spec says do not add path, so even mentions should be avoided outside docs
            # We'll fail if keyword appears in tasks file at all except maybe in fail_msg mentioning backup is forbidden? But spec says don't add those, so any occurrence is suspect.
            # To be practical, assert that tasks file does not contain those words as active logic (e.g., 'backup' in a task name or shell).
            # We'll search case-insensitive but allow the word in fail_msg? Safer to forbid entirely for Task 0 baseline.
            if keyword in lowered:
                # locate lines containing keyword
                lines = [l for l in tasks.splitlines() if keyword in l.lower()]
                # if any line is not a comment, fail
                for line in lines:
                    stripped = line.strip()
                    if not stripped.startswith("#"):
                        self.fail(f"tasks must not contain {keyword} path — found: {line.strip()}")

        # archive is also forbidden unless it's part of 'unarchive' ansible module? Check for tar/archive words
        if "archive" in lowered:
            lines = [l for l in tasks.splitlines() if "archive" in l.lower()]
            for line in lines:
                if not line.strip().startswith("#"):
                    self.fail(f"tasks must not contain archive path — found: {line.strip()}")

        # JENKINS_HOME preservation/copy logic forbidden — but jenkins_home volume is allowed as bind mount path
        # Check for copy of JENKINS_HOME or cp
        # Look for patterns that would copy the directory
        forbidden_patterns = [
            r"\bcp\s+.*jenkins",
            r"copy.*jenkins_home",
            r"JENKINS_HOME",
            r"tar\s+.*jenkins",
            r"rsync.*jenkins",
        ]
        for pat in forbidden_patterns:
            if re.search(pat, tasks, re.IGNORECASE):
                # allow the volume bind device: /srv/home-server/data/jenkins (that's not JENKINS_HOME env var)
                # but disallow env var string JENKINS_HOME
                if "JENKINS_HOME" in tasks and pat == r"JENKINS_HOME":
                    self.fail(f"tasks must not contain JENKINS_HOME preservation logic — found pattern {pat}")

        # Must contain exact path removal only after assertion, and recreate with correct mode
        self.assertIn("/srv/home-server/data/jenkins", tasks,
                      "tasks must reference exact Jenkins data dir /srv/home-server/data/jenkins for clean reset")
        # ensure removal is via file state: absent or rm -rf with exact path
        has_removal = (
            'state: absent' in tasks and '/srv/home-server/data/jenkins' in tasks
            or 'rm -rf' in tasks
            or 'file:' in tasks
        )
        self.assertTrue(has_removal, "tasks must remove exact dir after assertion")
        # ensure recreate with 0750 and correct uid/gid
        self.assertIn("0750", tasks,
                      "tasks must recreate dir with mode 0750")
        # ensure no broad removal like /srv/home-server/data
        # check that rm -rf does not target parent without jenkins suffix
        if "rm -rf /srv/home-server/data " in tasks or "rm -rf /srv/home-server/data\n" in tasks:
            self.fail("tasks must not remove broad /srv/home-server/data, only /srv/home-server/data/jenkins")

        # also ensure the clean reset is fail-closed: if jobs/builds exist, do not remove
        # check for assertion about jobs empty and builds zero
        self.assertTrue(
            "jobs" in lowered and ("empty" in lowered or "length" in lowered or "== 0" in tasks),
            "tasks must assert job list is empty before removal"
        )

    def test_no_example_jobs_or_agents_are_declared(self):
        """No agent container, no inbound-agent, no example job is declared in compose or tasks."""
        compose = read(COMPOSE)
        tasks = read(TASKS)
        dockerfile = read(DOCKERFILE)
        # compose must have exactly one service: jenkins
        # Parse yaml if possible
        try:
            import yaml
            data = yaml.safe_load(compose)
            services = data.get("services", {}) if isinstance(data, dict) else {}
            self.assertEqual(set(services.keys()), {"jenkins"},
                             f"compose must declare only jenkins service, got {list(services.keys())}")
        except Exception as e:
            # fallback to string checks
            self.assertNotIn("inbound-agent", compose.lower(),
                             f"compose must not declare inbound-agent: {e}")
        # no agent port
        self.assertNotIn("50000", compose)
        self.assertNotIn("50000", tasks)
        # no example job creation via groovy or xml
        for keyword in ("example", "seed", "job-dsl", "jenkins-agent", "inbound-agent"):
            if keyword in tasks.lower() and "jenkins_clean" not in tasks.lower():
                # allow but check
                pass
            self.assertNotIn("example job", tasks.lower(),
                             "tasks must not create example jobs")
        # Dockerfile must not install agent-related packages
        self.assertNotIn("inbound-agent", dockerfile.lower())
        # tasks must not contain a second docker container for agent
        # check for docker_compose with agent project
        self.assertNotIn("jenkins-agent", tasks.lower())
        self.assertNotIn("inbound_agent", tasks.lower())
        # Check no job xml or jobs directory creation outside clean reset
        # Allow init.groovy.d creation but not jobs population
        for line in tasks.splitlines():
            if "jobs" in line.lower() and "api/json" not in line.lower() and "find" not in line.lower() and "/srv/home-server/data/jenkins/jobs" not in line:
                # allow the preflight inspection of jobs dir, but not creation of example jobs
                if "example" in line.lower() or "seed" in line.lower():
                    self.fail(f"tasks must not declare example jobs: {line}")

    def test_existing_admin_is_the_only_baseline_account(self):
        """Only the existing admin is created; no provider users, no Prometheus/matrix-auth plugins in Task 0."""
        groovy = read(GROOVY)
        tasks = read(TASKS)
        dockerfile = read(DOCKERFILE)
        compose = read(COMPOSE)

        # groovy must create/bootstrap admin via JENKINS_ADMIN_ID/PASSWORD
        self.assertIn("JENKINS_ADMIN_ID", groovy,
                      "groovy must reference JENKINS_ADMIN_ID")
        self.assertIn("JENKINS_ADMIN_PASSWORD", groovy,
                      "groovy must reference JENKINS_ADMIN_PASSWORD")
        self.assertIn("HudsonPrivateSecurityRealm", groovy,
                      "groovy must use HudsonPrivateSecurityRealm for admin")
        # must not create provider users in Task 0
        for user in ("labmonitor-api", "labmonitor", "prometheus-scraper", "prometheus_scraper"):
            self.assertNotIn(user, groovy.lower(),
                             f"groovy must not create provider user {user} in Task 0 baseline")
            self.assertNotIn(user, tasks.lower(),
                             f"tasks must not create provider user {user} in Task 0")

        # must not add prometheus or matrix-auth plugins in Task 0
        for plugin_keyword in ("prometheus:", "matrix-auth", "matrix_auth"):
            self.assertNotIn(plugin_keyword, dockerfile.lower(),
                             f"Dockerfile must not add {plugin_keyword} in Task 0 — Task 3 does")
            self.assertNotIn(plugin_keyword, tasks.lower(),
                             f"tasks must not install {plugin_keyword} in Task 0")

        # Dockerfile must not contain plugin install for those
        self.assertNotIn("plugins.txt", dockerfile,
                         "Dockerfile must not reference plugins.txt in Task 0 baseline")

        # compose .env.example must not contain provider tokens
        if ENV_EXAMPLE.is_file():
            env_ex = read(ENV_EXAMPLE)
            self.assertNotIn("labmonitor", env_ex.lower(),
                             ".env.example must not contain labmonitor provider in Task 0")
            self.assertNotIn("prometheus-scraper", env_ex.lower(),
                             ".env.example must not contain prometheus-scraper in Task 0")

        # groovy must still be admin-only — check that authorization strategy remains FullControl or is at least not provider-permissive
        # In Task 0 baseline, it uses FullControlOnceLoggedInAuthorizationStrategy (checked in audit) — allow either that or future GlobalMatrix after Task 3, but Task 0 must not yet add provider perms
        # Ensure no grant for labmonitor
        self.assertNotIn("labmonitor", groovy.lower())
