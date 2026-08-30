# Home Server — Bootstrap Slice 1

Repositório para provisionar um home server a partir de uma VM Ubuntu 26.04 limpa, com workflow lab-first. O Ansible é o único orquestrador e o mesmo código serve `lab` e `prod`.

## Visão geral do Slice 1

O Slice 1 prepara host e plataforma:

- Base Ubuntu segura (pacotes, timezone, SSH hardening, `/srv/home-server`).
- Docker Engine + Compose plugin sem daemon TCP.
- Cockpit no host em `9090`.
- k3s single-node pinado (`v1.36.3+k3s1`) com containerd, CoreDNS e ServiceLB.
- Traefik bundled em `kube-system` com file provider (`watch: true`) e Secret `traefik-tls` em `kube-system` alimentado por mkcert local.

Nada de aplicações futuras neste slice: sem Jenkins, n8n, Metabase, PostgreSQL, Portainer, Grafana, Prometheus, Glance ou restore de dados.

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
│   ├── roles/{base,docker,cockpit,k3s,compose-services,firewall,k8s-platform}/
│   ├── roles/xanmanning.k3s/    # ignorada — reinstalável via ansible-galaxy (requirements.yml)
│   └── secrets/               # ignorado — *.crt/*.key locais do mkcert
├── compose/                   # host-native Docker Compose (postgres, jenkins, n8n, metabase) — Slice 2
├── k8s/
│   ├── ingress/README.md      # limite: rotas Docker via file provider, não via K8s Service
│   └── README.md              # plataforma Kubernetes
├── scripts/
│   ├── hosts/generate-hosts.sh
│   ├── hosts/lab.hosts.example
│   └── hosts/prod.hosts.example
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
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags k8s-platform
```

Ordem intencional em `ansible/site.yml`: `base` → `docker` → `cockpit` → `k3s` → `compose-services` → `firewall` → `k8s-platform`.

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
  portainer.lab.arpa \
  glance.lab.arpa
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

Cada comando imprime oito linhas no formato `<IP> <serviço>.<domínio>` (cockpit, glance, grafana, jenkins, metabase, n8n, portainer, prometheus) usando o IP/domínio do inventário selecionado via `ansible-inventory --list`. Nada é escrito automaticamente em `/etc/hosts`.

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

## O que os Slices 1–2 não fazem

- Não instala CasaOS.
- Não cria Services ou EndpointSlices legados para rotear serviços host-native; serviços Compose (Jenkins, n8n, Metabase) são roteados diretamente pelo file provider do Traefik bundled, sem objetos Kubernetes (`k8s/ingress/README.md`).
- Não executa restore automático de dados; Slice 2 sobe serviços **vazios** (PostgreSQL, Jenkins, n8n, Metabase) sem dados de backup.
- Não modifica automaticamente `/etc/hosts` de clientes.

## Próximos slices

- **Slice 2 — Compose** (concluído): redes `home-server-automation`/`home-server-data`, PostgreSQL `15432`, Jenkins `18080` (imagem custom), n8n `15678`, Metabase `13001`, file provider para 3 backends — ver seção acima.
- **Slice 3**: Dashboard Glance e observabilidade (Portainer, Grafana, Prometheus) sobre a fundação do Slice 1–2.
- **Slices seguintes**: restore e automações adicionais.

## Segurança e notas

- Docker exposto apenas via socket Unix; sem listeners `2375`/`2376`.
- UFW com `DEFAULT_FORWARD_POLICY="ACCEPT"` para o CNI; política de entrada `deny` e allowlist restrita ao Slice 1.
- Não commitar IPs reais de produção, segredos ou conteúdos de certificados. O inventário real e `vault.yml` permanecem ignorados.
- Remover NodePorts legados após Ingress estável (nenhum criado no Slice 1).
