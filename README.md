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
│   ├── roles/{base,docker,cockpit,k3s,firewall,k8s-platform}/
│   ├── roles/xanmanning.k3s/    # ignorada — reinstalável via ansible-galaxy (requirements.yml)
│   └── secrets/               # ignorado — *.crt/*.key locais do mkcert
├── compose/                   # reservado para Slice 2 (host-native Docker Compose)
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
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags firewall
ansible-playbook -i ansible/inventories/lab/hosts.yml -u "$HOME_SERVER_SSH_USER" --ask-become-pass --ask-vault-pass ansible/site.yml --tags k8s-platform
```

Ordem intencional em `ansible/site.yml`: `base` → `docker` → `cockpit` → `k3s` → `firewall` → `k8s-platform`.

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

Slice 1 não abre portas de aplicações futuras nem NodePorts de aplicação; apenas `22`, `80`, `443`, `9090` e `6443` a partir de `lan_cidr`/`vpn_cidr`, além do forwarding CNI.

## O que o Slice 1 não faz

- Não instala CasaOS.
- Não cria Services ou EndpointSlices legados para rotear serviços host-native; serviços Compose futuros serão roteados diretamente pelo file provider do Traefik bundled, sem objetos Kubernetes.
- Não executa restore automático de dados nem deploy de aplicações Compose.
- Não modifica automaticamente `/etc/hosts` de clientes.

## Próximos slices

- **Slice 2**: Compose host-native (Jenkins, n8n, Metabase, PostgreSQL e rede de dados).
- **Slice 3**: Dashboard Glance e observabilidade (Portainer, Grafana, Prometheus) sobre a fundação do Slice 1.
- **Slices seguintes**: restore e automações adicionais.

## Segurança e notas

- Docker exposto apenas via socket Unix; sem listeners `2375`/`2376`.
- UFW com `DEFAULT_FORWARD_POLICY="ACCEPT"` para o CNI; política de entrada `deny` e allowlist restrita ao Slice 1.
- Não commitar IPs reais de produção, segredos ou conteúdos de certificados. O inventário real e `vault.yml` permanecem ignorados.
- Remover NodePorts legados após Ingress estável (nenhum criado no Slice 1).
