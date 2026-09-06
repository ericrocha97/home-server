# Home Server — Bootstrap Slice 1

Repositório para provisionar um home server a partir de uma VM Ubuntu 26.04 limpa, com workflow lab-first. O Ansible é o único orquestrador e o mesmo código serve `lab` e `prod`.

## Visão geral do Slice 1

O Slice 1 prepara host e plataforma:

- Base Ubuntu segura (pacotes, timezone, SSH hardening, `/srv/home-server`).
- Docker Engine + Compose plugin sem daemon TCP.
- Cockpit no host em `9090`.
- k3s single-node pinado (`v1.36.3+k3s1`) com containerd, CoreDNS e ServiceLB.
- Traefik bundled em `kube-system` com file provider (`watch: true`) e Secret `traefik-tls` em `kube-system` alimentado por mkcert local.

Nada de aplicações futuras neste slice: sem Jenkins, n8n, Metabase, PostgreSQL, Portainer, Grafana, Prometheus ou restore de dados.

## Estrutura de arquivos

```
├── ansible/
│   ├── ansible.cfg
│   ├── site.yml                 # entry point único — ansible/site.yml
│   ├── requirements.yml
│   ├── requirements.txt
│   ├── inventories/
│   │   ├── lab/
│   │   │   ├── hosts.yml              # ignorado — copiar de hosts.example.yml
│   │   │   └── group_vars/all/          # ignorado — vars.yml (de all.example.yml) + vault.yml
│   │   └── prod/
│   │       ├── hosts.yml              # ignorado — copiar de hosts.example.yml
│   │       └── group_vars/all/          # ignorado — vars.yml (de all.example.yml) + vault.yml
│   ├── roles/{base,docker,cockpit,k3s,compose-services,docker-provider,firewall,monitoring,portainer,labmonitor-foundation,k8s-platform}/
│   ├── roles/xanmanning.k3s/    # ignorada — reinstalável via ansible-galaxy (requirements.yml)
│   └── secrets/               # ignorado — *.crt/*.key locais do mkcert
├── compose/                   # host-native Docker Compose (postgres, jenkins, n8n, metabase — Slice 2; docker-provider, portainer-agent — Slice 3)
├── k8s/
│   ├── ingress/README.md      # limite: rotas Docker via file provider, não via K8s Service
│   ├── labmonitor/rbac.yaml   # RBAC mínimo do futuro leitor (Slice 3, sem Deployment)
│   ├── monitoring/dashboards/ # 4 dashboards técnicos (host, docker, kubernetes, jenkins)
│   └── README.md              # plataforma Kubernetes
├── scripts/
│   ├── hosts/generate-hosts.sh
│   ├── hosts/lab.hosts.example
│   ├── hosts/prod.hosts.example
│   └── verify/slice3.sh       # verificação ponta a ponta do Slice 3 (somente leitura)
├── old/                       # arquivo local ignorado — stack antiga preservada localmente, nunca versionada
├── .venv/                      # ignorado — virtualenv do Ansible na máquina admin
└── .env.example
```

`old/` é arquivo local ignorado pelo `.gitignore`. A stack antiga foi movida para `old/ansible` e `old/k8s` localmente e não participa da nova execução.

## Pré-requisitos

- Python 3 na máquina de administração (o ambiente Ansible vive em `.venv/`, ignorado pelo Git).
- Acesso SSH com chave ao host alvo.
- `mkcert` instalado localmente para gerar TLS de `*.lab.arpa` / `*.home.arpa`.

## Execução limpa (do clone ao provisionamento)

### 1. Preparar o ambiente

```bash
git clone <repo> && cd home-server

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r ansible/requirements.txt

ansible-galaxy collection install -r ansible/requirements.yml
ansible-galaxy role install -r ansible/requirements.yml   # cria ansible/roles/xanmanning.k3s/ (ignorada)

export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
```

Sempre que abrir um terminal novo, reative o venv e reexporte o `ANSIBLE_CONFIG`.

### 2. Preparar inventário (exemplo lab)

