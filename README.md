# Configuração Ansible para Home Server

Este repositório contém playbooks Ansible para configurar um servidor doméstico. A configuração inclui a instalação de pacotes básicos, Docker, K3s, ambiente de desenvolvimento (NVM, Node.js) e personalização do shell (Zsh, Starship).

## Estrutura de Arquivos

- `ansible/`: Diretório principal que contém todos os arquivos Ansible.
  - `playbook.yml`: Playbook principal para a configuração inicial do servidor. Instala pacotes essenciais como git, vim, curl e Docker.
  - `k3s_playbook.yml`: Playbook para instalar e configurar um cluster K3s (Lightweight Kubernetes) no servidor. Utiliza a role `xanmanning.k3s`.
  - `docker_apps_playbook.yml`: Playbook para implantar serviços em contêineres Docker usando Docker Compose. Os serviços incluem Portainer e Netdata.
  - `nvm_node_pnpm_playbook.yml`: Playbook para instalar NVM (Node Version Manager), a versão mais recente do Node.js (LTS) e pnpm. Garante que o `nvm` esteja disponível nos shells Bash e Zsh.
  - `zsh_starship_playbook.yml`: Playbook para instalar e configurar o Zsh como shell padrão, Oh My Zsh e o prompt Starship com o tema Rosé Pine.
  - `inventory.ini`: Arquivo de inventário que define os hosts a serem gerenciados pelo Ansible.
  - `secrets.yml`:  Arquivo criptografado que armazena dados sensíveis como senhas e chaves de API.
  - `docker_files/`: Diretório que contém arquivos relacionados à configuração dos contêineres Docker.
    - `docker-compose.yml.j2`: Template Jinja2 para o arquivo `docker-compose.yml`. É usado pelo `docker_apps_playbook.yml` para gerar o arquivo de composição final.
    - `Dockerfile`: Dockerfile para construir uma imagem personalizada. (Nota: Atualmente não utilizado no docker-compose).
    - `portainer_password.txt.j2`: Template Jinja2 para criar o arquivo de senha do Portainer.

## Pré-requisitos

1. **Ansible Instalado**: Você precisa ter o Ansible instalado na sua máquina local.
2. **Acesso SSH**: Acesso SSH ao servidor de destino configurado com chaves públicas/privadas.
3. **Coleções e Roles Ansible**: Instale as coleções e roles necessárias com os seguintes comandos:

    ```bash
    ansible-galaxy collection install community.docker
    ansible-galaxy role install xanmanning.k3s
    ```

## Gerenciamento de Segredos

O arquivo `secrets.yml` não está incluído neste repositório por razões de segurança. Você deve criá-lo usando o `ansible-vault`.

1. **Crie o arquivo `secrets.yml`:**
    Execute o comando a seguir no diretório `ansible/`. Ele solicitará que você crie uma senha para o vault.

    ```bash
    ansible-vault create secrets.yml
    ```

2. **Adicione o seguinte conteúdo ao arquivo**, substituindo os valores de exemplo pelas suas senhas:

    ```yaml
    portainer_admin_password: "sua_senha_segura_para_o_portainer"
    ```

## Como Executar os Playbooks

Para executar os playbooks, use o comando `ansible-playbook`. Você precisará fornecer a senha do vault se o playbook a exigir.

**Nota**: Execute os playbooks a partir do diretório `ansible/`.

1. **Configuração Inicial do Servidor:**
    Este playbook instala pacotes básicos e o Docker.

    ```bash
    ansible-playbook -i inventory.ini playbook.yml --ask-become-pass
    ```

2. **Implantar Aplicações Docker:**
    Este playbook implanta os contêineres definidos no `docker-compose.yml.j2`.

    ```bash
    ansible-playbook -i inventory.ini docker_apps_playbook.yml --ask-become-pass --ask-vault-pass
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
