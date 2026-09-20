#!/usr/bin/env bash
set -Eeuo pipefail

# O socket Docker do host é uma dependência opt-in do pipeline Bluefin. Ele só
# é montado pelo overlay compose.bluefin.yaml quando jenkins_bluefin_enabled=true,
# portanto o entrypoint não pode exigi-lo na configuração padrão (desabilitada).
if [[ "${JENKINS_BLUEFIN_ENABLED:-false}" == "true" ]]; then
  if [[ ! -S /var/run/docker.sock ]]; then
    printf 'JENKINS_BLUEFIN_ENABLED=true requires the mounted Docker socket (compose.bluefin.yaml)\n' >&2
    exit 1
  fi
  sock_gid="$(stat -c %g /var/run/docker.sock)"
  if ! getent group dockersock >/dev/null 2>&1; then
    groupadd -g "$sock_gid" dockersock
  elif [[ "$(getent group dockersock | cut -d: -f3)" != "$sock_gid" ]]; then
    groupmod -g "$sock_gid" dockersock
  fi
  usermod -aG dockersock jenkins
fi

exec gosu jenkins /usr/bin/tini -- /usr/local/bin/jenkins.sh "$@"
