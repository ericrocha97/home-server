# Home Server

O Ansible provisiona uma plataforma completa de servidor doméstico de nó único em
um host limpo com **Ubuntu 26.04**. O mesmo código implanta um ambiente de `lab`
(`lab.arpa`) ou um ambiente de produção (`home.arpa`).

A plataforma inclui um host reforçado, Docker, k3s, Traefik, serviços Compose,
monitoramento e ferramentas de administração. Os dados persistentes dos serviços são armazenados em
`/srv/home-server/data/`.

## Serviços

| Serviço    | Finalidade                           | endereço HTTPS                | Acesso direto (IP:porta)       |
| ---------- | ------------------------------------ | ----------------------------- | ------------------------------ |
| Cockpit    | Administração do host                | `https://cockpit.<domain>`    | `https://<server LAN IP>:9090` |
| Jenkins    | Automação de CI                      | `https://jenkins.<domain>`    | `http://<server LAN IP>:18080` |
| n8n        | Automação de fluxos de trabalho      | `https://n8n.<domain>`        | `http://<server LAN IP>:15678` |
| Metabase   | Análises                             | `https://metabase.<domain>`   | `http://<server LAN IP>:13001` |
| Grafana    | Dashboards e visualização            | `https://grafana.<domain>`    | `http://<server LAN IP>:30300` |
| Prometheus | Coleta e consultas de métricas       | `https://prometheus.<domain>` | `http://<server LAN IP>:30909` |
| Portainer  | Administração do Docker e Kubernetes | `https://portainer.<domain>`  | `http://<server LAN IP>:30900` |

`<domain>` é `lab.arpa` para laboratório ou `home.arpa` para produção. O Traefik serve
esses endpoints HTTPS. Cockpit, Jenkins, n8n e Metabase são executados como serviços
Compose nativos do host; Grafana, Prometheus e Portainer são executados no k3s.
Os acessos diretos por IP:porta são permitidos somente a partir da LAN/VPN. Jenkins,
n8n e Metabase respondem apenas em HTTP (o TLS é terminado no Traefik); use preferencialmente
os endereços HTTPS.

PostgreSQL é um serviço de banco de dados interno, não um endpoint HTTP. O provedor do
socket Docker, o exportador de métricas do Docker e a base do LabMonitor são
componentes exclusivamente internos. Em particular, o provedor Docker na porta `12375`
não pode ser acessado por clientes LAN, VPN, Ingress ou NodePort.

## Pré-requisitos

### Estação de trabalho de administração

- Python 3
- Acesso por chave SSH ao host de destino e um usuário não root com capacidade de sudo
- `mkcert` para certificados HTTPS locais
- Docker Compose, caso execute as verificações locais de renderização do Compose

### Host de destino

- Uma instalação limpa do Ubuntu **26.04**
- Um endereço LAN acessível
- Acesso SSH para o usuário de administração

## Instalar as Dependências do Controlador

Execute a partir da raiz do repositório:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r ansible/requirements.txt
ansible-galaxy collection install -r ansible/requirements.yml
ansible-galaxy role install -r ansible/requirements.yml
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
```

Reative `.venv` e exporte `ANSIBLE_CONFIG` em cada novo shell.

## Configurar um Ambiente

Escolha `lab` ou `prod` e use esse nome consistentemente abaixo:

```bash
export ENVIRONMENT=lab
# Para produção: export ENVIRONMENT=prod

cp "ansible/inventories/$ENVIRONMENT/hosts.example.yml" \
  "ansible/inventories/$ENVIRONMENT/hosts.yml"
mkdir -p "ansible/inventories/$ENVIRONMENT/group_vars/all"
cp "ansible/inventories/$ENVIRONMENT/group_vars/all.example.yml" \
  "ansible/inventories/$ENVIRONMENT/group_vars/all/vars.yml"
```

Edite `hosts.yml` e defina `ansible_host` como o IP LAN real do destino. Depois edite
`group_vars/all/vars.yml`:

- Mantenha `environment_name` e `base_domain` pareados: `lab` / `lab.arpa`, ou
  `prod` / `home.arpa`.
- Defina `lan_cidr`, opcionalmente `vpn_cidr`, e `base_timezone` para sua rede
  e localização.
- Mantenha `server_lan_ip: "{{ ansible_host }}"` a menos que o host tenha um endereço
  de serviço diferente.
- Defina `server_lan_interface` ou `k3s_flannel_interface` somente quando a seleção
  automática de interface não for adequada.
- Mantenha as referências de imagem fixadas em `name:tag@sha256:<digest>` onde o exemplo
  exigir um digest. Nunca use `latest`.
- Revise portas, retenção, tamanhos de armazenamento e NodePorts antes do deploy.
- Mantenha `jenkins_clean_reset_confirmed: false` a menos que você autorize explicitamente
  a linha de base limpa destrutiva do Jenkins. Esta é uma operação única: ela
  é executada somente enquanto `/srv/home-server/data/jenkins/.clean-baseline-complete` estiver
  ausente. Para executá-la novamente, remova esse marcador e defina explicitamente a variável
  como `true`; defina-a novamente como `false` imediatamente após a execução aprovada.

Os exemplos rastreados usam somente IPs de documentação. Não faça commit de `hosts.yml`,
`group_vars/all/vars.yml`, `vault.yml` ou arquivos `.env` gerados no host.

## Configurar o Vault

Crie o Vault do ambiente:

```bash
ansible-vault create "ansible/inventories/$ENVIRONMENT/group_vars/all/vault.yml"
```

Ele deve definir valores secretos não vazios e distintos para:

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

Os tokens da API do provedor Jenkins devem ter o formato exato `11` seguido de 32
caracteres hexadecimais em minúsculas. Gere um sem expô-lo no
repositório:

```bash
python3 -c "import secrets; print('11' + secrets.token_hex(16))"
```

As cinco senhas do PostgreSQL devem ser diferentes. As senhas e os tokens do Jenkins
também devem ser diferentes entre si e da senha de administrador do Jenkins. Nunca imprima
nem faça commit do conteúdo do Vault ou dos arquivos `.env` gerados no host.

## Configurar HTTPS

O deploy requer um certificado e uma chave na estação de trabalho de
administração. Gere-os antes do primeiro deploy.

```bash
export ENVIRONMENT=lab
export DOMAIN=lab.arpa
# Para produção: ENVIRONMENT=prod e DOMAIN=home.arpa

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

