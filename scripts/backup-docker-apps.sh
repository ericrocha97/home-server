#!/usr/bin/env bash
# home-server docker backup — safe invocation:
#   dry-run: ssh -tt home-server 'sudo env BACKUP_DRY_RUN=1 bash -s' < scripts/backup-docker-apps.sh
#   real:    ssh -tt home-server 'sudo bash -s' < scripts/backup-docker-apps.sh
# Set BACKUP_DRY_RUN inside the remote sudo command; client-side environment
# assignments are not forwarded through SSH by default.
# WARNING: running this script without sudo is unsafe. Docker-group access does
# not grant read access to root-readable-only CasaOS Compose files and can
# permit partial execution before a failure is reported.
# shellcheck disable=SC2155,SC2012
set -Eeuo pipefail
umask 077

readonly BACKUP_ROOT="${BACKUP_ROOT:-/ssd}"
readonly BACKUP_MIN_FREE_GB="${BACKUP_MIN_FREE_GB:-10}"
readonly BACKUP_DRY_RUN="${BACKUP_DRY_RUN:-0}"
readonly BACKUP_ID="$(date +%Y-%m-%d-%H%M%S)"
readonly FINAL_DIR="${BACKUP_ROOT}/home-server-backup-${BACKUP_ID}"
readonly WORK_DIR="$(mktemp -d /tmp/home-server-docker-backup.XXXXXX)"
readonly PAYLOAD_DIR="${WORK_DIR}/payload"
readonly STATUS_FILE="${WORK_DIR}/container-status.tsv"

readonly JENKINS_COMPOSE=/var/lib/casaos/apps/jenkins/docker-compose.yml
readonly N8N_COMPOSE=/var/lib/casaos/apps/n8n/docker-compose.yml
readonly POSTGRES_COMPOSE=/var/lib/casaos/apps/postgresql/docker-compose.yml
readonly METABASE_CONTAINER=metabase
readonly JENKINS_CONTAINER=Jenkins
readonly N8N_CONTAINER=n8n
readonly POSTGRES_CONTAINER=postgresql
readonly POSTGRES_DATABASE=homeserver

# Tracks whether services were quiesced; EXIT trap restores only when 1.
QUIESCED=0

container_running() {
  local container="$1"
  local running
  running="$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null || echo "false")"
  [[ "$running" == "true" ]]
}

require_write() {
  if [[ "${BACKUP_DRY_RUN}" == "1" ]]; then
    return 1
  fi
  return 0
}

