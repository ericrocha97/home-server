# Manifests Kubernetes (k3s)

Esta pasta contém a migração dos serviços antes orquestrados por `docker-compose` para o cluster k3s.

## Visão Geral

| Serviço              | Tipo K8s                        | Persistência    | Exposição         | Observações |
|----------------------|---------------------------------|-----------------|-------------------|-------------|
| Portainer            | Deployment                      | PVC 1Gi         | Ingress / NodePort opc. | Gerencia Docker + cluster k3s. Métricas em `/api/system/metrics` |
| Prometheus/Grafana   | Helm Chart kube-prometheus-stack| PVCs (values)   | Grafana via PF/Ingress | Stack de monitoramento principal |
| cAdvisor             | DaemonSet + Service             | -               | ClusterIP (headless) | Métricas por nó dos containers Docker e pods |
| node-exporter        | DaemonSet (via chart)           | -               | Service interno    | Métricas de host (CPU, memória, filesystem) |

Stack de monitoramento substitui containers dedicados anteriores e centraliza scraping em Prometheus Operator.

## Deploy da Stack de Monitoramento

Usamos o chart `kube-prometheus-stack`.

Valores customizados: `monitoring/kube-prometheus-stack-values.yaml`.

### Instalação (manual)

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring -f k8s/monitoring/kube-prometheus-stack-values.yaml
```

Grafana (login padrão admin / prom-operator) – altere a senha depois.

```bash
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
```

## Deploy Portainer

Automatizado via playbook `ansible/k8s_apps_playbook.yml` (aplica RBAC, Deployment, Secrets e Ingress). Manual (debug / laboratório):

```bash
kubectl apply -f k8s/portainer/portainer-rbac.yaml
kubectl apply -f k8s/portainer/portainer-deployment.yaml
```

Acesso:

- Ingress: `http://portainer.local` (após editar `/etc/hosts`)
- NodePort (fallback): `http://<IP_DO_NODE>:30900` (pode remover o Service `portainer-nodeport` se não precisar)

### Acesso simultâneo Docker + Kubernetes

O Deployment monta:

- `/var/run/docker.sock` (controle total Docker host)
- `/var/lib/docker/volumes` (RW) – permite gerenciamento de volumes

Argumento `--host=unix:///var/run/docker.sock` força detecção do Docker local. RBAC Kubernetes via ServiceAccount `portainer-sa` + ClusterRoleBinding com permissões amplas.

#### Segurança

Montar o docker.sock concede ao Portainer (e qualquer exploit) acesso root efetivo ao host. Considere:

- Usar Portainer Agent em vez de socket direto
- Tornar `/var/lib/docker/volumes` readOnly se apenas inspeção
- Restringir Ingress (TLS + auth extra)

## Deploy cAdvisor (separado)

O kube-prometheus-stack já coleta muitas métricas via kubelet/cAdvisor embutido. O DaemonSet dedicado opcional fornece métricas extras clássicas do cAdvisor.

```bash
kubectl apply -f k8s/monitoring/cadvisor-daemonset.yaml
```

Verificar target no Prometheus em: Status > Targets (job cadvisor).

## Ingress & Secrets

Ingress configurado em `ingress/ingress.yaml` com hosts:

| Host            | Serviço    | Namespace   |
|-----------------|-----------|-------------|
| portainer.local | portainer | tools       |
| grafana.local   | grafana   | monitoring  |

Certifique-se de adicionar entradas no `/etc/hosts` (máquina de acesso) apontando para o IP do nó k3s:

```bash
192.168.1.55 portainer.local grafana.local
```

### Credenciais

- Grafana: Secret `grafana-admin-secret` (chaves `admin-user`, `admin-password`). Referenciado via `existingSecret` nos values do chart.
- Portainer: Secret `portainer-admin-password` montado em `/run/secrets/portainer/password` e usado por `--admin-password-file`.

Altere os valores `CHANGE_ME_*` antes do deploy.

### Gestão de Secrets Locais (não versionadas)

Os arquivos de secrets reais NÃO são versionados. Foram fornecidos arquivos exemplo em `k8s/secrets/*.example.yaml`.

Passos:

1. Copiar exemplos:

  ```bash
  cp k8s/secrets/grafana-admin-secret.example.yaml k8s/secrets/grafana-admin-secret.yaml
  cp k8s/secrets/portainer-admin-password-secret.example.yaml k8s/secrets/portainer-admin-password-secret.yaml
  ```

1. Editar os arquivos reais e substituir `REPLACE_ME` por senhas fortes.

1. (Opcional Portainer) Gerar hash bcrypt:

  ```bash
  sudo apt install -y apache2-utils # se não tiver htpasswd
  htpasswd -bnBC 10 '' 'SENHA_FORTE' | tr -d ':
' > /tmp/hash.txt
  cat /tmp/hash.txt  # copie o hash e substitua o valor em password
  ```

  Obs: O Portainer aceita senha em texto puro no arquivo, mas hash é mais seguro em repouso.

1. Executar playbook. Ele validará a existência dos arquivos e falhará com mensagem amigável se faltarem.

Entradas adicionadas ao `.gitignore` garantem que `grafana-admin-secret.yaml` e `portainer-admin-password-secret.yaml` não sejam commitados.

## Automação via Ansible

Playbook: `ansible/k8s_apps_playbook.yml`

Principais etapas:

 1. Valida existência dos secrets locais reais
 2. Copia manifests para o servidor
 3. Copia kubeconfig protegido para `~/.kube/config` do usuário remoto
 4. Cria namespaces `monitoring` e `tools`
 5. Aplica secrets
 6. Instala Helm (se ausente) + repositórios
 7. Instala/atualiza `kube-prometheus-stack`
 8. Aplica RBAC Portainer (`portainer-rbac.yaml`)
 9. Aplica Deployment Portainer / cAdvisor / Ingress

Execução:

```bash
cd ansible
ansible-playbook -i inventory.ini k8s_apps_playbook.yml --ask-become-pass
```

## Próximos Passos / Melhorias

1. Configurar TLS (cert-manager + Let's Encrypt) e remover NodePort.
2. Ajustar retenção / recursos Prometheus conforme uso real.
3. Dashboards adicionais (IDs: 1860 node exporter, 893 cAdvisor, 16176 Portainer).
4. Backups PVCs (Velero ou snapshots local-path).
5. Hardening Portainer (remover docker.sock após fase híbrida ou migrar para Agent).
6. ServiceMonitor dedicado ao cAdvisor (refinar scrape / labels).