```bash
cp ansible/inventories/lab/hosts.example.yml \
   ansible/inventories/lab/hosts.yml

mkdir -p ansible/inventories/lab/group_vars/all

cp ansible/inventories/lab/group_vars/all.example.yml \
   ansible/inventories/lab/group_vars/all/vars.yml
```

Layout resultante (tudo ignorado pelo Git):

```text
ansible/inventories/lab/
├── hosts.yml                 # ansible_host real do servidor
└── group_vars/
    └── all/
        ├── vars.yml          # variáveis públicas (lan_cidr, k3s_version, ...)
        └── vault.yml         # segredos (k3s_token)
```

Edite `hosts.yml` e `all/vars.yml` com os valores reais. Para `prod`, repita com o inventário `prod` (`base_domain: home.arpa`). O `base_domain` é `lab.arpa` em `lab`; o IP real (`ansible_host` / `server_lan_ip`) fica apenas nesses arquivos ignorados.

### 3. Configurar o Vault

```bash
ansible-vault create ansible/inventories/lab/group_vars/all/vault.yml
```

Conteúdo mínimo (gere o token com `openssl rand -hex 32`; a senha do Vault fica fora do repositório):

```yaml
k3s_token: "<token-gerado>"
```

### 4. Validar antes de executar

```bash
ansible-playbook --syntax-check ansible/site.yml

ansible-inventory -i ansible/inventories/lab/hosts.yml --graph --ask-vault-pass

ansible -i ansible/inventories/lab/hosts.yml all -m ping \
  --ask-become-pass --ask-vault-pass

yamllint ansible/ k8s/          # se instalado no venv
bash -n scripts/hosts/generate-hosts.sh
```

### 5. Gerar hosts auxiliares

```bash
./scripts/hosts/generate-hosts.sh lab
```

O script pedirá a senha do Vault automaticamente (decifra `group_vars/all/`) e imprime os mapeamentos — detalhes na seção "Hostnames" abaixo.

### 6. Executar o provisionamento

Bootstrap completo (lab):

```bash
ansible-playbook \
  -i ansible/inventories/lab/hosts.yml \
  -u "$HOME_SERVER_SSH_USER" \
  --ask-become-pass \
  --ask-vault-pass \
  ansible/site.yml
```

Execução por tags (exemplos):

```bash
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass ansible/site.yml --tags base
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass ansible/site.yml --tags docker
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass ansible/site.yml --tags cockpit
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags k3s
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags compose-services
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags firewall
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags monitoring
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags portainer
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags labmonitor-foundation
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags k8s-platform
```

Ordem intencional em `ansible/site.yml`: `base` → `docker` → `cockpit` → `k3s` → `compose-services` → `docker-provider` → `firewall` → `monitoring` → `portainer` → `labmonitor-foundation` → `k8s-platform`.

> **Janela transitória (primeiro bootstrap completo sem `--tags`)**: `compose-services` sobe containers com portas `18080/13001/15678/15432` publicadas **antes** de `firewall` aplicar UFW/DOCKER-USER. Essa janela existe também no Slice 1 (Cockpit `9090`/`6443` antes do firewall) e é aceita; a execução recomendada no laboratório é separar os passos e fechar a janela imediatamente:
>
> ```bash
> ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags compose-services
> ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags firewall,k8s-platform
> ```
>
> Agora inclui `15432` (DB) — por isso `firewall_postgres_direct_enable: false` + `DOCKER-USER DROP` padrão é crítico mesmo durante a janela. A execução completa continua suportada depois da primeira aceitação do fluxo separado. `compose-services` precisa estar antes de `firewall` (para que firewall abra portas de serviços que já existem) e antes de `k8s-platform` (para que Traefik aponte para backends já `healthy`). Se `firewall` estivesse antes, abriria portas sem alvo; se `k8s-platform` estivesse antes, Traefik healthcheck falharia até Compose subir.

### 7. Validar pós-provisionamento

No servidor:

```bash
sudo systemctl is-active docker cockpit.socket k3s
sudo ufw status verbose
sudo k3s kubectl get nodes
sudo k3s kubectl get pods -A
```

Acesso ao Cockpit:

```text
https://cockpit.lab.arpa        # via Traefik, cert mkcert confiável
https://<IP_DO_SERVIDOR>:9090   # fallback direto, cert self-signed (aviso esperado)
```

## TLS local com mkcert

Gerar certificados fora do Git (exemplo lab):

```bash
mkdir -p ansible/secrets
mkcert -install
mkcert \
  -cert-file ansible/secrets/lab-tls.crt \
  -key-file ansible/secrets/lab-tls.key \
  cockpit.lab.arpa \
  jenkins.lab.arpa \
  metabase.lab.arpa \
  n8n.lab.arpa \
  grafana.lab.arpa \
  prometheus.lab.arpa \
  portainer.lab.arpa
chmod 600 ansible/secrets/lab-tls.key
```

Produção usa `ansible/secrets/prod-tls.crt` / `prod-tls.key` para `*.home.arpa`. Os arquivos `*.crt`/`*.key` e `k3s_token` em `vault.yml` são ignorados e nunca commitados. Cada cliente que acessar `*.lab.arpa` / `*.home.arpa` precisa confiar na CA do mkcert.

O playbook valida a presença do par `{{ environment_name }}-tls.crt/.key` antes do deploy e aplica o Secret `kube-system/traefik-tls` idempotentemente.

## Hostnames e resolução de nomes

`lab.arpa` (lab) e `home.arpa` (prod) são os domínios base. O Ansible não modifica computadores clientes.

Use o gerador somente-leitura para obter os mapeamentos:

```bash
./scripts/hosts/generate-hosts.sh lab
./scripts/hosts/generate-hosts.sh prod
```

Cada comando imprime sete linhas no formato `<IP> <serviço>.<domínio>` (cockpit, grafana, jenkins, metabase, n8n, portainer, prometheus) usando o IP/domínio do inventário selecionado via `ansible-inventory --list`. Nada é escrito automaticamente em `/etc/hosts`.

Como o inventário contém um Vault (`group_vars/all/vault.yml`), o script pedirá a senha do Vault para decifrar as variáveis do grupo — comportamento esperado.

Copie manualmente a saída para o arquivo hosts do cliente quando quiser resolver por nome:

```bash
./scripts/hosts/generate-hosts.sh lab > /tmp/lab.hosts
# revisar /tmp/lab.hosts e anexar manualmente a /etc/hosts no cliente
```

Exemplos versionados em `scripts/hosts/lab.hosts.example` (`192.0.2.10`) e `scripts/hosts/prod.hosts.example` (`192.0.2.11`) são apenas documentação — não contêm IPs reais.

Alternativa: configurar DNS local (roteador, AdGuard Home, Pi-hole) com os mesmos hosts.

## Acesso direto (fallback IP:porta)

Sem hostname, o Cockpit permanece acessível diretamente pela porta publicada no host:

- `https://<IP_DO_SERVIDOR>:9090`

Slice 1 não abre portas de aplicações futuras nem NodePorts de aplicação; apenas `22`, `80`, `443`, `9090` e `6443` a partir de `lan_cidr`/`vpn_cidr`, além do forwarding CNI. Após Slice 2, Jenkins/n8n/Metabase também têm fallback direto via `server_lan_ip` (ex. `192.0.2.10:18080` para Jenkins, `15678` n8n, `13001` Metabase, `15432` PostgreSQL) mas restritos a LAN/VPN e `k3s_pod_cidr→host`.

## Slice 2 — Compose

Redes `home-server-automation` e `home-server-data` criadas pelo Ansible.
Serviços vazios: PostgreSQL `15432`, Jenkins `18080`, n8n `15678`, Metabase `13001`.
Jenkins usa imagem custom local com tag derivada do fingerprint do Dockerfile/entrypoint/base image (docker.io + curl + gh) com dockersock RW montado via `/var/run/docker.sock:/var/run/docker.sock` e bootstrap de segurança `init.groovy.d/01-admin.groovy` — segunda exceção privilegiada além do Portainer Agent (spec-mãe). Acesso direto via `server_lan_ip:porta` e HTTPS via `jenkins|n8n|metabase.<base_domain>` pelo Traefik file provider. Nenhum restore é executado; Jenkins sobe vazio mas já autenticado (403 para anônimo). Portas liberadas apenas para LAN/VPN e `k3s_pod_cidr→host`, e `18080` só após verificação de auth.

