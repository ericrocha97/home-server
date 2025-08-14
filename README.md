# Configuração Ansible para Home Server

Este repositório contém playbooks Ansible para configurar um servidor doméstico. A configuração inclui a instalação de pacotes básicos, Docker, K3s, ambiente de desenvolvimento (NVM, Node.js) e personalização do shell (Zsh, Starship).

## Estrutura de Arquivos

- `ansible/`: Diretório principal que contém todos os arquivos Ansible.
  - `playbook.yml`: Playbook principal para a configuração inicial do servidor. Instala pacotes essenciais como git, vim, curl e Docker.
  - `k3s_playbook.yml`: Playbook para instalar e configurar um cluster K3s (Lightweight Kubernetes) no servidor. Utiliza a role `xanmanning.k3s`.
  - `docker_apps_playbook.yml`: Implanta os serviços Docker (Portainer, Adminer, Netdata) usando um arquivo estático `docker-compose.yml`. O playbook garante uma implantação limpa, removendo contêineres e redes antigas antes de iniciar os novos.
  - `nvm_node_pnpm_playbook.yml`: Playbook para instalar NVM (Node Version Manager), a versão mais recente do Node.js (LTS) e pnpm. Garante que o `nvm` esteja disponível nos shells Bash e Zsh.
    - `zsh_starship_playbook.yml`: Playbook para instalar e configurar o Zsh como shell padrão, Oh My Zsh e o prompt Starship com o tema Rosé Pine.
    - `sdkman_playbook.yml`: Playbook para instalar o SDKMAN! e suas dependências no servidor.
  - `inventory.ini`: Arquivo de inventário que define os hosts a serem gerenciados pelo Ansible.
  - `secrets.yml`: Arquivo criptografado para armazenar dados sensíveis. (Nota: Atualmente não utilizado pelos playbooks, mas mantido para uso futuro).
  - `docker_files/`: Diretório que contém arquivos relacionados à configuração dos contêineres Docker.
    - `docker-compose.yml`: Arquivo estático que define os serviços a serem implantados: Portainer, Adminer, Netdata, Prometheus, Grafana, Node Exporter e cAdvisor. As portas são expostas diretamente para acesso via IP do servidor.
    - `prometheus/prometheus.yml`: Arquivo de configuração do Prometheus, já configurado para coletar métricas do Node Exporter e cAdvisor.

## Pré-requisitos

1. **Ansible Instalado**: Você precisa ter o Ansible instalado na sua máquina local.
2. **Acesso SSH**: Acesso SSH ao servidor de destino configurado com chaves públicas/privadas.
3. **Coleções e Roles Ansible**: Instale as coleções e roles necessárias com os seguintes comandos:

    ```bash
    ansible-galaxy collection install community.docker
    ansible-galaxy role install xanmanning.k3s
    ```

## Como Executar os Playbooks

**Nota**: Execute os playbooks a partir do diretório `ansible/`.

1. **Configuração Inicial do Servidor:**
    Este playbook instala pacotes básicos e o Docker.

    ```bash
    ansible-playbook -i inventory.ini playbook.yml --ask-become-pass
    ```

2. **Implantar Aplicações Docker:**
    Este playbook implanta os contêineres definidos no `docker-compose.yml`, incluindo monitoramento e visualização de métricas.

    ```bash
    ansible-playbook -i inventory.ini docker_apps_playbook.yml --ask-become-pass
    ```

3. **Instalar K3s:**
    Este playbook instala o K3s no servidor.

    ```bash
    ansible-playbook -i inventory.ini k3s_playbook.yml --ask-become-pass
    ```

4. **Instalar Ambiente Node.js:**
    Este playbook instala NVM, Node.js (LTS) e pnpm.

    ```bash
    ansible-playbook -i inventory.ini nvm_node_pnpm_playbook.yml --ask-become-pass
    ```

5. **Instalar Zsh e Starship:**
    Este playbook instala e configura o Zsh e o prompt Starship.

    ```bash
    ansible-playbook -i inventory.ini zsh_starship_playbook.yml --ask-become-pass
    ```

6. **Instalar SDKMAN!:**
    Este playbook instala o SDKMAN! e suas dependências no servidor.

    ```bash
    ansible-playbook -i inventory.ini sdkman_playbook.yml --ask-become-pass
    ```

## Acesso aos Serviços

Após executar o `docker_apps_playbook.yml`, os serviços estarão disponíveis nos seguintes endereços (substitua `<IP_DO_SERVIDOR>` pelo IP do seu homeserver):

- **Portainer:** `http://<IP_DO_SERVIDOR>:9000`
- **Adminer:** `http://<IP_DO_SERVIDOR>:8081`
- **Netdata:** `http://<IP_DO_SERVIDOR>:19999`
- **Prometheus:** `http://<IP_DO_SERVIDOR>:19090`
- **Grafana:** `http://<IP_DO_SERVIDOR>:13000`
- **Node Exporter:** `http://<IP_DO_SERVIDOR>:19100/metrics`
- **cAdvisor:** `http://<IP_DO_SERVIDOR>:18080`

O Grafana já estará pronto para ser configurado com Prometheus como fonte de dados e dashboards de monitoramento do servidor.