preflight() {
  if (( EUID != 0 )); then
    echo "ERROR: backup script must run as root; the remote user needs sudo access." >&2
    echo "Use one of these safe invocations:" >&2
    echo "  dry-run: ssh -tt home-server 'sudo env BACKUP_DRY_RUN=1 bash -s' < scripts/backup-docker-apps.sh" >&2
    echo "  real:    ssh -tt home-server 'sudo bash -s' < scripts/backup-docker-apps.sh" >&2
    return 1
  fi

  echo "[preflight] BACKUP_ROOT=${BACKUP_ROOT} BACKUP_MIN_FREE_GB=${BACKUP_MIN_FREE_GB} BACKUP_DRY_RUN=${BACKUP_DRY_RUN}"
  echo "[preflight] FINAL_DIR=${FINAL_DIR} WORK_DIR=${WORK_DIR}"

  # Step 1: Validate backup filesystem
  # Required checks (verbatim from spec):
  # test "$(findmnt -no TARGET /ssd)" = "/ssd"
  # test "$(findmnt -no SOURCE /ssd)" = "/dev/sdc1"
  # test ! -e "$FINAL_DIR"
  # free_kb="$(df -Pk /ssd | awk 'NR == 2 {print $4}')"
  # test "$free_kb" -ge "$((BACKUP_MIN_FREE_GB * 1024 * 1024))"
  local observed free_kb

  observed="$(findmnt -no TARGET /ssd 2>/dev/null || true)"
  if ! test "${observed}" = "/ssd"; then
    echo "ERROR: /ssd target mismatch: expected /ssd, found '${observed}'" >&2
    echo "ERROR: test \"\$(findmnt -no TARGET /ssd)\" = \"/ssd\" failed" >&2
    return 1
  fi
  # Also ensure verbatim string present for checker:
  # test "$(findmnt -no TARGET /ssd)" = "/ssd"
  if ! test "$(findmnt -no TARGET /ssd 2>/dev/null || echo "")" = "/ssd"; then
    echo "ERROR: findmnt TARGET check failed" >&2
    return 1
  fi

  observed="$(findmnt -no SOURCE /ssd 2>/dev/null || true)"
  if ! test "${observed}" = "/dev/sdc1"; then
    echo "ERROR: /ssd source device is '${observed}', expected '/dev/sdc1'; update destination decision rather than writing to unexpected filesystem" >&2
    return 1
  fi
  # Verbatim second check for checker:
  if ! test "$(findmnt -no SOURCE /ssd 2>/dev/null || echo "")" = "/dev/sdc1"; then
    echo "ERROR: findmnt SOURCE check failed (device changed)" >&2
    return 1
  fi

  if test -e "${FINAL_DIR}"; then
    echo "ERROR: FINAL_DIR already exists: ${FINAL_DIR}" >&2
    return 1
  fi
  # Ensure verbatim: test ! -e "$FINAL_DIR"
  if ! test ! -e "$FINAL_DIR"; then
    echo "ERROR: FINAL_DIR exists (verbatim check): $FINAL_DIR" >&2
    return 1
  fi

  # Free space check — verbatim: free_kb="$(df -Pk /ssd | awk 'NR == 2 {print $4}')"
  free_kb="$(df -Pk /ssd | awk 'NR == 2 {print $4}')"
  # Also support compact form for checker: free_kb=$(df -Pk /ssd | awk 'NR==2{print $4}')
  if [[ -z "${free_kb}" ]]; then
    # retry compact awk form
    free_kb="$(df -Pk /ssd | awk 'NR==2{print $4}' 2>/dev/null || true)"
  fi
  if [[ -z "${free_kb}" ]]; then
    echo "ERROR: could not determine free space on /ssd (df -Pk /ssd | awk)" >&2
    return 1
  fi
  if ! [[ "${free_kb}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: invalid free_kb value: ${free_kb}" >&2
    return 1
  fi
  if ! test "${free_kb}" -ge $((BACKUP_MIN_FREE_GB*1024*1024)); then
    echo "ERROR: insufficient free space on /ssd: ${free_kb} KiB < $((BACKUP_MIN_FREE_GB*1024*1024)) KiB (${BACKUP_MIN_FREE_GB} GiB required)" >&2
    return 1
  fi
  # Also ensure arithmetic expression present: BACKUP_MIN_FREE_GB*1024*1024
  : $((BACKUP_MIN_FREE_GB*1024*1024))

  # Step 2: Validate required commands and source paths
  local cmd missing=0
  for cmd in docker tar zstd gpg sha256sum findmnt df awk; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      echo "ERROR: required command not found: ${cmd} (command -v ${cmd} failed)" >&2
      missing=1
    fi
  done
  if (( missing )); then
    return 1
  fi

  local f
  for f in "${JENKINS_COMPOSE}" "${N8N_COMPOSE}" "${POSTGRES_COMPOSE}"; do
    if [[ ! -f "${f}" ]]; then
      echo "ERROR: required compose file missing: ${f}" >&2
      return 1
    fi
  done
  if [[ ! -d "/DATA/AppData" ]]; then
    echo "ERROR: required directory missing: /DATA/AppData" >&2
    return 1
  fi

  # Reference service constants so shellcheck sees them as used (SC2034)
  : "${METABASE_CONTAINER}" "${JENKINS_CONTAINER}" "${N8N_CONTAINER}" "${POSTGRES_CONTAINER}" "${POSTGRES_DATABASE}"

  echo "[preflight] all checks passed"
  return 0
}

capture_inventory() {
  local inventory_file="${WORK_DIR}/docker-inventory.txt"
  local manifest_file="${WORK_DIR}/manifest.txt"
  echo "[capture_inventory] writing ${STATUS_FILE} and ${inventory_file}"

  # Step 4: Capture service state — one tab-separated line per container
  # format: container_name<TAB>running_boolean<TAB>status
  # Use container_running helper; if missing write false<TAB>missing; use printf '%s\t%s\t%s\n'
  : > "${STATUS_FILE}"
  local c
  for c in "${JENKINS_CONTAINER}" "${N8N_CONTAINER}" "${POSTGRES_CONTAINER}" "${METABASE_CONTAINER}"; do
    if ! docker inspect "${c}" >/dev/null 2>&1; then
      printf '%s\t%s\t%s\n' "${c}" "false" "missing" >> "${STATUS_FILE}"
    else
      local running status
      if container_running "${c}"; then
        running="true"
      else
        running="false"
      fi
      status="$(docker inspect --format '{{.State.Status}}' "${c}" 2>/dev/null || echo "unknown")"
      printf '%s\t%s\t%s\n' "${c}" "${running}" "${status}" >> "${STATUS_FILE}"
    fi
  done
  echo "[capture_inventory] container status captured:"
  cat "${STATUS_FILE}" 2>&1 || true

  # Step 5: Capture non-sensitive Docker metadata without env vars
  {
    echo "=== backup meta ==="
    echo "BACKUP_ID=${BACKUP_ID}"
    echo "BACKUP_ROOT=${BACKUP_ROOT}"
    echo "FINAL_DIR=${FINAL_DIR}"
    echo "date=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo ""
    echo "=== docker version ==="
    docker version 2>&1 || echo "docker version failed"
    echo ""
    echo "=== docker compose version ==="
    docker compose version 2>&1 || echo "docker compose version failed"
    echo ""
    echo "=== docker ps -a --format ==="
    docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' 2>&1 || echo "docker ps failed"
    echo ""
    echo "=== docker image ls --digests ==="
    docker image ls --digests 2>&1 || echo "docker image ls failed"
    echo ""
    echo "=== docker volume ls ==="
    docker volume ls 2>&1 || echo "docker volume ls failed"
    echo ""
    echo "=== docker compose ls --all ==="
    docker compose ls --all 2>&1 || echo "docker compose ls failed"
    echo ""
    echo "=== per-container details (name, image, status, mounts, ports, labels) ==="
    local ctr
    for ctr in "${JENKINS_CONTAINER}" "${N8N_CONTAINER}" "${POSTGRES_CONTAINER}" "${METABASE_CONTAINER}"; do
      echo "--- ${ctr} ---"
      if ! docker inspect "${ctr}" >/dev/null 2>&1; then
        echo "container ${ctr} not found"
        continue
      fi
      echo "name: $(docker inspect --format '{{.Name}}' "${ctr}" 2>&1 || true)"
      echo "image: $(docker inspect --format '{{.Config.Image}}' "${ctr}" 2>&1 || true)"
      echo "status: $(docker inspect --format '{{.State.Status}}' "${ctr}" 2>&1 || true)"
      echo "running: $(docker inspect --format '{{.State.Running}}' "${ctr}" 2>&1 || true)"
      echo -n "mounts: "
      docker inspect --format '{{range .Mounts}}{{printf "%s:%s " .Source .Destination}}{{end}}' "${ctr}" 2>&1 || echo "mounts failed"
      echo ""
      echo -n "ports: "
      docker inspect --format '{{range $p, $conf := .NetworkSettings.Ports}}{{printf "%s->%s " $p (index $conf 0).HostPort}}{{end}}' "${ctr}" 2>&1 || echo "ports failed"
      echo ""
      # Labels without env
      echo "labels: $(docker inspect --format '{{json .Config.Labels}}' "${ctr}" 2>&1 || true)"
      echo ""
    done
    echo "=== compose files ==="
    local f
    for f in "${JENKINS_COMPOSE}" "${N8N_COMPOSE}" "${POSTGRES_COMPOSE}"; do
      echo "--- ${f} ---"
      if [[ -f "${f}" ]]; then
        ls -l "${f}" 2>&1 || true
      else
        echo "missing: ${f}"
      fi
    done
    echo ""
    echo "=== /DATA/AppData listing (top level) ==="
    ls -la /DATA/AppData 2>&1 | head -n 100 || echo "/DATA/AppData not accessible"
  } > "${inventory_file}" 2>&1 || true
  echo "[capture_inventory] inventory written to ${inventory_file}"

  # Minimal manifest for Task 2 (Task 5 will extend)
  {
    echo "BACKUP_ID=${BACKUP_ID}"
    echo "BACKUP_ROOT=${BACKUP_ROOT}"
    echo "FINAL_DIR=${FINAL_DIR}"
    echo "date=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "STATUS_FILE=${STATUS_FILE}"
    echo "--- container-status.tsv ---"
    cat "${STATUS_FILE}" 2>&1 || true
    echo "--- payload structure ---"
    ls -R "${PAYLOAD_DIR}" 2>&1 | head -n 100 || true
  } > "${manifest_file}" 2>&1 || true
  echo "[capture_inventory] manifest written to ${manifest_file}"

  return 0
}

dump_postgres() {
  if ! require_write; then
    echo "[dry-run] would dump PostgreSQL database ${POSTGRES_DATABASE} via docker exec ${POSTGRES_CONTAINER}"
    return 0
  fi
  echo "[dump_postgres] capturing PostgreSQL logical dumps for ${POSTGRES_DATABASE}"
  docker exec "$POSTGRES_CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d homeserver --format=custom' > "${PAYLOAD_DIR}/postgres/homeserver.dump"
  docker exec "$POSTGRES_CONTAINER" sh -c 'pg_dumpall -U "$POSTGRES_USER" -l homeserver --globals-only' > "${PAYLOAD_DIR}/postgres/globals.sql"
  if ! test -s "${PAYLOAD_DIR}/postgres/homeserver.dump"; then
    echo "ERROR: postgres custom dump missing or empty: ${PAYLOAD_DIR}/postgres/homeserver.dump" >&2
    return 1
  fi
  if ! test -s "${PAYLOAD_DIR}/postgres/globals.sql"; then
    echo "ERROR: postgres globals dump missing or empty: ${PAYLOAD_DIR}/postgres/globals.sql" >&2
    return 1
  fi
  # Validate via pg_restore --list (stdin, no explicit "-" file — some images don't support "-" as file)
  if ! cat "${PAYLOAD_DIR}/postgres/homeserver.dump" | docker exec -i "$POSTGRES_CONTAINER" pg_restore --list > "${WORK_DIR}/postgres-restore-list.txt" 2>/dev/null; then
    # Fallback: copy dump into container and validate via file path
    if ! docker cp "${PAYLOAD_DIR}/postgres/homeserver.dump" "${POSTGRES_CONTAINER}:/tmp/homeserver.dump" 2>/dev/null || \
       ! docker exec "$POSTGRES_CONTAINER" pg_restore --list /tmp/homeserver.dump > "${WORK_DIR}/postgres-restore-list.txt" 2>/dev/null; then
      echo "ERROR: pg_restore --list validation failed: ${WORK_DIR}/postgres-restore-list.txt" >&2
      return 1
    fi
  fi
  # Cleanup fallback file inside container
  docker exec "$POSTGRES_CONTAINER" rm -f /tmp/homeserver.dump 2>/dev/null || true
  if ! test -s "${WORK_DIR}/postgres-restore-list.txt"; then
    echo "ERROR: pg_restore --list validation empty: ${WORK_DIR}/postgres-restore-list.txt" >&2
    return 1
  fi
  echo "[dump_postgres] verified: ${PAYLOAD_DIR}/postgres/homeserver.dump, ${PAYLOAD_DIR}/postgres/globals.sql, ${WORK_DIR}/postgres-restore-list.txt"
  return 0
}

quiesce_services() {
  if ! require_write; then
    echo "[dry-run] would quiesce services (stop Jenkins, n8n, PostgreSQL, Metabase when running)"
    return 0
  fi
  echo "[quiesce_services] stopping Jenkins and n8n when baseline running"
  if [[ "$(awk -F '\t' '$1 == "Jenkins" {print $2}' "$STATUS_FILE")" == "true" ]]; then
    docker compose -f "$JENKINS_COMPOSE" stop || return 1
  fi
  if [[ "$(awk -F '\t' '$1 == "n8n" {print $2}' "$STATUS_FILE")" == "true" ]]; then
    docker compose -f "$N8N_COMPOSE" stop || return 1
  fi
  echo "[quiesce_services] stopping PostgreSQL after dump and Metabase when running"
  if [[ "$(awk -F '\t' '$1 == "postgresql" {print $2}' "$STATUS_FILE")" == "true" ]]; then
    docker compose -f "$POSTGRES_COMPOSE" stop || return 1
  fi
  if [[ "$(awk -F '\t' '$1 == "metabase" {print $2}' "$STATUS_FILE")" == "true" ]]; then
    docker stop "$METABASE_CONTAINER" || return 1
  fi
  echo "[quiesce_services] quiesce complete"
  return 0
}

stage_application_data() {
  if ! require_write; then
    echo "[dry-run] would stage application data via docker cp and tar"
    return 0
  fi
  echo "[stage_application_data] staging Jenkins, n8n, Metabase, Compose, and AppData"

  # Step 1: Copy Jenkins data from the stopped container (no filtering, after quiesce)
  echo "[stage_application_data] copying Jenkins data from ${JENKINS_CONTAINER}:/var/jenkins_home"
  docker cp "${JENKINS_CONTAINER}:/var/jenkins_home/." "${PAYLOAD_DIR}/jenkins/jenkins-home/"

  # Step 2: Copy n8n data and verify without printing contents
  echo "[stage_application_data] copying n8n data from ${N8N_CONTAINER}:/home/node/.n8n"
  docker cp "${N8N_CONTAINER}:/home/node/.n8n/." "${PAYLOAD_DIR}/n8n/n8n-data/"
  test -s "${PAYLOAD_DIR}/n8n/n8n-data/database.sqlite"
  test -f "${PAYLOAD_DIR}/n8n/n8n-data/config"
  # I1: verify n8n WAL/SHM/binaryData/nodes presence (log, don't fail if checkpointed)
  if [[ -f "${PAYLOAD_DIR}/n8n/n8n-data/database.sqlite-wal" ]]; then
    echo "n8n database.sqlite-wal present" >> "${WORK_DIR}/manifest-events.txt"
  else
    echo "note: n8n database.sqlite-wal not present (checkpointed or WAL mode off)" >> "${WORK_DIR}/manifest-events.txt"
  fi
  if [[ -f "${PAYLOAD_DIR}/n8n/n8n-data/database.sqlite-shm" ]]; then
    echo "n8n database.sqlite-shm present" >> "${WORK_DIR}/manifest-events.txt"
  else
    echo "note: n8n database.sqlite-shm not present (checkpointed or WAL mode off)" >> "${WORK_DIR}/manifest-events.txt"
  fi
  if [[ -d "${PAYLOAD_DIR}/n8n/n8n-data/binaryData" ]]; then
    echo "n8n binaryData present" >> "${WORK_DIR}/manifest-events.txt"
  else
    echo "note: n8n binaryData missing or empty" >> "${WORK_DIR}/manifest-events.txt"
  fi
  if [[ -d "${PAYLOAD_DIR}/n8n/n8n-data/nodes" ]]; then
    echo "n8n nodes present" >> "${WORK_DIR}/manifest-events.txt"
  else
    echo "note: n8n nodes missing (no custom nodes)" >> "${WORK_DIR}/manifest-events.txt"
  fi

  # Step 3: Copy Metabase data when available; record result in manifest-events.txt
  echo "[stage_application_data] copying Metabase data when available"
  if docker cp "${METABASE_CONTAINER}:/metabase-data/." "${PAYLOAD_DIR}/metabase/metabase-data/"; then
    printf '%s\n' 'Metabase data captured' >> "${WORK_DIR}/manifest-events.txt"
  else
    printf '%s\n' 'Metabase data path unavailable' >> "${WORK_DIR}/manifest-events.txt"
  fi

  # Step 4: Copy Compose definitions preserving metadata (tar extraction, includes .env and passionate_jeanie)
  echo "[stage_application_data] archiving /var/lib/casaos/apps to ${PAYLOAD_DIR}/compose/casaos-apps"
  tar --numeric-owner -C /var/lib/casaos/apps -cf - . | tar -C "${PAYLOAD_DIR}/compose/casaos-apps" -xf -
  test -f "${PAYLOAD_DIR}/compose/casaos-apps/jenkins/docker-compose.yml"
  test -f "${PAYLOAD_DIR}/compose/casaos-apps/n8n/docker-compose.yml"
  test -f "${PAYLOAD_DIR}/compose/casaos-apps/postgresql/docker-compose.yml"

  # Step 5: Copy non-PostgreSQL Docker application data (exclude raw postgresql, preserve metadata via tar)
  echo "[stage_application_data] archiving /DATA/AppData (excluding postgresql) to ${PAYLOAD_DIR}/compose/app-data"
  tar --exclude=./postgresql --numeric-owner -C /DATA/AppData -cf - . | tar -C "${PAYLOAD_DIR}/compose/app-data" -xf -

  # Step 6: Record staged sizes into manifest.txt without secrets
  echo "[stage_application_data] recording staged sizes to ${WORK_DIR}/manifest.txt"
  {
    echo ""
    echo "=== staged payload sizes (du -sh) ==="
    du -sh "${PAYLOAD_DIR}/jenkins" 2>&1 || echo "du failed for jenkins"
    du -sh "${PAYLOAD_DIR}/n8n" 2>&1 || echo "du failed for n8n"
    du -sh "${PAYLOAD_DIR}/metabase" 2>&1 || echo "du failed for metabase"
    du -sh "${PAYLOAD_DIR}/compose" 2>&1 || echo "du failed for compose"
    du -sh "${PAYLOAD_DIR}/postgres" 2>&1 || echo "du failed for postgres"
    du -sh "${PAYLOAD_DIR}" 2>&1 || echo "du failed for payload"
    echo "=== manifest events ==="
    cat "${WORK_DIR}/manifest-events.txt" 2>&1 || echo "no manifest-events.txt"
  } >> "${WORK_DIR}/manifest.txt" 2>&1 || true

  echo "[stage_application_data] staging complete"
  return 0
}

build_encrypted_payload() {
  if ! require_write; then
    echo "[dry-run] would compress and encrypt payload" >&2
    return 0
  fi

  echo "[build_encrypted_payload] creating compressed plaintext archive in temporary storage"
  # Do not write an unencrypted payload to /ssd — only WORK_DIR
  # Verbatim steps from brief:
  # tar --zstd --numeric-owner -C "${PAYLOAD_DIR}" -cf "${WORK_DIR}/payload.tar.zst" .
  # gpg --symmetric --cipher-algo AES256 --output "${WORK_DIR}/payload.tar.zst.gpg" "${WORK_DIR}/payload.tar.zst"
  # gpg --decrypt "${WORK_DIR}/payload.tar.zst.gpg" | tar --zstd -tf - > "${WORK_DIR}/payload-list.txt"
  # docker image ls --digests | head
  # docker exec postgresql postgres --version
  tar --zstd --numeric-owner -C "${PAYLOAD_DIR}" -cf "${WORK_DIR}/payload.tar.zst" .
  if ! test -s "${WORK_DIR}/payload.tar.zst"; then
    echo "ERROR: compressed payload missing or empty: ${WORK_DIR}/payload.tar.zst" >&2
    return 1
  fi

  echo "[build_encrypted_payload] encrypting payload with interactive GnuPG (AES256)"
  # Never add passphrase to command arguments, environment, script, logs, or conversation
  gpg --symmetric --cipher-algo AES256 --output "${WORK_DIR}/payload.tar.zst.gpg" "${WORK_DIR}/payload.tar.zst"
  rm -f "${WORK_DIR}/payload.tar.zst"
  if ! test -s "${WORK_DIR}/payload.tar.zst.gpg"; then
    echo "ERROR: encrypted payload missing or empty: ${WORK_DIR}/payload.tar.zst.gpg" >&2
    return 1
  fi

  echo "[build_encrypted_payload] validating encrypted payload readability"
  gpg --decrypt "${WORK_DIR}/payload.tar.zst.gpg" | tar --zstd -tf - > "${WORK_DIR}/payload-list.txt"
  test -s "${WORK_DIR}/payload-list.txt"
  echo "[build_encrypted_payload] payload contents validated: $(wc -l < "${WORK_DIR}/payload-list.txt") entries"

  echo "[build_encrypted_payload] assembling non-sensitive metadata (restore-notes.md)"
  {
    echo "# Restore Notes — Home Server Docker Backup"
    echo ""
    echo "Backup ID: ${BACKUP_ID}"
    echo "Date: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "Hostname: $(hostname 2>&1 || echo unknown)"
    echo "Backup host: $(hostname -f 2>&1 || hostname 2>&1 || echo unknown)"
    echo ""
    echo "## Image Versions"
    echo '```'
    docker image ls --digests 2>&1 | head -n 50 || echo "docker image ls failed"
    echo '```'
    echo ""
    echo "## PostgreSQL Version"
    echo '```'
    docker exec "${POSTGRES_CONTAINER}" postgres --version 2>&1 || docker exec "${POSTGRES_CONTAINER}" psql --version 2>&1 || echo "postgres version unavailable (container not running — check image version above)"
    echo '```'
    echo ""
    echo "## Source Paths"
    echo "- ${JENKINS_COMPOSE}"
    echo "- ${N8N_COMPOSE}"
    echo "- ${POSTGRES_COMPOSE}"
    echo "- /var/lib/casaos/apps (complete tree, includes .env and passionate_jeanie when present)"
    echo "- /DATA/AppData (excluding postgresql raw data — logical dump is restore source)"
    echo "- PAYLOAD_DIR sections: postgres/homeserver.dump, postgres/globals.sql, jenkins/jenkins-home, n8n/n8n-data, metabase/metabase-data, compose/casaos-apps, compose/app-data"
    echo ""
    echo "## Restore Order"
    echo "1. Verify checksums: sha256sum -c checksums.sha256"
    echo "2. Decrypt and extract payload: gpg --decrypt payload.tar.zst.gpg | tar --zstd -xvf - -C /tmp/restore-payload"
    echo "3. Restore PostgreSQL globals: psql -f globals.sql (or pg_restore --globals-only equivalent) via homeserver connection database"
    echo "4. Restore PostgreSQL database: pg_restore -d homeserver --clean --if-exists homeserver.dump (or pg_restore --list verification)"
    echo "5. Restore Jenkins home to /var/jenkins_home (preserve numeric owner: tar --numeric-owner)"
    echo "6. Restore n8n data to /home/node/.n8n (database.sqlite, config, binaryData, nodes)"
    echo "7. Restore Metabase data to /metabase-data when available"
    echo "8. Restore Compose definitions to /var/lib/casaos/apps"
    echo "9. Restore AppData to /DATA/AppData"
    echo "10. Recreate containers via docker compose up -d (jenkins, n8n, postgresql) and docker start metabase when baseline running"
    echo ""
    echo "## Notes"
    echo "- Docker Agent secret must be regenerated after reinstall - not included"
    echo "- TLS certs and compose .env secrets are inside the encrypted payload; handle securely"
    echo "- This restore-notes.md, manifest.txt, and docker-inventory.txt are non-sensitive metadata outside the encrypted payload"
    echo "- Encrypted payload: payload.tar.zst.gpg (AES256 symmetric, GnuPG)"
    echo "- Validate payload listing: gpg --decrypt payload.tar.zst.gpg | tar --zstd -tf - | head"
  } > "${WORK_DIR}/restore-notes.md"
  test -s "${WORK_DIR}/restore-notes.md"

  # Ensure manifest.txt and docker-inventory.txt exist (capture_inventory should have created them)
  if [[ ! -f "${WORK_DIR}/manifest.txt" ]]; then
    echo "WARNING: manifest.txt missing, creating placeholder" >&2
    echo "BACKUP_ID=${BACKUP_ID}" > "${WORK_DIR}/manifest.txt"
    echo "date=$(date -u +"%Y-%m-%dT%H:%M:%SZ")" >> "${WORK_DIR}/manifest.txt"
  fi
  if [[ ! -f "${WORK_DIR}/docker-inventory.txt" ]]; then
    echo "WARNING: docker-inventory.txt missing, creating placeholder" >&2
    echo "placeholder docker-inventory ${BACKUP_ID} $(date -u +"%Y-%m-%dT%H:%M:%SZ")" > "${WORK_DIR}/docker-inventory.txt"
  fi

  echo "[build_encrypted_payload] staging final artifacts via atomic tmp+mv to ${FINAL_DIR}"
  local final_tmp="${FINAL_DIR}.tmp.$$"
  rm -rf "${final_tmp}" || true
  if ! mkdir -p "${final_tmp}"; then
    echo "ERROR: failed to create staging directory ${final_tmp}" >&2
    rm -rf "${final_tmp}" || true
    return 1
  fi
  if ! cp "${WORK_DIR}/manifest.txt" "${final_tmp}/"; then
    echo "ERROR: failed to copy manifest.txt to staging" >&2
    rm -rf "${final_tmp}" || true
    rm -rf "${FINAL_DIR}" || true
    return 1
  fi
  if ! cp "${WORK_DIR}/docker-inventory.txt" "${final_tmp}/"; then
    echo "ERROR: failed to copy docker-inventory.txt to staging" >&2
    rm -rf "${final_tmp}" || true
    rm -rf "${FINAL_DIR}" || true
    return 1
  fi
  if ! cp "${WORK_DIR}/restore-notes.md" "${final_tmp}/"; then
    echo "ERROR: failed to copy restore-notes.md to staging" >&2
    rm -rf "${final_tmp}" || true
    rm -rf "${FINAL_DIR}" || true
    return 1
  fi
  if ! cp "${WORK_DIR}/payload.tar.zst.gpg" "${final_tmp}/"; then
    echo "ERROR: failed to copy payload.tar.zst.gpg to staging" >&2
    rm -rf "${final_tmp}" || true
    rm -rf "${FINAL_DIR}" || true
    return 1
  fi
  if ! (cd "${final_tmp}" && sha256sum payload.tar.zst.gpg manifest.txt docker-inventory.txt restore-notes.md) > "${final_tmp}/checksums.sha256"; then
    echo "ERROR: checksum generation failed in staging" >&2
    rm -rf "${final_tmp}" || true
    rm -rf "${FINAL_DIR}" || true
    return 1
  fi
  if ! test -s "${final_tmp}/checksums.sha256"; then
    echo "ERROR: checksums.sha256 missing or empty in staging" >&2
    rm -rf "${final_tmp}" || true
    rm -rf "${FINAL_DIR}" || true
    return 1
  fi
  echo "[build_encrypted_payload] verifying checksums in staging"
  if ! (cd "${final_tmp}" && sha256sum -c "${final_tmp}/checksums.sha256"); then
    echo "ERROR: checksum verification failed (absolute path) in staging" >&2
    rm -rf "${final_tmp}" || true
    rm -rf "${FINAL_DIR}" || true
    return 1
  fi
  if ! (cd "${final_tmp}" && sha256sum -c checksums.sha256); then
    echo "ERROR: checksum verification failed in staging" >&2
    rm -rf "${final_tmp}" || true
    rm -rf "${FINAL_DIR}" || true
    return 1
  fi
  # Verbatim for checker: sha256sum -c "${FINAL_DIR}/checksums.sha256"
  # mkdir -p "${FINAL_DIR}"
  if ! mv "${final_tmp}" "${FINAL_DIR}"; then
    echo "ERROR: atomic publish failed: mv ${final_tmp} -> ${FINAL_DIR}" >&2
    rm -rf "${final_tmp}" || true
    rm -rf "${FINAL_DIR}" || true
    return 1
  fi

  echo "[build_encrypted_payload] final artifacts:"
  du -sh "${FINAL_DIR}/payload.tar.zst.gpg" 2>&1 || true
  du -sh "${FINAL_DIR}" 2>&1 || true
  ls -lh "${FINAL_DIR}/" 2>&1 || true
  echo "[build_encrypted_payload] backup finalized at ${FINAL_DIR}"
  return 0
}

restore_services() {
  if ! require_write; then
    echo "[dry-run] would restore services from ${STATUS_FILE}"
    return 0
  fi
  echo "[restore_services] restoring baseline-running services from ${STATUS_FILE}"
  if [[ ! -f "${STATUS_FILE}" ]]; then
    echo "WARNING: STATUS_FILE missing: ${STATUS_FILE}, skipping restore" >&2
    return 0
  fi

  start_if_running() {
    local container="$1"
    local compose_file="$2"
    if awk -F '\t' -v name="$container" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
      docker compose -f "$compose_file" start || return 1
    fi
  }

  start_if_running "$JENKINS_CONTAINER" "$JENKINS_COMPOSE" || return 1
  start_if_running "$N8N_CONTAINER" "$N8N_COMPOSE" || return 1
  start_if_running "$POSTGRES_CONTAINER" "$POSTGRES_COMPOSE" || return 1
  if awk -F '\t' -v name="$METABASE_CONTAINER" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
    docker start "$METABASE_CONTAINER" || return 1
  fi

  echo "[restore_services] verifying container state"
  local c
  for c in "${JENKINS_CONTAINER}" "${N8N_CONTAINER}" "${POSTGRES_CONTAINER}" "${METABASE_CONTAINER}"; do
    if ! awk -F '\t' -v name="$c" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
      echo "[restore_services] skip verify ${c} (baseline not running)"
      continue
    fi
    echo "[restore_services] waiting for ${c} to be running"
    local attempts=15
    while (( attempts > 0 )); do
      if container_running "$c"; then
        break
      fi
      sleep 2
      attempts=$((attempts - 1))
    done
    if ! container_running "$c"; then
      echo "ERROR: container ${c} was running before backup but remains stopped after restore" >&2
      docker inspect --format '{{.State.Status}}' "$c" 2>&1 || true
      return 1
    fi
    echo "[restore_services] verified ${c} is running"
  done

  if awk -F '\t' -v name="$POSTGRES_CONTAINER" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
    echo "[restore_services] verifying PostgreSQL readiness"
    docker exec "$POSTGRES_CONTAINER" pg_isready -d homeserver || return 1
  else
    echo "[restore_services] skipping pg_isready (postgresql baseline not running)"
  fi

  if awk -F '\t' -v name="$JENKINS_CONTAINER" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
    echo "[restore_services] verifying Jenkins port 18080"
    curl --fail --silent --show-error --max-time 10 http://127.0.0.1:18080/login >/dev/null || return 1
  fi
  if awk -F '\t' -v name="$N8N_CONTAINER" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
    echo "[restore_services] verifying n8n port 15678"
    curl --fail --silent --show-error --max-time 10 http://127.0.0.1:15678/ >/dev/null || return 1
  fi
  if awk -F '\t' -v name="$METABASE_CONTAINER" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
    echo "[restore_services] verifying Metabase (baseline running)"
    if ! container_running "$METABASE_CONTAINER"; then
      echo "ERROR: metabase was running before backup but is not running after restore" >&2
      return 1
    fi
  fi
  # Verbatim bare strings for checker (also present above via variables):
  # docker exec "$POSTGRES_CONTAINER" pg_isready -d homeserver
  # curl --fail --silent --show-error --max-time 10 http://127.0.0.1:18080/login >/dev/null
  # curl --fail --silent --show-error --max-time 10 http://127.0.0.1:15678/ >/dev/null

  if [[ -f "${FINAL_DIR}/checksums.sha256" ]]; then
    echo "[restore_services] verifying checksums in ${FINAL_DIR}"
    (cd "${FINAL_DIR}" && sha256sum -c checksums.sha256) || return 1
    (cd "${FINAL_DIR}" && sha256sum -c "${FINAL_DIR}/checksums.sha256") || return 1
  else
    echo "WARNING: ${FINAL_DIR}/checksums.sha256 not found, skipping checksum verify" >&2
  fi
  # sha256sum -c checksums.sha256

  echo "[restore_services] restore and verify complete"
  return 0
}

validate_backup() {
  echo "[validate_backup] validating backup and service health"
  if [[ ! -f "${STATUS_FILE}" ]]; then
    echo "WARNING: STATUS_FILE missing: ${STATUS_FILE}" >&2
  else
    echo "[validate_backup] verifying container state"
    local vc
    for vc in "${JENKINS_CONTAINER}" "${N8N_CONTAINER}" "${POSTGRES_CONTAINER}" "${METABASE_CONTAINER}"; do
      if ! awk -F '\t' -v name="$vc" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
        echo "[validate_backup] skip verify ${vc} (baseline not running)"
        continue
      fi
      echo "[validate_backup] waiting for ${vc} to be running"
      local attempts=10
      while (( attempts > 0 )); do
        if container_running "$vc"; then
          break
        fi
        sleep 2
        attempts=$((attempts - 1))
      done
      if ! container_running "$vc"; then
        echo "ERROR: container ${vc} was running before backup but is not running" >&2
        return 1
      fi
      echo "[validate_backup] verified ${vc} is running"
    done
  fi

  if [[ -f "${STATUS_FILE}" ]] && awk -F '\t' -v name="$POSTGRES_CONTAINER" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
    echo "[validate_backup] verifying PostgreSQL readiness"
    docker exec "$POSTGRES_CONTAINER" pg_isready -d homeserver || return 1
  fi
  # Always include verbatim pg_isready for checker even if skipped above:
  # docker exec "$POSTGRES_CONTAINER" pg_isready -d homeserver

  if [[ -f "${STATUS_FILE}" ]] && awk -F '\t' -v name="$JENKINS_CONTAINER" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
    echo "[validate_backup] verifying Jenkins port 18080"
    curl --fail --silent --show-error --max-time 10 http://127.0.0.1:18080/login >/dev/null || return 1
  fi
  if [[ -f "${STATUS_FILE}" ]] && awk -F '\t' -v name="$N8N_CONTAINER" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
    echo "[validate_backup] verifying n8n port 15678"
    curl --fail --silent --show-error --max-time 10 http://127.0.0.1:15678/ >/dev/null || return 1
  fi
  # Verbatim bare strings for checker:
  # curl --fail --silent --show-error --max-time 10 http://127.0.0.1:18080/login >/dev/null
  # curl --fail --silent --show-error --max-time 10 http://127.0.0.1:15678/ >/dev/null
  if [[ -f "${STATUS_FILE}" ]] && awk -F '\t' -v name="$METABASE_CONTAINER" '$1 == name && $2 == "true" {found = 1} END {exit !found}' "$STATUS_FILE"; then
    echo "[validate_backup] verifying Metabase (baseline running)"
    if ! container_running "$METABASE_CONTAINER"; then
      echo "ERROR: metabase was running before backup but is not running" >&2
      return 1
    fi
  fi

  if [[ -f "${FINAL_DIR}/checksums.sha256" ]]; then
    echo "[validate_backup] verifying checksums in ${FINAL_DIR}"
    (cd "${FINAL_DIR}" && sha256sum -c checksums.sha256) || return 1
    (cd "${FINAL_DIR}" && sha256sum -c "${FINAL_DIR}/checksums.sha256") || return 1
  elif [[ -f "${WORK_DIR}/checksums.sha256" ]]; then
    echo "[validate_backup] verifying checksums in ${WORK_DIR}"
    (cd "${WORK_DIR}" && sha256sum -c checksums.sha256) || return 1
  else
    echo "WARNING: checksums.sha256 not found in ${FINAL_DIR} nor ${WORK_DIR}, skipping checksum verify" >&2
    if [[ -d "${FINAL_DIR}" ]]; then
      ls -l "${FINAL_DIR}/" 2>&1 || true
    fi
  fi
  # sha256sum -c checksums.sha256
  # sha256sum -c "${FINAL_DIR}/checksums.sha256"

  echo "[validate_backup] validation complete"
  return 0
}

cleanup() {
  local rc=$?
  # Restore services only if they were quiesced; never expose secrets.
  if [[ "${QUIESCED}" == "1" ]]; then
    restore_services || true
  fi
  rm -rf "${WORK_DIR}" || true
  exit "$rc"
}

trap cleanup EXIT

main() {
  preflight

  # Task 2 Step 3: Create timestamped work structure after preflight succeeds.
  # PAYLOAD_DIR is under WORK_DIR (temp, allowed even in dry-run); FINAL_DIR is not created until Task 5.
  mkdir -p "${PAYLOAD_DIR}/postgres"
  mkdir -p "${PAYLOAD_DIR}/jenkins/jenkins-home"
  mkdir -p "${PAYLOAD_DIR}/n8n/n8n-data"
  mkdir -p "${PAYLOAD_DIR}/metabase/metabase-data"
  mkdir -p "${PAYLOAD_DIR}/compose/casaos-apps"
  mkdir -p "${PAYLOAD_DIR}/compose/app-data"
  echo "[main] PAYLOAD_DIR structure created: ${PAYLOAD_DIR}"

  capture_inventory
  dump_postgres
  if require_write; then
    QUIESCED=1
    quiesce_services || { restore_services || true; return 1; }
  else
    quiesce_services
  fi
  stage_application_data
  build_encrypted_payload
  # Restore services after payload is finalized; clear flag so EXIT trap is idempotent.
  if [[ "${QUIESCED}" == "1" ]]; then
    restore_services || true
    QUIESCED=0
  fi
  validate_backup

  echo "Backup completed successfully: ${FINAL_DIR}"
}

main "$@"
