# Compose

Projetos host-native. Dados persistentes ficam em `/srv/home-server/data/<service>` fora do Git.

## Topologia — shared `automation` database

PostgreSQL roda apenas em `home-server-data`; n8n usa ambas as redes externas, Jenkins permanece em `home-server-automation`, Metabase permanece em `home-server-data`. O Ansible cria `automation`, `automation_writer` e `automation_reader`; n8n recebe o contrato writer e Metabase o contrato reader. Nenhuma tabela de aplicação, workflow n8n, dashboard Metabase, Service ou EndpointSlice é criada nesta mudança.

Mapeamento exato (topologia):

```text
Jenkins --home-server-automation--> n8n
n8n --home-server-data / automation_writer--> PostgreSQL / automation
Metabase --home-server-data / automation_reader--> PostgreSQL / automation
n8n --home-server-data / n8n--> PostgreSQL / n8n
Metabase --home-server-data / metabase--> PostgreSQL / metabase
```

Jenkins has no direct PostgreSQL route, and `automation` is for shared CI/CD and automation data only. Ou seja: Jenkins não tem rota direta para PostgreSQL (`home-server-data` não está anexada a Jenkins); `automation` é exclusivamente para dados compartilhados de CI/CD e automação — não colocar dados de CI/CD em `n8n` nem em `metabase`, que permanecem como databases internos separados.

Permissões (least-privilege):
- `automation_writer` (n8n): `CONNECT` na database `automation`, `USAGE, CREATE` em `public`, `ALL PRIVILEGES` em tabelas/sequências existentes e `ALTER DEFAULT PRIVILEGES FOR ROLE automation_writer ... GRANT SELECT / USAGE, SELECT ... TO automation_reader` para objetos futuros criados pelo writer.
- `automation_reader` (Metabase): `CONNECT` na database `automation`, `USAGE` em `public`, `SELECT` em tabelas existentes, `USAGE, SELECT` em sequências existentes + default privileges acima. Nunca recebe `CREATE`, `INSERT`, `UPDATE`, `DELETE` nem ownership.

## Vault — senhas `automation_writer` / `automation_reader`

Ambas as variáveis devem ser adicionadas ao Vault criptografado específico do ambiente antes de reexecutar o Ansible. Nunca commitar valores reais; usar senhas fortes distintas entre si e de `postgres_superuser_password`, `postgres_n8n_password`, `postgres_metabase_password`. O Ansible valida que todas são não-vazias, distintas e nunca imprime valores (`no_log: true`).

Bloco sanitizado a adicionar em `ansible/inventories/<env>/group_vars/all/vault.yml` (exemplo, sem valores reais):

```yaml
postgres_automation_writer_password: "<distinct strong password>"
postgres_automation_reader_password: "<distinct strong password>"
```

Localização: `ansible/inventories/lab/group_vars/all/vault.yml` e `ansible/inventories/prod/group_vars/all/vault.yml` (arquivos ignorados, 0600, criptografados com `ansible-vault`). Exemplo inventário rastreado `all.example.yml` contém apenas os nomes não-secretos:

```yaml
compose_postgres_db_automation: automation
compose_postgres_user_automation_writer: automation_writer
compose_postgres_user_automation_reader: automation_reader
```

Metadados não-secretos também são renderizados em `compose/postgres/.env` gerado no host:

```dotenv
POSTGRES_AUTOMATION_DB=automation
POSTGRES_AUTOMATION_WRITER=automation_writer
POSTGRES_AUTOMATION_READER=automation_reader
```

## Migração aditiva (preserva dados existentes)

Após adicionar as duas senhas ao Vault, executar a migração aditiva (não destrói dados n8n/metabase, apenas adiciona roles/database/contrato):

```bash
ansible-playbook -i ansible/inventories/lab/hosts.yml \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass \
  ansible/site.yml --tags compose-services
```

Mantido idempotente. Em seguida restaura firewall + Traefik (segundo estágio já existente):

```bash
ansible-playbook -i ansible/inventories/lab/hosts.yml \
  -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass \
  ansible/site.yml --tags firewall,k8s-platform
```

O primeiro comando preserva os dados existentes de n8n e Metabase e adiciona apenas a database/roles compartilhadas e o contrato de ambiente. O segundo restaura o estágio de firewall e Traefik.

## Conexão — n8n (writer) e Metabase (reader)

Nenhuma tabela de aplicação é criada por esta task — `AUTOMATION_DB_*` é apenas contrato de conexão. Workflows n8n e data sources Metabase que usam `automation` são criados fora desta mudança.

n8n — segunda credencial PostgreSQL (além de `DB_POSTGRESDB_*` que continua apontando para `n8n`):

- host `postgres`
- port `5432`
- database `automation`
- user `automation_writer`
- password via Vault (`postgres_automation_writer_password` → `AUTOMATION_DB_PASSWORD` no container)

No Compose (`compose/n8n/compose.yaml` e `ansible/roles/compose-services/templates/n8n.env.j2`):

```yaml
AUTOMATION_DB_HOST: "${AUTOMATION_DB_HOST:-postgres}"
AUTOMATION_DB_PORT: "${AUTOMATION_DB_PORT:-5432}"
AUTOMATION_DB_NAME: "${AUTOMATION_DB_NAME:-automation}"
AUTOMATION_DB_USER: "${AUTOMATION_DB_USER:-automation_writer}"
AUTOMATION_DB_PASSWORD: "${AUTOMATION_DB_PASSWORD:?required}"
```

