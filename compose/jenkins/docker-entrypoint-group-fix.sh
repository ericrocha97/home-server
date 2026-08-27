#!/usr/bin/env bash
set -Eeuo pipefail
if [[ ! -S /var/run/docker.sock ]]; then
  printf 'Docker socket is required for Jenkins builds but is not mounted\n' >&2
  exit 1
fi
sock_gid="$(stat -c %g /var/run/docker.sock)"
if ! getent group dockersock >/dev/null 2>&1; then
  groupadd -g "$sock_gid" dockersock
elif [[ "$(getent group dockersock | cut -d: -f3)" != "$sock_gid" ]]; then
  groupmod -g "$sock_gid" dockersock
fi
usermod -aG dockersock jenkins
exec gosu jenkins /usr/bin/tini -- /usr/local/bin/jenkins.sh "$@"