Cada cliente que abrir as URLs HTTPS deve confiar na CA local do mkcert. Configure
seu servidor DNS local com os sete nomes acima ou gere mapeamentos de host dos clientes
a partir do inventário:

```bash
./scripts/hosts/generate-hosts.sh "$ENVIRONMENT"
```

O script apenas imprime os mapeamentos; revise-os e adicione-os manualmente ao cliente.
Ele solicita a senha do Vault porque lê o inventário do ambiente.

## Validar Antes do Deploy

Defina novamente o ambiente de destino se você abriu um novo terminal:

```bash
export ENVIRONMENT=lab
# Para produção: export ENVIRONMENT=prod
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

Para validar cada definição do Compose com entradas sanitizadas:

```bash
for service in postgres jenkins n8n metabase docker-provider portainer-agent; do
  docker compose --env-file "compose/$service/.env.example" \
    -f "compose/$service/compose.yaml" config >/dev/null
done
```

## Fazer o Deploy

Para o primeiro deploy, feche o curto intervalo entre a publicação de portas do
Compose e a aplicação do firewall com as duas execuções iniciais abaixo. Depois, execute o
playbook completo.

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

As execuções subsequentes são idempotentes. Para uma falha retomável, execute a tag
da função afetada, como `--tags monitoring`, `--tags portainer` ou
`--tags labmonitor-foundation`, e depois execute novamente o playbook completo.

## Verificar o Deploy

O script precisa rodar **no servidor provisionado** (root ou sudo): ele usa o
`kubectl` do k3s local, inspeciona `ufw`/`iptables` e consulta endpoints que só
respondem no próprio host. Copie o script para o servidor e execute-o lá:

```bash
# A partir do seu cliente (controlador Ansible):
scp scripts/verify/platform.sh "$HOME_SERVER_SSH_USER@<server LAN IP>":/tmp/

# No servidor:
ssh "$HOME_SERVER_SSH_USER@<server LAN IP>"
sudo env SERVER_LAN_IP="<server LAN IP>" \
  JENKINS_LABMONITOR_API_TOKEN="<Vault token>" \
  GRAFANA_ADMIN_PASSWORD="<Vault password>" \
  bash /tmp/platform.sh
```

Ela verifica a disponibilidade dos serviços, os destinos do Prometheus, Grafana,
Portainer, permissões do provedor Jenkins, limites do provedor Docker,
RBAC do LabMonitor e metadados de descoberta.

`GRAFANA_ADMIN_PASSWORD` é opcional: o script pode ler o Secret ativo do Kubernetes
quando permitido. O script nunca altera o estado do firewall nem imprime
credenciais.

De um cliente LAN ou VPN separado (a sua máquina cliente, não o próprio servidor —
um teste feito de dentro do host não prova que a porta está fechada para clientes
externos), esta requisição deve falhar. Uma resposta bem-sucedida
significa que o limite do provedor Docker está exposto incorretamente:

```bash
curl --connect-timeout 5 "http://<server LAN IP>:12375/version"
```

## Limites Operacionais

- Os serviços Compose são roteados pelo provedor de arquivos do Traefik. Não crie
  Kubernetes Services ou EndpointSlices para Cockpit, Jenkins, n8n ou
  Metabase.
- O monitoramento do Docker usa o proxy somente leitura na porta `12375`; o exportador de métricas
  não deve montar `/var/run/docker.sock`.
- O Portainer Docker Agent é a única exceção administrativa de socket Docker com leitura e escrita
  e permanece isolado na porta `9001`.
- Jenkins não participa da rede de banco de dados. n8n é o único serviço que participa
  tanto das redes de automação quanto de dados. `automation_writer` é proprietário do banco de
  dados compartilhado; `automation_reader` não tem privilégio de escrita nem de `CREATE`.
- A identidade do LabMonitor pode ler a topologia do cluster e dois ConfigMaps nomeados,
  mas não pode ler Secrets nem alterar recursos do cluster. Nenhuma API web ou carga de trabalho do LabMonitor
  é implantada por este repositório.