Metabase — data source `automation` (ao mesmo host/port/database, com user `automation_reader`; `MB_DB_*` continua apontando para database `metabase` e deve ser configurado via UI/API de administração do Metabase):

- host `postgres`
- port `5432`
- database `automation`
- user `automation_reader`
- password via Vault (`postgres_automation_reader_password` → `AUTOMATION_DB_PASSWORD`)

No Compose (`compose/metabase/compose.yaml` e `ansible/roles/compose-services/templates/metabase.env.j2`):

```yaml
AUTOMATION_DB_HOST: "${AUTOMATION_DB_HOST:-postgres}"
AUTOMATION_DB_PORT: "${AUTOMATION_DB_PORT:-5432}"
AUTOMATION_DB_NAME: "${AUTOMATION_DB_NAME:-automation}"
AUTOMATION_DB_USER: "${AUTOMATION_DB_USER:-automation_reader}"
AUTOMATION_DB_PASSWORD: "${AUTOMATION_DB_PASSWORD:?required}"
```

Exemplos sanitizados (`.env.example` com `changeme-*`, nunca valores reais; `.env` gerado pelo Ansible contém valores Vault e é ignorado):

- `compose/n8n/.env.example` → `AUTOMATION_DB_USER=automation_writer`, `AUTOMATION_DB_PASSWORD=changeme-automation-writer`
- `compose/metabase/.env.example` → `AUTOMATION_DB_USER=automation_reader`, `AUTOMATION_DB_PASSWORD=changeme-automation-reader`

## Validação estática (sem Vault/host vivo)

```bash
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
ansible-playbook --syntax-check ansible/site.yml
yamllint ansible/ k8s/ compose/
bash -n scripts/hosts/generate-hosts.sh
docker compose --env-file compose/n8n/.env.example -f compose/n8n/compose.yaml config >/dev/null
docker compose --env-file compose/metabase/.env.example -f compose/metabase/compose.yaml config >/dev/null
git diff --check
git status --short
```

Confirmar que nenhum arquivo rastreado contém senha real, `192.168.100.179`, `latest` ou referência de imagem sem pinagem `name:tag@sha256:<64-hex>`.

Dados sanitizados alternativos quando Docker não está disponível (simulação Python da interpolação `${VAR:-default}` / `${VAR:?required}`) — ver task reports anteriores.

Validação estática:

```bash
docker compose --env-file compose/postgres/.env.example -f compose/postgres/compose.yaml config
docker compose --env-file compose/jenkins/.env.example -f compose/jenkins/compose.yaml config
docker compose --env-file compose/n8n/.env.example -f compose/n8n/compose.yaml config
docker compose --env-file compose/metabase/.env.example -f compose/metabase/compose.yaml config
```

## Verificação em lab (requer Vault e host vivo) — passos 5–7 documentados, execução em host

Estes comandos exigem `vault.yml` com `postgres_automation_writer_password` / `postgres_automation_reader_password` e host lab com Docker/PostgreSQL em execução. Estão documentados aqui com saídas esperadas; execute no host lab quando disponível. Nunca imprimir conteúdo de `.env` gerado.

### Passo 5 — Migração aditiva em duas etapas (já descrito acima)

Ver seção "Migração aditiva". Esperado: primeira execução preserva dados n8n/metabase existentes e adiciona apenas `automation` + roles + contrato; segunda restaura firewall/DOCKER-USER e file provider Traefik.

### Passo 6 — Verificar permissões no host

```bash
sudo docker exec postgres psql -X -U postgres -d postgres -c \
  "SELECT datname FROM pg_database WHERE datname IN ('n8n', 'metabase', 'automation') ORDER BY datname"
sudo docker exec postgres psql -X -U postgres -d postgres -c \
  "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname IN ('n8n', 'metabase', 'automation_writer', 'automation_reader') ORDER BY rolname"
sudo docker exec postgres psql -X -U postgres -d automation -c \
  "SELECT has_schema_privilege('automation_reader', 'public', 'USAGE') AS reader_usage, has_schema_privilege('automation_reader', 'public', 'CREATE') AS reader_create"
```

Esperado: as três databases (`automation`, `metabase`, `n8n`) e os quatro application roles (`automation_reader`, `automation_writer`, `metabase`, `n8n`) existem; `reader_usage` é `t`; `reader_create` é `f`. Use os `.env` gerados apenas para testes autenticados writer/reader (ex.: `psql "host=postgres port=5432 dbname=automation user=automation_writer password=..." -c "SELECT 1"`), nunca imprimir seu conteúdo.

### Passo 7 — Verificar redes e comportamento de serviços

```bash
sudo docker inspect n8n --format '{{json .NetworkSettings.Networks}}'
sudo docker inspect metabase --format '{{json .NetworkSettings.Networks}}'
sudo docker inspect jenkins --format '{{json .NetworkSettings.Networks}}'
sudo docker exec jenkins curl -fsS http://n8n:5678/healthz >/dev/null
```

Esperado: n8n está em ambas as redes externas (`home-server-automation` e `home-server-data`), Metabase está em `home-server-data`, Jenkins está em `home-server-automation`, e Jenkins alcança n8n (`http://n8n:5678/healthz` → 200) sem qualquer anexo direto de rede PostgreSQL. Jenkins has no direct PostgreSQL route — validado por ausência de `home-server-data` em `jenkins` inspect.
