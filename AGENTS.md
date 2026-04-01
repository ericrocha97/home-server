# AGENTS.md - Home Server Infrastructure Repository

This repository contains Ansible playbooks and Kubernetes manifests for configuring and deploying a home server running k3s with observability tools (Prometheus/Grafana) and Portainer.

## Repository Structure

```
├── ansible/                    # Ansible playbooks
│   ├── playbook.yml           # Base server setup
│   ├── k3s_playbook.yml       # K3s installation
│   ├── k8s_apps_playbook.yml  # Kubernetes apps deployment
│   ├── nvm_node_pnpm_playbook.yml
│   ├── zsh_starship_playbook.yml
│   ├── sdkman_playbook.yml
│   ├── inventory.ini          # Target hosts
│   └── secrets.yml            # Ansible Vault secrets (future)
├── k8s/                       # Kubernetes manifests
│   ├── ingress/
│   ├── monitoring/
│   ├── portainer/
│   └── secrets/
└── .vscode/settings.json
```

## Build/Test/Lint Commands

### Ansible Playbooks

All playbooks run from the `ansible/` directory:

```bash
# Base server setup (packages + Docker)
ansible-playbook -i inventory.ini playbook.yml --ask-become-pass

# Install K3s
ansible-playbook -i inventory.ini k3s_playbook.yml --ask-become-pass

# Deploy Kubernetes apps (Portainer, Prometheus Stack, Ingress)
ansible-playbook -i inventory.ini k8s_apps_playbook.yml --ask-become-pass

# Development environment
ansible-playbook -i inventory.ini nvm_node_pnpm_playbook.yml --ask-become-pass
ansible-playbook -i inventory.ini zsh_starship_playbook.yml --ask-become-pass
ansible-playbook -i inventory.ini sdkman_playbook.yml --ask-become-pass

# Install CasaOS
ansible-playbook -i inventory.ini casaos_playbook.yml --ask-become-pass

# Note: CasaOS is configured to run on host port 8081
# to avoid conflict with Traefik on port 80.

# Syntax check all playbooks
ansible-playbook --syntax-check playbook.yml
ansible-playbook --syntax-check k3s_playbook.yml
ansible-playbook --syntax-check k8s_apps_playbook.yml

# List tasks without executing (dry run)
ansible-playbook -i inventory.ini playbook.yml --list-tasks
```

### Required Ansible Collections

Install before running playbooks:

```bash
ansible-galaxy collection install kubernetes.core
ansible-galaxy role install xanmanning.k3s
ansible-galaxy collection install community.docker
```

### YAML Validation

For Kubernetes manifests and Ansible YAML files:

```bash
# Validate YAML syntax (requires yamllint)
yamllint ansible/*.yml k8s/**/*.yaml

# Or using Python YAML parser
python3 -c "import yaml; [yaml.safe_load_all(open(f)) for f in ['playbook.yml']]"
```

### Kubernetes Manifests

```bash
# Apply manifests (requires kubectl configured)
kubectl apply -f k8s/ --dry-run=client  # Validate without applying

# Lint Kubernetes YAML
kubectl create --dry-run=client -f k8s/portainer/portainer-deployment.yaml

# Check Helm values files syntax
helm lint ./k8s/monitoring/kube-prometheus-stack-values.yaml
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

4. **Storage**:
   - Use `storageClassName: local-path` for local-path provisioner
   - Specify appropriate access modes: `ReadWriteOnce` for most cases

### Secrets Management

1. **Never commit actual secrets**: Use `.example.yaml` suffix for templates
2. **Secret files pattern**: `*-admin-secret.yaml`
3. **Check existence in playbooks**: Validate secrets exist before applying
4. **Permissions**: Secret files should have `0600` permissions

### Documentation

1. **Playbook Headers**: Include `name:` for all plays and meaningful task names
2. **Comments**: Add comments for non-obvious decisions or workarounds
3. **README**: Keep `/k8s/README.md` updated with access instructions

### General Conventions

1. **Line Endings**: Use LF (Unix-style) - `.gitattributes` enforces this
2. **File Encoding**: UTF-8
3. **Executable Bit**: Only set on shell scripts, not on YAML/manifest files
4. **Trailing Whitespace**: Remove trailing whitespace

## Development Workflow

1. **Before committing**:
   - Run `ansible-playbook --syntax-check` on all modified playbooks
   - Verify YAML syntax with `yamllint` (if available)
   - Ensure no secrets are committed

2. **Testing Changes**:
   - Use `--check` mode: `ansible-playbook --check playbook.yml`
   - Use `--diff` to see changes: `ansible-playbook --diff playbook.yml`
   - Test on a single host with `--limit`

3. **Order of Execution**:
   ```
   playbook.yml → k3s_playbook.yml → k8s_apps_playbook.yml
   ```

## Security Notes

- Portainer has broad permissions (ClusterRole) - review before production use
- Consider migrating to Portainer Agent for reduced privileges
- Add TLS with cert-manager when ready for production
- Remove NodePort services once Ingress is stable
