# AGENTS.md - Home Server Infrastructure Repository

This repository provisions a home server from a clean Ubuntu 26.04 lab-first workflow. Slice 1 installs the host base, Docker, Cockpit, single-node k3s and the bundled Traefik in `kube-system` with a file provider for `lab.arpa` / `home.arpa` hostnames.

## Repository Structure

```
├── ansible/                    # Ansible controller
│   ├── ansible.cfg            # controller defaults (roles_path, collections_paths)
│   ├── site.yml               # single entry point — ansible/site.yml
│   ├── requirements.yml       # pinned collections + xanmanning.k3s v3.6.2
│   ├── requirements.txt       # ansible-core 2.20.1, netaddr
│   ├── inventories/
│   │   ├── lab/
│   │   │   ├── hosts.yml              # ignored — real lab inventory (ansible_host / server_lan_ip)
│   │   │   ├── hosts.example.yml      # 192.0.2.10 placeholder
│   │   │   └── group_vars/
│   │   │       ├── all.yml            # ignored — lab vars (base_domain: lab.arpa)
│   │   │       ├── all.example.yml
│   │   │       └── vault.yml          # ignored — k3s_token
│   │   └── prod/
│   │       ├── hosts.yml              # ignored — real prod inventory
│   │       ├── hosts.example.yml      # 192.0.2.11 placeholder
│   │       └── group_vars/
│   │           ├── all.example.yml    # base_domain: home.arpa
│   │           ├── all.yml            # ignored — prod vars
│   │           └── vault.yml          # ignored
│   ├── roles/
│   │   ├── base/              # packages, timezone, SSH hardening, /srv/home-server
│   │   ├── docker/            # Docker Engine + Compose plugin, no TCP
│   │   ├── cockpit/           # Cockpit on 9090 with Traefik proxy awareness
│   │   ├── k3s/               # pinned k3s single-node + LAN interface detection
│   │   ├── firewall/          # UFW allowlist for Slice 1 + CNI forward policy
│   │   └── k8s-platform/      # Secret kube-system/traefik-tls + HelmChartConfig
│   └── secrets/               # ignored — lab-tls.crt/key, prod-tls.crt/key
├── compose/                   # host-native Docker Compose services (Slice 2)
├── k8s/                       # Kubernetes manifests
│   ├── ingress/README.md      # file-provider boundary (no Services/EndpointSlices for Docker)
│   └── README.md              # Kubernetes platform overview
├── scripts/
│   └── hosts/
│       ├── generate-hosts.sh      # read-only host mapping generator (lab|prod)
│       ├── lab.hosts.example      # 8 lines 192.0.2.10 *.lab.arpa
│       └── prod.hosts.example     # 8 lines 192.0.2.11 *.home.arpa
├── old/                       # local ignored archive — old ansible/k8s preserved locally, never loaded
├── .env.example
└── .vscode/settings.json
```

`old/` is gitignored and never executed by `ansible/site.yml`. Legacy CasaOS and EndpointSlices workflows have been removed.

## Build/Test/Lint Commands

### Ansible Playbooks

All playbooks run from the repository root with `ANSIBLE_CONFIG` pointing to `ansible/ansible.cfg`:

```bash
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"

# Full bootstrap (lab)
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml

# Full bootstrap (prod)
ansible-playbook -i ansible/inventories/prod/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml

# Tagged runs
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass ansible/site.yml --tags base
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass ansible/site.yml --tags docker
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass ansible/site.yml --tags cockpit
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags k3s
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags firewall
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags k8s-platform

# Syntax / inventory checks (no SSH)
ansible-playbook --syntax-check ansible/site.yml
ansible-inventory -i ansible/inventories/lab/hosts.example.yml --graph
ansible-inventory -i ansible/inventories/prod/hosts.example.yml --graph

# Host mapping helper (read-only, never writes /etc/hosts)
./scripts/hosts/generate-hosts.sh lab
./scripts/hosts/generate-hosts.sh prod
bash -n scripts/hosts/generate-hosts.sh

# List tasks without executing (dry run)
ansible-playbook -i ansible/inventories/lab/hosts.example.yml ansible/site.yml --list-tasks
```

### Required Ansible Collections and Roles

Pinned in `ansible/requirements.yml`, install with:

