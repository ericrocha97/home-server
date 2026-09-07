# Kubernetes platform

The single-node k3s platform uses the bundled Traefik instance in
`kube-system`. The platform adds the final infrastructure layer: monitoring (Prometheus/Grafana), Portainer
administration, read-only providers, and the LabMonitor provider foundation.
No product is deployed; restore and additional automations live outside this
project.

Host-native Docker Compose services are routed directly by Traefik's file provider;
they are not represented by Kubernetes Services or EndpointSlices.

The file provider adds 3 backends Docker — `jenkins` (`18080`), `n8n` (`15678`) and `metabase` (`13001`) — apontando para `server_lan_ip:porta` com healthCheck; `cockpit` permanece como backend original. Nenhum Service/EndpointSlice é criado para esses 3 serviços.

## Namespaces e workloads (final)

- `monitoring`: `kube-prometheus-stack` `88.6.1` — Prometheus (retenção `15d`,
  PVC `20Gi` em `local-path`, ClusterIP estável `prometheus:9090`, NodePort
  humano `30909`) e Grafana (PVC `5Gi`, ClusterIP `grafana:3000`, NodePort
  `30300`) mais node-exporter, kube-state-metrics e 4 dashboards técnicos via
  ConfigMaps (`grafana-dashboard-host/docker/kubernetes/jenkins`).
  `docker-metrics-exporter` (ClusterIP `9797`) consome apenas
  `http://server_lan_ip:12375` via ServiceMonitor — sem mount de socket.
- `portainer`: Server (NodePort `30900`, ServiceAccount dedicada, Secret do
  agente via Vault) e Kubernetes Agent (ClusterIP `9001`) no mesmo namespace;
  o Docker Agent roda no host (`server_lan_ip:9001`, projeto Compose separado).
- `labmonitor`: somente fundação, sem Deployment — ServiceAccount
  `labmonitor-api` (`get`/`list`/`watch` em nodes/pods/services/namespaces e
  deployments; `get` nos ConfigMaps `labmonitor-catalog` e
  `labmonitor-provider-config`), Secret `labmonitor-jenkins-readonly`
  (`username` + `api-token`, sem password). Sem leitura de Secrets e sem
  `cluster-admin`.
- `kube-system`: Traefik bundled + Secret `traefik-tls`; file provider para
  Compose/Cockpit e Ingress (`ingressClassName: traefik`, `pathType: Prefix`)
  para Grafana/Prometheus/Portainer. RBAC base em `k8s/labmonitor/rbac.yaml`.

## Discovery (7 aplicações navegáveis)

Labels `labmonitor.*` no Docker (jenkins/n8n/metabase com `labmonitor.id`
estável), metadados nos Services (grafana/prometheus/portainer), catálogo
(cockpit) e provider-config (endpoints internos prometheus/docker/jenkins/
kubernetes). PostgreSQL e providers não têm URL navegável. Cada ambiente
materializa apenas seu domínio (`lab.arpa` vs `home.arpa`).

## Verificação

Validação estática a partir da raiz (sem SSH):

```bash
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
ansible-playbook --syntax-check ansible/site.yml
python3 -m unittest discover -s tests -p 'test_*.py'
```

Verificação viva no host (somente leitura, credenciais via ambiente/Secrets,
firewall nunca alterado):

```bash
SERVER_LAN_IP="<ip-do-servidor>" \
JENKINS_LABMONITOR_API_TOKEN="<token-do-vault>" \
GRAFANA_ADMIN_PASSWORD="<senha-do-vault>" \
./scripts/verify/platform.sh
```

Detalhes dos 24 checks (positivos e negativos) em `scripts/verify/platform.sh`
e na seção de plataforma do `README.md` raiz.
