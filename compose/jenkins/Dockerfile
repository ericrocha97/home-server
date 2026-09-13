# compose/jenkins/Dockerfile — a role passa uma referência completa com digest real.
# Não adicionar uma tag default: sem build-arg o build deve falhar.
ARG JENKINS_BASE_IMAGE
FROM ${JENKINS_BASE_IMAGE}
ARG JENKINS_BASE_IMAGE
LABEL org.opencontainers.image.base.name="${JENKINS_BASE_IMAGE}"

USER root

# NOTE: Debian trixie split the CLI into the separate docker-cli binary
# package; docker.io is the daemon only (now Recommends: docker-cli). Jenkins
# talks to the host daemon through the mounted /var/run/docker.sock, so only
# the client is needed — the daemon (containerd/runc/iptables) is unused here.
RUN apt-get update && apt-get install -y --no-install-recommends \
      docker-cli curl gpg ca-certificates gosu tini \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
         -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
         > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

COPY docker-entrypoint-group-fix.sh /usr/local/bin/docker-entrypoint-group-fix.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint-group-fix.sh

# Pin and install Jenkins plugins compatible with 2.568.3-lts-jdk21.
# Prometheus 860.v532442b_44e9a_ requires Jenkins 2.479.3; matrix-auth 3.3
# requires Jenkins 2.528.3. Base image stays in the required build arg only.
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

RUN command -v docker \
    && docker --version \
    && command -v gh \
    && gh --version \
    && command -v gosu \
    && test -x /usr/bin/tini \
    && test -x /usr/local/bin/jenkins.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint-group-fix.sh"]