```bash
pip install -r ansible/requirements.txt
ansible-galaxy collection install -r ansible/requirements.yml
ansible-galaxy role install -r ansible/requirements.yml
```

- `ansible.posix` `2.1.0`
- `community.docker` `5.0.4`
- `community.general` `12.1.0`
- `kubernetes.core` `6.2.0`
- `xanmanning.k3s` `v3.6.2` (from https://github.com/PyratLabs/ansible-role-k3s)

### YAML Validation

For Kubernetes manifests and Ansible YAML files:

```bash
# Validate YAML syntax (requires yamllint)
yamllint ansible/ k8s/

# Or using Python YAML parser
python3 -c "import yaml, glob; [list(yaml.safe_load_all(open(f))) for f in glob.glob('ansible/**/*.yml', recursive=True)]"
```

### Kubernetes Manifests

Slice 1 keeps `k8s/` minimal. Host-native Docker Compose services are **not** represented by Kubernetes Services or EndpointSlices; they are routed by the bundled Traefik file provider generated by `k8s-platform`.

```bash
# Validate manifests without applying (requires kubectl)
kubectl apply -f k8s/ --dry-run=client

# Validate ingress boundary doc
cat k8s/ingress/README.md

# Lint a manifest
kubectl create --dry-run=client -o yaml -f k8s/ingress/README.md  # placeholder — use real manifests from later slices

# Check platform README
cat k8s/README.md
```

## Code Style Guidelines

### YAML Conventions

1. **Document Separators**: Use `---` to separate multiple YAML documents in a single file
2. **Indentation**: 2 spaces (no tabs)
3. **Quotes**: Use quotes for strings containing special characters or variables:
   - Ansible: Always quote variables: `name: "{{ ansible_user }}"`
   - Kubernetes: Quote port numbers and special values if needed
4. **Booleans**: Use lowercase `true`/`false` (not `True`/`False`)
5. **Line Length**: Keep lines under 120 characters when practical

### Ansible Best Practices

1. **Task Names**: Use descriptive names in English, imperative mood:
   - Good: `Ensure Docker is installed`
   - Bad: `Installing docker`

2. **Idempotency**: All tasks must be idempotent:
   - Use `state: present` for packages
   - Use `creates:` parameter for shell commands
   - Use `changed_when:` to suppress spurious changes

3. **Become**: Use `become: yes` only when necessary (per-task or per-play):
   ```yaml
   - name: Install package requiring root
     apt:
       name: curl
       state: present
     become: yes
   ```

4. **Variable Usage**:
   - Always quote variable interpolation: `"{{ var_name }}"`
   - Use descriptive variable names: `k8s_manifests_root` not `path`
   - Define variables in `vars:` block or `ansible/group_vars/`

5. **Error Handling**:
   - Use `failed_when:` for conditional failures
   - Use `changed_when: false` for informational commands
   - Add `run_once: true` for tasks that should execute once per playbook run

6. **Handler Conventions**:
   - Notify handlers by name, not by task name
   - Keep handlers simple and focused

### Kubernetes Manifest Conventions

1. **Resource Ordering**: Within a manifest file, resources should be ordered:
   - Namespace (if creating)
   - RBAC (ServiceAccount, ClusterRole, Role, RoleBinding, ClusterRoleBinding)
   - ConfigMap / Secret
   - Deployment / StatefulSet / DaemonSet
   - Service
   - Ingress

2. **Naming Conventions**:
   - Use lowercase with hyphens: `portainer-deployment.yaml`
   - Resource names should be descriptive: `tools-ingress` not `ingress`
   - Labels should follow: `app: portainer` or `app.kubernetes.io/name: grafana`

3. **Ingress Annotations**:
    - Always specify ingress class: `kubernetes.io/ingress.class: traefik`
    - Use `pathType: Prefix` for most paths
    - Prefer `spec.ingressClassName: traefik` in new manifests

4. **Storage**:
   - Use `storageClassName: local-path` for local-path provisioner
   - Specify appropriate access modes: `ReadWriteOnce` for most cases

### Secrets Management

1. **Never commit actual secrets**: Use `.example.yaml` suffix for templates
2. **Secret files pattern**: `*-admin-secret.yaml`
3. **Check existence in playbooks**: Validate secrets exist before applying
4. **Permissions**: Secret files should have `0600` permissions
5. **Local TLS files**: keep mkcert outputs local-only in `ansible/secrets/`:
   - `lab-tls.crt` / `lab-tls.key` for `*.lab.arpa`
   - `prod-tls.crt` / `prod-tls.key` for `*.home.arpa`
   - never commit them
6. **Vault**: `ansible/inventories/<env>/group_vars/vault.yml` holds `k3s_token` (0600, encrypted) — never commit plaintext
7. **Ignored inventory**: `ansible/inventories/*/hosts.yml` and `ansible/inventories/*/group_vars/all.yml` are ignored; only `*.example.yml` with `192.0.2.0/24` placeholders are tracked
8. **k8s secrets**: `k8s/secrets/*.yaml` is ignored, `!k8s/secrets/*.example.yaml` is tracked
9. **Local archive**: `old/` is ignored and never executed

### Documentation

1. **Playbook Headers**: Include `name:` for all plays and meaningful task names
2. **Comments**: Add comments for non-obvious decisions or workarounds
3. **README**: Keep `/k8s/README.md` and `/README.md` updated with Slice 1 access instructions (hostnames via `scripts/hosts/generate-hosts.sh`, direct `IP:9090` fallback)

### General Conventions

1. **Line Endings**: Use LF (Unix-style) - `.gitattributes` enforces this
2. **File Encoding**: UTF-8
3. **Executable Bit**: Only set on shell scripts, not on YAML/manifest files
4. **Trailing Whitespace**: Remove trailing whitespace

## Development Workflow

1. **Before committing**:
   - Run `ansible-playbook --syntax-check ansible/site.yml`
   - Verify YAML syntax with `yamllint ansible/ k8s/`
   - Check shell helper: `bash -n scripts/hosts/generate-hosts.sh`
   - Ensure no secrets or real inventories are staged (`git status`, `git diff --cached`)

2. **Testing Changes**:
   - Use `--check` mode: `ansible-playbook -i ansible/inventories/lab/hosts.yml --check ansible/site.yml`
   - Use `--diff` to see changes: `ansible-playbook -i ansible/inventories/lab/hosts.yml --diff ansible/site.yml`
   - Test on a single host with `--limit` or by targeting `lab` only

3. **Order of Execution** (`ansible/site.yml`):
   ```
   base → docker → cockpit → k3s → firewall → k8s-platform
   ```
   The host and Docker prerequisites exist before k3s; firewall is enabled only after k3s; Traefik is configured only after the Kubernetes API is healthy.

4. **Hostnames**: Generate mappings with `./scripts/hosts/generate-hosts.sh lab|prod` and copy manually to the client `/etc/hosts` if name resolution is needed. The helper never edits `/etc/hosts` automatically.

## Security Notes

- Docker daemon exposed only via Unix socket; no `2375`/`2376` TCP listeners.
- Cockpit listens on `9090` and is fronted by Traefik file provider for `cockpit.lab.arpa` / `cockpit.home.arpa` with `insecureSkipVerify` only on the host backhaul; client-facing TLS uses mkcert `traefik-tls` Secret in `kube-system`.
- UFW default ingress `deny`, egress `allow`, `DEFAULT_FORWARD_POLICY="ACCEPT"` for k3s CNI; allowlist in Slice 1 is only `22`, `80`, `443`, `9090`, `6443` from `lan_cidr`/`vpn_cidr` plus `k3s_pod_cidr` → `k3s_service_cidr` routed and `k3s_pod_cidr` → `server_lan_ip:9090`.
- Do not expose raw PostgreSQL (`5432`/`15432`) via HTTP Ingress; only web UIs belong behind Ingress.
- Hostnames use `lab.arpa` (lab) and `home.arpa` (prod) resolved via manually copied hosts files from `scripts/hosts/generate-hosts.sh`; no automatic `/etc/hosts` mutation and no legacy EndpointSlices for Docker services.
- Local archive `old/` is ignored and never loaded by the new `site.yml`; do not restore Compose data or run applications during Slice 1.
- Do not commit real LAN IPs in public docs/manifests; use placeholders (`192.0.2.10`/`192.0.2.11`) and runtime variables (`server_lan_ip` / `ansible_host`).
