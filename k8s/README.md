# Manifests Kubernetes (k3s)

Esta pasta concentra os manifests da stack no k3s e o roteamento HTTPS local para serviços dentro e fora do cluster.

## Visão geral da arquitetura

- Traefik do k3s é o único ponto de entrada em `80/443`.
- CasaOS continua nativo no Ubuntu (porta `8081`) e é publicado via Ingress com `Service` sem selector + `EndpointSlice`.
- Jenkins, Metabase e n8n (host/Docker) seguem o mesmo padrão em `k8s/external-services/`.
- Portainer (namespace `tools`) e Grafana (namespace `monitoring`) continuam dentro do cluster.
- Domínio local padrão: `*.home.arpa`.
- `.local` foi descontinuado para estes acessos.

## Estrutura relevante

- `k8s/external-services/`
  - `README.md` (referência do fluxo)
  - manifests concretos são renderizados em runtime pelo playbook a partir de `ansible/templates/external-services/*.yaml.j2`
- `k8s/ingress/`
  - `tools-ingress.yaml`
  - `monitoring-ingress.yaml`
- `k8s/portainer/`
- `k8s/monitoring/`
- `k8s/secrets/`

## Mapeamento de serviços e portas

| Host | Serviço backend | Namespace | Porta de destino |
|---|---|---|---|
| `casaos.home.arpa` | `casaos-external` | `tools` | host `8081` |
| `jenkins.home.arpa` | `jenkins-external` | `tools` | host `18080` |
| `metabase.home.arpa` | `metabase-external` | `tools` | host `13001` |
| `n8n.home.arpa` | `n8n-external` | `tools` | host `15678` |
| `portainer.home.arpa` | `portainer` | `tools` | service `9000` |
| `grafana.home.arpa` | `monitoring-grafana` | `monitoring` | service `80` |

IP do servidor usado nos EndpointSlices:

- definido em runtime por variável (`SERVER_LAN_IP`) ou por `ansible_host` do inventory

## TLS local com mkcert

O TLS local usa secret Kubernetes `local-home-arpa-tls` nos namespaces `tools` e `monitoring`.

Arquivos esperados localmente (máquina de administração):

- `ansible/secrets/local-home-arpa-tls.crt`
- `ansible/secrets/local-home-arpa-tls.key`

Comando sugerido:

```bash
mkcert -install
mkcert \
  -cert-file ansible/secrets/local-home-arpa-tls.crt \
  -key-file ansible/secrets/local-home-arpa-tls.key \
  casaos.home.arpa \
  jenkins.home.arpa \
  metabase.home.arpa \
  n8n.home.arpa \
  portainer.home.arpa \
  grafana.home.arpa
mkcert -CAROOT
```

Importante: cada cliente que acessa `*.home.arpa` deve confiar na CA raiz do mkcert.

## Portainer para Kubernetes e Docker

O setup mantém o Portainer Server em `tools`, com dois agents:

- Kubernetes Agent (`namespace: portainer`)
  - service: `portainer-agent.portainer.svc.cluster.local:9001`
- Docker Agent no host
  - container: `portainer_agent`
  - bind: `<SERVER_LAN_IP>:9001`

Para hardening e vínculo entre server e agents, é obrigatório `AGENT_SECRET`.

Arquivo local (não versionado):

- `ansible/secrets/portainer-agent-secret.txt`

Gerar:

```bash
openssl rand -hex 32 > ansible/secrets/portainer-agent-secret.txt
chmod 600 ansible/secrets/portainer-agent-secret.txt
```

O playbook cria o secret `portainer-agent-secret` nos namespaces `tools` e `portainer`.

Após deploy, adicionar os environments no Portainer UI:

1. Kubernetes -> Agent -> `portainer-agent.portainer.svc.cluster.local:9001`
2. Docker Standalone -> Agent -> `<SERVER_LAN_IP>:9001`

Não incluir protocolo no campo de endereço.

## Resolução de nomes

Opção rápida com `/etc/hosts`:

```text
<SERVER_LAN_IP> casaos.home.arpa jenkins.home.arpa metabase.home.arpa n8n.home.arpa portainer.home.arpa grafana.home.arpa
```

Opção recomendada: DNS local (roteador, AdGuard Home, Pi-hole).

## Credenciais e secrets

- Grafana: `k8s/secrets/grafana-admin-secret.yaml` (não versionado)
- Portainer: `k8s/secrets/portainer-admin-password-secret.yaml` (não versionado)

Arquivos de exemplo:

- `k8s/secrets/grafana-admin-secret.example.yaml`
- `k8s/secrets/portainer-admin-password-secret.example.yaml`

## Validação de manifests (sem aplicar)

Observação: os manifests concretos de `external-services` são renderizados pelo playbook a partir de templates Jinja2 usando `SERVER_LAN_IP` ou `ansible_host`.

```bash
kubectl apply --dry-run=client -f k8s/ingress/tools-ingress.yaml
kubectl apply --dry-run=client -f k8s/ingress/monitoring-ingress.yaml
kubectl create --dry-run=client -f k8s/portainer/portainer-deployment.yaml
```

## Automação via Ansible

Playbook principal: `ansible/k8s_apps_playbook.yml`

Fluxo atualizado:

1. Valida secrets reais (`grafana-admin-secret.yaml`, `portainer-admin-password-secret.yaml`)
2. Valida certificados locais mkcert (`local-home-arpa-tls.crt`, `local-home-arpa-tls.key`)
3. Copia manifests para o servidor
4. Garante namespaces `tools` e `monitoring`
5. Aplica secrets de aplicação e TLS (`local-home-arpa-tls`)
6. Instala/atualiza kube-prometheus-stack
7. Aplica Portainer, cAdvisor, external-services e ingresses novos
8. Remove ingresses/recursos legados com `.local` (quando existentes)

Execução:

```bash
cd ansible
ansible-playbook -i inventory.ini k8s_apps_playbook.yml --ask-become-pass
```

## Validação pós-deploy

```bash
kubectl get ingress -A
kubectl get svc -n tools
kubectl get endpointslice -n tools
kubectl get secret -n tools | grep local-home-arpa-tls
kubectl get secret -n monitoring | grep local-home-arpa-tls

curl -vk https://casaos.home.arpa
curl -vk https://jenkins.home.arpa
curl -vk https://metabase.home.arpa
curl -vk https://n8n.home.arpa
curl -vk https://portainer.home.arpa
curl -vk https://grafana.home.arpa
```

## Rollback

```bash
kubectl delete -f k8s/external-services/
kubectl delete -f k8s/ingress/tools-ingress.yaml
kubectl delete -f k8s/ingress/monitoring-ingress.yaml
kubectl delete secret local-home-arpa-tls -n tools
kubectl delete secret local-home-arpa-tls -n monitoring
```

Se necessário, reaplique manifests antigos (somente em cenário de rollback planejado).

## Segurança

- Portainer Server (namespace `tools`) está sem mount direto de `docker.sock`; o acesso Docker ocorre via `portainer_agent` com `AGENT_SECRET`.
- O endpoint Docker continua privilegiado porque o Docker Agent usa o socket do host; mantenha acesso restrito à rede local confiável.
- PostgreSQL puro (`5432`/`15432`) não deve ser exposto por Ingress HTTP.
- Se precisar TLS para PostgreSQL, trate em fluxo separado com solução TCP/TLS apropriada.
