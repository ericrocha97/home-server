# Home Server Infrastructure

## Scope And Entry Point

- This is an Ansible-only, lab-first Ubuntu 26.04 home-server platform. `ansible/site.yml` is the only playbook entry point; run it from the repository root with `ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"`.
- Roles run in this fixed dependency order: `base` -> `docker` -> `cockpit` -> `k3s` -> `compose-services` -> `docker-provider` -> `firewall` -> `monitoring` -> `portainer` -> `labmonitor-foundation` -> `k8s-platform`.
- `compose/` is host-native Docker Compose. `k8s/` contains only Kubernetes-side resources. Do not create Kubernetes Services or EndpointSlices for Compose services; Traefik's file provider routes Cockpit, Jenkins, n8n, and Metabase directly to `server_lan_ip`.
- The platform foundation is final infrastructure only: Prometheus/Grafana, read-only Docker and Jenkins providers, Portainer, and LabMonitor identity/configuration. It deliberately does not deploy a `labmonitor-api` workload, product dashboards, workflows, or restores.

## Layout

- `ansible/roles/`: host and platform implementation. `monitoring`, `portainer`, and `labmonitor-foundation` are platform-foundation roles.
- `compose/`: `postgres`, `jenkins`, `n8n`, `metabase`, `docker-provider`, and `portainer-agent` Compose projects. Host data lives in `/srv/home-server/data/<service>`, never in this repository.
- `k8s/monitoring/`: Docker metrics exporter source and Grafana dashboard JSON. `k8s/labmonitor/rbac.yaml` is the future LabMonitor reader RBAC.
- `scripts/verify/platform.sh`: read-only live acceptance suite. It validates positive and negative security contracts and must not be changed to weaken a failed check.
- `tests/test_platform_contract.py` and `tests/test_jenkins_clean_baseline.py`: static contract tests.

## Environment And Secrets

- Real inventories and Vault files are ignored: `ansible/inventories/<env>/hosts.yml` and `group_vars/all/{vars.yml,vault.yml}`. Tracked `*.example.yml` files must use only `192.0.2.10` / `192.0.2.11` placeholders.
- Keep TLS material only in ignored `ansible/secrets/<env>-tls.{crt,key}` and Vault-backed generated host `.env` files only on the server. Never print rendered `.env` content or secret values; use `no_log: true` for tasks that handle them.
- Every externally pulled image is pinned in inventory defaults. Do not add `latest`, an unpinned image, a real LAN IP, a password, token, certificate, or Vault content to tracked files.
- `jenkins_clean_reset_confirmed: true` authorizes a one-time destructive Jenkins clean baseline only while `/srv/home-server/data/jenkins/.clean-baseline-complete` is absent. Leave example inventories `false`; reset the real inventory to `false` after the approved baseline run.

## Security Boundaries

- Docker's daemon remains Unix-socket-only. `docker-provider` is the sole monitoring path: GET-only socket proxy on `server_lan_ip:12375`, reachable only from the k3s pod CIDR. Never expose it through an Ingress, NodePort, or LAN/VPN firewall exception.
- `docker-metrics-exporter` must use the proxy, not mount `/var/run/docker.sock`. The Portainer Docker Agent is the explicit administrative RW socket exception and remains isolated in its own Compose project on port `9001`.
- Jenkins must not join `home-server-data`; only n8n bridges automation and data networks. `automation_writer` owns shared `automation`; `automation_reader` is read-only and never gains ownership, DML, or `CREATE`.
- `labmonitor-api` is least-privilege: read cluster topology and exactly two named ConfigMaps, never Secrets or write verbs. Do not add a LabMonitor Deployment in this repository.
- Human UIs use Traefik/NodePorts as configured. PostgreSQL and providers are not HTTP ingress targets.

## Ansible Implementation Notes

- `kubernetes.core.k8s` executes on the managed host. If its `src` refers to a repository file, first stage it on the host with `copy` or `template` (for example under `/tmp/home-server-*`) and then apply the host-local path. Do not give the module a controller-only `playbook_dir` path.
- Use `kubeconfig: "{{ kubeconfig_path }}"` for every cluster-touching `kubernetes.core` module and `kubectl` command. Helm uses `/usr/local/bin/helm` pinned to v3 because the collection needs the removed-in-v4 `helm repo` workflow.
- Render Secret manifests with `0600` and `no_log: true`; non-secret static manifests may be staged as `root:root` `0644`.
- Compose services must be healthy before `firewall` and `k8s-platform`; their first full-run port exposure is a known transient window. For a first lab bootstrap, close it with the documented split runs below.

## Commands

```bash
# Controller setup and static checks
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
ansible-playbook --syntax-check ansible/site.yml
python3 -m unittest tests.test_platform_contract tests.test_jenkins_clean_baseline
bash -n scripts/hosts/generate-hosts.sh
bash -n scripts/verify/platform.sh
git diff --check

# Render every Compose project with sanitized inputs
for service in postgres jenkins n8n metabase docker-provider portainer-agent; do
  docker compose --env-file "compose/$service/.env.example" \
    -f "compose/$service/compose.yaml" config >/dev/null
done

# Full lab run (real ignored inventory and Vault required)
ansible-playbook -i ansible/inventories/lab/hosts.yml \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml

# First lab bootstrap: close the Compose-before-firewall window immediately
ansible-playbook -i ansible/inventories/lab/hosts.yml \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass \
  ansible/site.yml --tags compose-services
ansible-playbook -i ansible/inventories/lab/hosts.yml \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass \
  ansible/site.yml --tags firewall,k8s-platform
```

- Use a focused role tag for resumable live failures, then rerun the full play: `--tags monitoring`, `portainer`, or `labmonitor-foundation` all require prior roles to be healthy.
- Repository-wide `yamllint ansible/ k8s/ compose/` currently reports baseline violations in existing files. Lint the changed YAML/template paths and do not treat unrelated baseline output as a regression.
- Run `scripts/verify/platform.sh` on a provisioned lab host with `SERVER_LAN_IP`, `JENKINS_LABMONITOR_API_TOKEN`, and optionally `GRAFANA_ADMIN_PASSWORD`; it is read-only and is the final live acceptance check.
