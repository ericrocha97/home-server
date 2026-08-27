# compose/jenkins/Dockerfile — a role passa uma referência completa com digest real.
# Não adicionar uma tag default: sem build-arg o build deve falhar.
ARG JENKINS_BASE_IMAGE
FROM ${JENKINS_BASE_IMAGE}
ARG JENKINS_BASE_IMAGE
LABEL org.opencontainers.image.base.name="${JENKINS_BASE_IMAGE}"

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
      docker.io curl gpg ca-certificates gosu tini \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
         -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
         > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

COPY docker-entrypoint-group-fix.sh /usr/local/bin/docker-entrypoint-group-fix.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint-group-fix.sh

RUN command -v gosu && test -x /usr/bin/tini && test -x /usr/local/bin/jenkins.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint-group-fix.sh"]
