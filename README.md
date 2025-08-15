# Configuração Ansible para Home Server

Este repositório contém playbooks Ansible para configurar um servidor doméstico com foco em Kubernetes (k3s) + observabilidade (Prometheus/Grafana) e ferramentas auxiliares (Portainer), além de ambiente de desenvolvimento (Node.js, Zsh, SDKs).

## Estrutura de Arquivos

- `ansible/`: Diretório principal com playbooks.
  - `playbook.yml`: Setup base (pacotes essenciais, Docker opcional se ainda necessário para Portainer gerir host, utilitários).
  - `k3s_playbook.yml`: Instala e configura k3s (via role `xanmanning.k3s`).
  - `k8s_apps_playbook.yml`: Implanta stack Kubernetes (Portainer + kube-prometheus-stack + cAdvisor + Ingress + Secrets + RBAC).
  - `nvm_node_pnpm_playbook.yml`: Instala NVM, Node LTS e pnpm.
  - `zsh_starship_playbook.yml`: Instala Zsh, Oh My Zsh e Starship.
  - `sdkman_playbook.yml`: Instala SDKMAN! e dependências.
  - `inventory.ini`: Inventário de hosts.
  - `secrets.yml`: (Reservado) para uso futuro com Ansible Vault.
- `k8s/`: Manifests da stack (Portainer, monitoring, ingress, secrets, RBAC) + README detalhado.

## Pré-requisitos

1. **Ansible Instalado**: Você precisa ter o Ansible instalado na sua máquina local.
2. **Acesso SSH**: Acesso SSH ao servidor de destino configurado com chaves públicas/privadas.
3. **Coleções e Roles Ansible**: Instale as coleções e roles necessárias (a `kubernetes.core` é obrigatória para o playbook de apps; `community.docker` só se ainda for usar Docker diretamente):

    ```bash
    ansible-galaxy collection install kubernetes.core
    ansible-galaxy role install xanmanning.k3s
    ansible-galaxy collection install community.docker
    ```

## Como Executar os Playbooks

**Nota**: Execute os playbooks a partir do diretório `ansible/`.

1. **Configuração Inicial do Servidor:**
    Este playbook instala pacotes básicos e o Docker.

    ```bash
    ansible-playbook -i inventory.ini playbook.yml --ask-become-pass
    ```

2. **Instalar K3s:**
    Este playbook instala o K3s no servidor.

    ```bash
    ansible-playbook -i inventory.ini k3s_playbook.yml --ask-become-pass
    ```

3. **Deploy da Stack Kubernetes (após k3s + secrets locais):**

    Criar secrets reais a partir dos exemplos em `k8s/secrets/*.example.yaml`.

    ```bash
    ansible-playbook -i inventory.ini k8s_apps_playbook.yml --ask-become-pass
    ```

    Acessos:
    - Portainer: `http://portainer.local` (Ingress) ou `http://<IP_DO_SERVIDOR>:30900` (NodePort opcional)
    - Grafana: `http://grafana.local`

    Adicionar ao `/etc/hosts` da máquina de acesso:

    ```text
    <IP_DO_SERVIDOR> portainer.local grafana.local
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

Após rodar `k8s_apps_playbook.yml` e configurar `/etc/hosts` local apontando para o IP do nó:

- Portainer: `http://portainer.local` (NodePort 30900 opcional)
- Grafana: `http://grafana.local`
- Prometheus / Alertmanager: usar `kubectl port-forward` ou criar Ingress futuro

Exemplo `/etc/hosts`:

```text
<IP_DO_SERVIDOR> portainer.local grafana.local
```

## Segurança & Notas

- Portainer monta `/var/run/docker.sock` e possui permissões amplas (ClusterRole) – risco: acesso root ao host.
- Considere migrar para Portainer Agent ou limitar permissões após estabilização.
- Recomendado adicionar TLS (cert-manager) e remover NodePort quando Ingress estiver estável.
