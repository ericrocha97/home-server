# Home Server

Ansible provisions a complete single-node home-server platform on a clean
**Ubuntu 26.04** host. The same code deploys either a `lab` environment
(`lab.arpa`) or a production environment (`home.arpa`).

The platform includes a hardened host, Docker, k3s, Traefik, Compose services,
monitoring, and administration tooling. Persistent service data is stored on

## Services

| Service    | Purpose                              | HTTPS address                 | Direct access (IP:port)        |
| ---------- | ------------------------------------ | ----------------------------- | ------------------------------ |
| Cockpit    | Host administration                  | `https://cockpit.<domain>`    | `https://<server LAN IP>:9090` |
| Jenkins    | CI automation                        | `https://jenkins.<domain>`    | `http://<server LAN IP>:18080` |
| n8n        | Workflow automation                  | `https://n8n.<domain>`        | `http://<server LAN IP>:15678` |
| Metabase   | Analytics                            | `https://metabase.<domain>`   | `http://<server LAN IP>:13001` |
| Grafana    | Dashboards and visualization         | `https://grafana.<domain>`    | `http://<server LAN IP>:30300` |
| Prometheus | Metrics collection and queries       | `https://prometheus.<domain>` | `http://<server LAN IP>:30909` |
| Portainer  | Docker and Kubernetes administration | `https://portainer.<domain>`  | `http://<server LAN IP>:30900` |

`<domain>` is `lab.arpa` for lab or `home.arpa` for production. Traefik serves
these HTTPS endpoints. Cockpit, Jenkins, n8n, and Metabase run as host-native
Compose services; Grafana, Prometheus, and Portainer run in k3s.
Direct IP:port access is allowed only from LAN/VPN. Jenkins,
n8n, and Metabase answer plain HTTP only (TLS is terminated at Traefik); prefer
the HTTPS addresses.

PostgreSQL is an internal database service, not an HTTP endpoint. The Docker
socket provider, Docker metrics exporter, and LabMonitor foundation are
internal-only components. In particular, the Docker provider on port `12375`
cannot be reached by LAN, VPN, Ingress, or NodePort clients.

## Prerequisites

### Administration workstation

- Python 3
- SSH key access to the target host and a non-root sudo-capable user
- `mkcert` for local HTTPS certificates
- Docker Compose, if you will run the local Compose rendering checks

### Target host

- A clean Ubuntu **26.04** installation
- A reachable LAN address
- SSH access for the administration user

## Install the Controller Dependencies

Run from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r ansible/requirements.txt
ansible-galaxy collection install -r ansible/requirements.yml
ansible-galaxy role install -r ansible/requirements.yml
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
```

Reactivate `.venv` and export `ANSIBLE_CONFIG` in every new shell.

## Configure an Environment

Choose `lab` or `prod` and use that name consistently below:

```bash
export ENVIRONMENT=lab
# For production: export ENVIRONMENT=prod

cp "ansible/inventories/$ENVIRONMENT/hosts.example.yml" \
  "ansible/inventories/$ENVIRONMENT/hosts.yml"
mkdir -p "ansible/inventories/$ENVIRONMENT/group_vars/all"
cp "ansible/inventories/$ENVIRONMENT/group_vars/all.example.yml" \
  "ansible/inventories/$ENVIRONMENT/group_vars/all/vars.yml"
```

Edit `hosts.yml` and set `ansible_host` to the target's real LAN IP. Then edit
`group_vars/all/vars.yml`:

- Keep `environment_name` and `base_domain` paired: `lab` / `lab.arpa`, or
  `prod` / `home.arpa`.
- Set `lan_cidr`, optionally `vpn_cidr`, and `base_timezone` for your network
  and location.
- Leave `server_lan_ip: "{{ ansible_host }}"` unless the host has a different
  service address.
- Set `server_lan_interface` or `k3s_flannel_interface` only when automatic
  interface selection is unsuitable.
- Keep image references pinned to `name:tag@sha256:<digest>` where the example
  requires a digest. Never use `latest`.
- Review ports, retention, storage sizes, and NodePorts before deployment.
- Leave `jenkins_clean_reset_confirmed: false` unless you explicitly authorize
  the destructive Jenkins clean baseline. This is a one-shot operation: it
  runs only while `/srv/home-server/data/jenkins/.clean-baseline-complete` is
  absent. To run it again, remove that marker and explicitly set the variable
  to `true`; set it back to `false` immediately after the approved run.

The tracked examples use documentation IPs only. Do not commit the generated

## Configure the Vault

Create the environment Vault:

```bash
ansible-vault create "ansible/inventories/$ENVIRONMENT/group_vars/all/vault.yml"
```

It must define non-empty, distinct secret values for:

```yaml
k3s_token: "<random token>"
postgres_superuser_password: "<unique password>"
postgres_n8n_password: "<unique password>"
postgres_metabase_password: "<unique password>"
n8n_encryption_key: "<random key>"
jenkins_admin_password: "<unique password>"
postgres_automation_writer_password: "<unique password>"
postgres_automation_reader_password: "<unique password>"
jenkins_labmonitor_password: "<unique password>"
jenkins_labmonitor_api_token: "<Jenkins fixed token>"
jenkins_prometheus_password: "<unique password>"
jenkins_prometheus_api_token: "<Jenkins fixed token>"
monitoring_grafana_admin_password: "<unique password>"
portainer_agent_secret: "<random shared agent secret>"
```

Jenkins provider API tokens must have the exact format `11` followed by 32
lowercase hexadecimal characters. Generate one without exposing it in the
repository:

```bash
python3 -c "import secrets; print('11' + secrets.token_hex(16))"
```

All five PostgreSQL passwords must be different. The Jenkins passwords and
tokens must also be different from each other and from the Jenkins admin
password. Never print or commit Vault content or generated host `.env` files.

## Configure HTTPS

The deployment requires a certificate and key on the administration
workstation. Generate them before the first deployment.

```bash
export ENVIRONMENT=lab
export DOMAIN=lab.arpa
# For production: ENVIRONMENT=prod and DOMAIN=home.arpa

