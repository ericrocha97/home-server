FROM lscr.io/linuxserver/code-server:latest

ARG DOCKER_GID

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc && \
    chmod a+r /etc/apt/keyrings/docker.asc && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*


RUN groupadd -g ${DOCKER_GID} docker


RUN mkdir -p /etc/cont-init.d


RUN echo '#!/bin/sh' > /etc/cont-init.d/99-docker-user && \
    echo 'usermod -aG docker abc' >> /etc/cont-init.d/99-docker-user && \
    chmod +x /etc/cont-init.d/99-docker-user