Detalhes:

- Jenkins `8080→18080`, n8n `5678→15678`, Metabase `3000→13001`, PostgreSQL `5432→15432`.
- Jenkins healthcheck via `curl -fsS http://localhost:8080/login`; PostgreSQL via `pg_isready`; n8n `/healthz`; Metabase `/api/health`.
- Volumes bind em `/srv/home-server/data/<serviço>` com ownership por UID/GID (postgres 999, jenkins/n8n 1000, metabase 2000) e logging `json-file` `10m`/`3`.
- Hostnames HTTPS (via Traefik file provider + `traefik-tls`): `https://jenkins.lab.arpa`, `https://n8n.lab.arpa`, `https://metabase.lab.arpa` (prod `*.home.arpa`). Exemplo placeholder lab: `192.0.2.10` para `jenkins.lab.arpa` etc. — nunca usar IP real em docs versionados, apenas placeholder `192.0.2.10`/`192.0.2.11` e runtime `server_lan_ip`.
- Verificação pós-bootstrap: `curl -s -o /dev/null -w "%{http_code}" http://192.0.2.10:18080/login` deve retornar `403` para anônimo (autenticado), não `200` sem auth.
- Jenkins clean baseline é one-shot com steady-state no-op: o reset destrutivo (`/srv/home-server/data/jenkins`) roda apenas quando o marcador `/srv/home-server/data/jenkins/.clean-baseline-complete` está ausente **e** `jenkins_clean_reset_confirmed: true` no inventário real (exemplos mantêm `false`). Reruns com marcador presente são no-ops; preflight limpo sem confirmação pula com aviso; sujo sem confirmação falha fechado sem apagar dados. Para reverter o one-shot, remova o marcador e confirme explicitamente.

### Shared automation database (`automation`) — extensão Slice 2 (Tasks 1–4)

PostgreSQL continua apenas em `home-server-data`; n8n usa ambas as redes, Jenkins permanece em `home-server-automation`, Metabase em `home-server-data`. O Ansible cria database `automation` com owner `automation_writer` e roles `automation_writer`/`automation_reader`; n8n recebe contrato writer e Metabase contrato reader. Nenhuma tabela de aplicação, workflow n8n ou dashboard Metabase é criada aqui — apenas infraestrutura.

Topologia exata:

```text
Jenkins --home-server-automation--> n8n
n8n --home-server-data / automation_writer--> PostgreSQL / automation
Metabase --home-server-data / automation_reader--> PostgreSQL / automation
n8n --home-server-data / n8n--> PostgreSQL / n8n
Metabase --home-server-data / metabase--> PostgreSQL / metabase
```

Jenkins has no direct PostgreSQL route, and `automation` is for shared CI/CD and automation data only. `automation` é exclusivamente para dados compartilhados de CI/CD/automação; manter `n8n` e `metabase` como databases internas separadas — não colocar dados de CI/CD nelas.

Permissões: `automation_writer` tem `CONNECT` em `automation`, `USAGE, CREATE` em `public`, `ALL PRIVILEGES` em tabelas/sequências existentes e default privileges para objetos futuros; `automation_reader` tem `CONNECT`, `USAGE` em `public`, `SELECT` em tabelas existentes, `USAGE, SELECT` em sequências + default privileges correspondentes. `automation_reader` nunca recebe `CREATE`/`INSERT`/`UPDATE`/`DELETE` nem ownership. `REVOKE ALL` de `PUBLIC` em database e schema.

Vault — adicione ao Vault criptografado do ambiente (`ansible/inventories/<env>/group_vars/all/vault.yml`, 0600, `ansible-vault`, ignorado) antes de reexecutar Ansible. Ambas as variáveis devem ser senhas fortes distintas entre si e de `postgres_superuser_password`, `postgres_n8n_password`, `postgres_metabase_password`; o Ansible valida não-vazio, distinção e nunca loga valores (`no_log: true`):