mkdir -p ansible/secrets
mkcert -install
mkcert \
  -cert-file "ansible/secrets/${ENVIRONMENT}-tls.crt" \
  -key-file "ansible/secrets/${ENVIRONMENT}-tls.key" \
  "cockpit.${DOMAIN}" \
  "jenkins.${DOMAIN}" \
  "n8n.${DOMAIN}" \
  "metabase.${DOMAIN}" \
  "grafana.${DOMAIN}" \
  "prometheus.${DOMAIN}" \
  "portainer.${DOMAIN}"
chmod 600 "ansible/secrets/${ENVIRONMENT}-tls.key"
```

Each client that opens the HTTPS URLs must trust the mkcert local CA. Configure
your local DNS server with the seven names above, or generate client host
mappings from the inventory:

```bash
./scripts/hosts/generate-hosts.sh "$ENVIRONMENT"
```

The script prints mappings only; review and add them to the client manually.
It prompts for the Vault password because it reads the environment inventory.

## Validate Before Deployment

Set the target environment again if you opened a new terminal:

```bash
export ENVIRONMENT=lab
# For production: export ENVIRONMENT=prod
export HOME_SERVER_SSH_USER="<target-ssh-user>"
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
test -f "ansible/inventories/$ENVIRONMENT/hosts.yml"

ansible-playbook \
  -i "ansible/inventories/$ENVIRONMENT/hosts.example.yml" \
  --syntax-check ansible/site.yml
ansible-inventory -i "ansible/inventories/$ENVIRONMENT/hosts.yml" \
  --graph --ask-vault-pass
ansible -i "ansible/inventories/$ENVIRONMENT/hosts.yml" all -m ping \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass

python3 -m unittest tests.test_platform_contract tests.test_jenkins_clean_baseline
bash -n scripts/hosts/generate-hosts.sh
bash -n scripts/verify/platform.sh
git diff --check
```

To validate every Compose definition with sanitized inputs:

```bash
for service in postgres jenkins n8n metabase docker-provider portainer-agent; do
  docker compose --env-file "compose/$service/.env.example" \
    -f "compose/$service/compose.yaml" config >/dev/null
done
```

## Deploy

For the first deployment, close the short interval between Compose port
publication and firewall enforcement with the two initial runs below. Then run

```bash
ansible-playbook -i "ansible/inventories/$ENVIRONMENT/hosts.yml" \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass \
  ansible/site.yml --tags compose-services

ansible-playbook -i "ansible/inventories/$ENVIRONMENT/hosts.yml" \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass \
  ansible/site.yml --tags firewall,k8s-platform

ansible-playbook -i "ansible/inventories/$ENVIRONMENT/hosts.yml" \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass \
  ansible/site.yml
```

Subsequent runs are idempotent. For a resumable failure, run the affected role
tag, such as `--tags monitoring`, `--tags portainer`, or
`--tags labmonitor-foundation`, then rerun the full playbook.

## Verify the Deployment

The script must run **on the provisioned server** (root or sudo): it uses the
local k3s `kubectl`, inspects `ufw`/`iptables`, and queries endpoints that only
answer on the host itself. Copy the script to the server and run it there:

```bash
# From your client (the Ansible controller):
scp scripts/verify/platform.sh "$HOME_SERVER_SSH_USER@<server LAN IP>":/tmp/

# On the server:
ssh "$HOME_SERVER_SSH_USER@<server LAN IP>"
sudo env SERVER_LAN_IP="<server LAN IP>" \
  JENKINS_LABMONITOR_API_TOKEN="<Vault token>" \
  GRAFANA_ADMIN_PASSWORD="<Vault password>" \
  bash /tmp/platform.sh
```

It checks service readiness, Prometheus targets, Grafana,
Portainer, Jenkins provider permissions, Docker provider boundaries,
LabMonitor RBAC, and discovery metadata.

`GRAFANA_ADMIN_PASSWORD` is optional: the script can read the live Kubernetes
Secret when permitted. The script never changes firewall state or prints
credentials.

From a separate LAN or VPN client (your client machine, not the server itself —
a test from inside the host cannot prove the port is closed to external
clients), this request must fail. A successful
response means the Docker provider boundary is incorrectly exposed:

```bash
curl --connect-timeout 5 "http://<server LAN IP>:12375/version"
```

## Operational Boundaries

- Compose services are routed by Traefik's file provider. Do not create
  Kubernetes Services or EndpointSlices for Cockpit, Jenkins, n8n, or
  Metabase.
- Docker monitoring uses the read-only proxy on port `12375`; the metrics
  exporter must not mount `/var/run/docker.sock`.
- The Portainer Docker Agent is the only administrative read-write Docker
  socket exception and remains isolated on port `9001`.
- Jenkins does not join the database network. n8n is the only service joining
  both automation and data networks. `automation_writer` owns the shared
  database; `automation_reader` has no write or `CREATE` privilege.
- The LabMonitor identity can read cluster topology and two named ConfigMaps,
  but cannot read Secrets or change cluster resources. No LabMonitor web API
  or workload is deployed by this repository.
