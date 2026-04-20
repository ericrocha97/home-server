# Configuração Ansible para Home Server

Este repositório contém playbooks Ansible e manifests Kubernetes para configurar um home server com k3s, observabilidade (Prometheus/Grafana), Portainer e integração de serviços externos do host via Traefik.

## Estrutura de Arquivos

- `ansible/`: Diretório principal com playbooks.
  - `playbook.yml`: Setup base (pacotes essenciais, Docker opcional, utilitários).
  - `k3s_playbook.yml`: Instala e configura k3s (via role `xanmanning.k3s`).
  - `k8s_apps_playbook.yml`: Implanta stack Kubernetes (Portainer + kube-prometheus-stack + cAdvisor + external-services + ingress TLS).
  - `casaos_playbook.yml`: Instala CasaOS nativo no Ubuntu e fixa porta `8081`.
  - `nvm_node_pnpm_playbook.yml`: Instala NVM, Node LTS e pnpm.
  - `zsh_starship_playbook.yml`: Instala Zsh, Oh My Zsh e Starship.
  - `sdkman_playbook.yml`: Instala SDKMAN! e dependências.
  - `inventory.ini`: Inventário de hosts.
  - `secrets.yml`: Reservado para uso futuro com Ansible Vault.
- `k8s/`: Manifests da stack.
  - `external-services/`: Services sem selector + EndpointSlices para apps fora do cluster.
  - `ingress/`: Ingress separados (`tools` e `monitoring`) com TLS local.
  - `monitoring/`, `portainer/`, `secrets/`: componentes da stack.

## Arquitetura de acesso local

- Ponto único de entrada em `80/443`: Traefik do k3s.
- CasaOS continua rodando nativo no host em `8081`.
- Serviços externos ao cluster (CasaOS/Jenkins/Metabase/n8n) são roteados via:
  - `Service` Kubernetes sem selector
  - `EndpointSlice` apontando para `192.168.100.113` e porta publicada no host
- Domínio padrão local: `home.arpa` (não usar `.local` para estes acessos).

Hosts usados:

- `casaos.home.arpa`
- `jenkins.home.arpa`
- `metabase.home.arpa`
- `n8n.home.arpa`
- `portainer.home.arpa`
- `grafana.home.arpa`

## Pré-requisitos

1. **Ansible instalado** na máquina local.
2. **Acesso SSH** ao servidor alvo com chave configurada.
3. **Coleções e roles Ansible**:

   ```bash
   ansible-galaxy collection install kubernetes.core
   ansible-galaxy role install xanmanning.k3s
   ansible-galaxy collection install community.docker
   ```

4. **mkcert** instalado na máquina de administração (para HTTPS local).

## HTTPS local com mkcert (home.arpa)

Gerar certificado e chave usados pelo playbook:

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

Notas:

- Os arquivos `ansible/secrets/local-home-arpa-tls.crt` e `ansible/secrets/local-home-arpa-tls.key` são locais e não versionados.
- Cada cliente que acessar os hosts `*.home.arpa` precisa confiar na CA raiz do mkcert, senão o browser exibirá alerta de certificado.

## Portainer para Kubernetes + Docker (persistente)

O deploy atual deixa o Portainer Server no namespace `tools` e adiciona:

- Portainer Agent Kubernetes no namespace `portainer`
- Portainer Agent Docker no host (container `portainer_agent` em `192.168.100.113:9001`)
- `AGENT_SECRET` compartilhado entre server e agents

Antes de executar `k8s_apps_playbook.yml`, crie um segredo forte local:

```bash
openssl rand -hex 32 > ansible/secrets/portainer-agent-secret.txt
chmod 600 ansible/secrets/portainer-agent-secret.txt
```

Depois de aplicar o playbook, no Portainer UI:

1. Add environment -> Kubernetes -> Agent
   - Address: `portainer-agent.portainer.svc.cluster.local:9001`
2. Add environment -> Docker Standalone -> Agent
   - Address: `192.168.100.113:9001`

Sem protocolo (`http://`/`https://`) no campo de endereço.

## Como executar os playbooks

Execute sempre a partir de `ansible/`.

1. **Configuração inicial do servidor**

   ```bash
   ansible-playbook -i inventory.ini playbook.yml --ask-become-pass
   ```

2. **Instalar k3s**

   ```bash
   ansible-playbook -i inventory.ini k3s_playbook.yml --ask-become-pass
   ```

3. **Instalar CasaOS (nativo no host)**

   ```bash
   ansible-playbook -i inventory.ini casaos_playbook.yml --ask-become-pass
   ```

   O CasaOS permanece no host em `8081`, sem competir com Traefik em `80/443`.

4. **Deploy da stack k8s (Ingress TLS + serviços externos)**

   Antes de rodar:

   - Crie os secrets reais a partir de `k8s/secrets/*.example.yaml`.
   - Gere os arquivos TLS do mkcert em `ansible/secrets/`.

   ```bash
   ansible-playbook -i inventory.ini k8s_apps_playbook.yml --ask-become-pass
   ```

5. **Ambiente de desenvolvimento (opcional)**

   ```bash
   ansible-playbook -i inventory.ini nvm_node_pnpm_playbook.yml --ask-become-pass
   ansible-playbook -i inventory.ini zsh_starship_playbook.yml --ask-become-pass
   ansible-playbook -i inventory.ini sdkman_playbook.yml --ask-become-pass
   ```

## Acesso aos serviços

Após o deploy com `k8s_apps_playbook.yml`:

- CasaOS: `https://casaos.home.arpa`
- Jenkins: `https://jenkins.home.arpa`
- Metabase: `https://metabase.home.arpa`
- n8n: `https://n8n.home.arpa`
- Portainer: `https://portainer.home.arpa`
- Grafana: `https://grafana.home.arpa`

Fallback opcional atual:

- Portainer NodePort: `http://<IP_DO_SERVIDOR>:30900`

## DNS local / resolução de nomes

Opção rápida (`/etc/hosts` no cliente):

```text
192.168.100.113 casaos.home.arpa jenkins.home.arpa metabase.home.arpa n8n.home.arpa portainer.home.arpa grafana.home.arpa
```

Opção recomendada: configurar DNS local (roteador, AdGuard Home, Pi-hole) com os mesmos hosts.

`*.local` está descontinuado para estes acessos.

## Segurança e notas importantes

- Portainer agora opera com separação de responsabilidades:
  - Portainer Server no namespace `tools`, sem mount direto de `docker.sock`
  - Portainer Agent Kubernetes no namespace `portainer`
  - Portainer Agent Docker no host em `192.168.100.113:9001`
- `AGENT_SECRET` é obrigatório para vínculo entre server e agents.
- Como o Docker Agent usa o socket do Docker do host, o endpoint Docker ainda é privilegiado e deve ficar restrito à rede local confiável.
- Este fluxo trata apenas de serviços **HTTP/HTTPS** atrás de Ingress.
- PostgreSQL puro (`15432`/`5432`) **não** deve ser exposto por Ingress HTTP; se precisar TLS para banco, tratar separadamente com solução TCP/TLS apropriada.