```yaml
postgres_automation_writer_password: "<distinct strong password>"
postgres_automation_reader_password: "<distinct strong password>"
```

Sem essas duas variáveis o play falha na validação inicial.

Migração aditiva (preserva dados n8n/metabase existentes — adiciona apenas database/roles/contrato):

```bash
ansible-playbook -i ansible/inventories/lab/hosts.yml \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass \
  ansible/site.yml --tags compose-services
```

Em seguida reaplica firewall + Traefik:

```bash
ansible-playbook -i ansible/inventories/lab/hosts.yml \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass \
  ansible/site.yml --tags firewall,k8s-platform
```

O primeiro comando preserva os dados existentes de n8n e Metabase e adiciona apenas a shared database/roles e o contrato de ambiente. O segundo restaura firewall e Traefik. Execução idempotente; segundo estágio já existia antes.

Conexão — n8n segunda credencial PostgreSQL (além de `DB_POSTGRESDB_*` que continua em `n8n`): host `postgres`, port `5432`, database `automation`, user `automation_writer` (password do Vault → `AUTOMATION_DB_PASSWORD` no container; `AUTOMATION_DB_HOST=postgres`, `AUTOMATION_DB_PORT=5432`, `AUTOMATION_DB_NAME=automation`).

Metabase data source `automation` (mesmo host/port/database, user `automation_reader`; `MB_DB_*` continua em `metabase` e precisa ser configurado via UI/API de administração do Metabase — não é criada automaticamente): host `postgres`, port `5432`, database `automation`, user `automation_reader`.

Composes expõem `AUTOMATION_DB_PASSWORD: "${AUTOMATION_DB_PASSWORD:?required}"` (`n8n` com `automation_writer`, `metabase` com `automation_reader`); templates `ansible/roles/compose-services/templates/n8n.env.j2` e `metabase.env.j2` renderizam com as variáveis Vault correspondentes. Exemplos sanitizados em `compose/n8n/.env.example` (`changeme-automation-writer`) e `compose/metabase/.env.example` (`changeme-automation-reader`); `.env` gerado no host contém valores Vault reais e é ignorado. No application tables are created by this task — `AUTOMATION_DB_*` é contrato de conexão apenas.

Verificação em lab (requer Vault e host vivo) — documentado para execução no host lab quando disponível (nunca imprimir `.env` gerado):

```bash
sudo docker exec postgres psql -X -U postgres -d postgres -c \
  "SELECT datname FROM pg_database WHERE datname IN ('n8n', 'metabase', 'automation') ORDER BY datname"
# esperado: automation | metabase | n8n

sudo docker exec postgres psql -X -U postgres -d postgres -c \
  "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname IN ('n8n', 'metabase', 'automation_writer', 'automation_reader') ORDER BY rolname"
# esperado: 4 roles, todos rolcanlogin = t

sudo docker exec postgres psql -X -U postgres -d automation -c \
  "SELECT has_schema_privilege('automation_reader', 'public', 'USAGE') AS reader_usage, has_schema_privilege('automation_reader', 'public', 'CREATE') AS reader_create"
# esperado: reader_usage = t, reader_create = f

sudo docker inspect n8n --format '{{json .NetworkSettings.Networks}}'
# esperado: contém home-server-automation e home-server-data
sudo docker inspect metabase --format '{{json .NetworkSettings.Networks}}'
# esperado: contém apenas home-server-data
sudo docker inspect jenkins --format '{{json .NetworkSettings.Networks}}'
# esperado: contém apenas home-server-automation (sem home-server-data) — Jenkins has no direct PostgreSQL route
sudo docker exec jenkins curl -fsS http://n8n:5678/healthz >/dev/null
# esperado: 0 (Jenkins alcança n8n via home-server-automation, sem rota PostgreSQL)
```

## Slice 3 — Platform foundation (camada final de infraestrutura)

Slice 3 prepara a última camada de infraestrutura para um futuro `labmonitor-api` e não deploya nenhum produto: sem API LabMonitor, sem frontend, sem dashboards de produto, sem jobs de exemplo, sem workflows e sem restore.

O que o Slice 3 entrega:

- Observabilidade técnica em k3s (`monitoring`): `kube-prometheus-stack` `88.6.1` com Prometheus (retenção `15d`, PVC `20Gi` em `local-path`) e Grafana (PVC `5Gi`) mais 4 dashboards técnicos (`host`, `docker`, `kubernetes`, `jenkins`). NodePorts humanos fixos: Grafana `30300`, Prometheus `30909`.
- Provider Docker read-only no host (`docker-provider`): proxy `tecnativa/docker-socket-proxy:0.3.0` com mount `:ro` e contrato GET-only (`POST=0` e seções de escrita revogadas), publicado apenas em `server_lan_ip:12375` para o `k3s_pod_cidr` — sem Ingress, NodePort ou hostname, negado para LAN/VPN/Internet.
- Exporter de métricas Docker em k3s (`docker-metrics-exporter:1.0.0`, ClusterIP `9797`): consome apenas `http://server_lan_ip:12375`, sem mount de socket, com ServiceMonitor para o Prometheus.
- Providers Jenkins (Compose, porta `18080` autenticada): usuários read-only `labmonitor-api` e `prometheus-scraper` com credenciais separadas via Vault e Groovy init-script; `/prometheus/` para scrape, REST autenticado para leitura, mutação e administração negadas.
- Portainer (`portainer`, NodePort `30900`): Server em k3s com ServiceAccount dedicada mais Kubernetes Agent (mesmo namespace) e Docker Agent no host (`server_lan_ip:9001`, exceção administrativa com mount RW em projeto Compose separado). O proxy read-only continua sendo o único caminho Docker para monitoramento.
- Fundação LabMonitor (`labmonitor`, somente identidade): ServiceAccount `labmonitor-api` com `get`/`list`/`watch` em nodes/pods/services/namespaces/deployments e `get` nos ConfigMaps `labmonitor-catalog`/`labmonitor-provider-config`; sem leitura de Secrets, sem `cluster-admin`, sem Deployment.
- Discovery declarativo: labels `labmonitor.*` no Docker (jenkins/n8n/metabase), metadados nos Services (grafana/prometheus/portainer), catálogo (cockpit) e provider-config (4 endpoints internos) — 7 aplicações navegáveis no total, cada ambiente apenas com seu domínio (`.lab.arpa` vs `.home.arpa`).
- Rotas Traefik finais: file provider para Compose/Cockpit, Ingress para Grafana/Prometheus/Portainer; providers seguem ClusterIP-only.

### Validação estática (sem SSH, sem Vault)

```bash
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
ansible-playbook --syntax-check ansible/site.yml
bash -n scripts/hosts/generate-hosts.sh
bash -n scripts/verify/slice3.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
docker compose --env-file compose/postgres/.env.example -f compose/postgres/compose.yaml config >/dev/null
docker compose --env-file compose/jenkins/.env.example -f compose/jenkins/compose.yaml config >/dev/null
docker compose --env-file compose/n8n/.env.example -f compose/n8n/compose.yaml config >/dev/null
docker compose --env-file compose/metabase/.env.example -f compose/metabase/compose.yaml config >/dev/null
docker compose --env-file compose/docker-provider/.env.example -f compose/docker-provider/compose.yaml config >/dev/null
docker compose --env-file compose/portainer-agent/.env.example -f compose/portainer-agent/compose.yaml config >/dev/null
git diff --check
git status --short
```

Os `.env.example` sanitizados carregam apenas placeholders (`local/*:lint`, `changeme-*`, `192.0.2.10`); o Ansible gera os `.env` reais no host (0600, ignorados) a partir do Vault. Nenhum arquivo versionado contém segredo, IP real, tag mutável ou mount de socket fora das exceções contratadas.

### Verificação ponta a ponta no host lab (requer Vault + host vivo)

Fluxo completo com o Vault do ambiente, depois o script de verificação:

```bash
ansible-playbook -i ansible/inventories/lab/hosts.yml \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass \
  ansible/site.yml

SERVER_LAN_IP="<ip-do-servidor>" \
JENKINS_LABMONITOR_API_TOKEN="<token-do-vault>" \
GRAFANA_ADMIN_PASSWORD="<senha-do-vault>" \
./scripts/verify/slice3.sh
```

O script (`set -Eeuo pipefail`, `KUBECONFIG` ou `/etc/rancher/k3s/k3s.yaml`) é somente leitura: credenciais vêm do ambiente ou de Secrets vivos e nunca são impressas; o firewall nunca é alterado. Ele verifica:

- Pods `monitoring`/`portainer` Ready; namespace/ServiceAccount/ConfigMaps/Secrets do `labmonitor`; PVCs Prometheus/Grafana `Bound`; retenção `15d` (ou override do inventário); targets UP (node-exporter, kubelet/cAdvisor, kube-state-metrics, Docker exporter, Jenkins).
- Proxy Docker: GETs a partir de pod k3s autorizado OK (`/version`, `/info`, `/containers/json`), POST de mutação rejeitado; exporter `/metrics` com as séries `labmonitor_docker_container_*` e sem socket.
- Jenkins: REST autenticado retorna JSON válido, mutação de build e `/manage` negados, anônimo negado; k3s → `18080` autenticado OK via probe com Secret reference.
- Grafana: datasource Prometheus ativo + 4 ConfigMaps de dashboards; Portainer Server alcança o Docker Agent e o Kubernetes Agent.
- Discovery: labels Docker (jenkins/n8n/metabase), Services (grafana/prometheus/portainer), catálogo + provider-config normalizam para as 7 entradas, sem URL navegável em postgres/providers e sem vazamento de domínio entre ambientes.
- Negativas: identidade `labmonitor-api` não lê Secrets nem cria pods; `12375`/`9797`/`9001` sem NodePort/Ingress; UFW + DOCKER-USER negam LAN/VPN em `12375`; nenhuma API LabMonitor deployada.

A prova negativa a partir da LAN/VPN precisa de um cliente separado (o host não prova negação remota sozinho):

```bash
curl --connect-timeout 5 "http://<server-lan-ip>:12375/version"   # deve falhar (timeout/recusa)
```

Se o probe k3s chegar com endereço de origem diferente do IP do pod (SNAT), o script registra o comportamento: mantém-se o allow estreito do `k3s_pod_cidr` e a negação da LAN — nunca se abre exceção para fazer o teste passar.

## O que os Slices 1–2 não fazem

- Não instala CasaOS.
- Não cria Services ou EndpointSlices legados para rotear serviços host-native; serviços Compose (Jenkins, n8n, Metabase) são roteados diretamente pelo file provider do Traefik bundled, sem objetos Kubernetes (`k8s/ingress/README.md`).
- Não executa restore automático de dados; Slice 2 sobe serviços **vazios** (PostgreSQL, Jenkins, n8n, Metabase) sem dados de backup.
- Não modifica automaticamente `/etc/hosts` de clientes.

## Próximos slices

- **Slice 2 — Compose** (concluído): redes `home-server-automation`/`home-server-data`, PostgreSQL `15432`, Jenkins `18080` (imagem custom), n8n `15678`, Metabase `13001`, file provider para 3 backends — ver seção acima.
- **Slice 3 — Platform foundation** (concluído, final infrastructure): observabilidade técnica (Prometheus, Grafana + dashboards), providers read-only (Docker socket proxy, Docker metrics exporter, Jenkins providers), administração Portainer, fundação de discovery (RBAC + provider endpoints + catálogo) e rotas Traefik finais — file provider para Compose/Cockpit, Ingress para Grafana/Prometheus/Portainer. Nenhum produto é deployado neste slice. Verificação ponta a ponta em `scripts/verify/slice3.sh` — ver seção Slice 3 acima.
- Restore e automações adicionais vivem fora deste projeto.

## Segurança e notas

- Docker exposto apenas via socket Unix; sem listeners `2375`/`2376`.
- UFW com `DEFAULT_FORWARD_POLICY="ACCEPT"` para o CNI; política de entrada `deny` e allowlist restrita ao Slice 1.
- Não commitar IPs reais de produção, segredos ou conteúdos de certificados. O inventário real e `vault.yml` permanecem ignorados.
- Remover NodePorts legados após Ingress estável (nenhum criado no Slice 1).
