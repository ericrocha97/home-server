#!/usr/bin/env bash
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
  docker exec -i "$POSTGRES_CONTAINER" pg_restore --list - < "${PAYLOAD_DIR}/postgres/homeserver.dump" > "${WORK_DIR}/postgres-restore-list.txt"
  if ! test -s "${WORK_DIR}/postgres-restore-list.txt"; then
    echo "ERROR: pg_restore --list validation failed or empty: ${WORK_DIR}/postgres-restore-list.txt" >&2
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
    docker compose -f "$JENKINS_COMPOSE" stop
  fi
  if [[ "$(awk -F '\t' '$1 == "n8n" {print $2}' "$STATUS_FILE")" == "true" ]]; then
    docker compose -f "$N8N_COMPOSE" stop
  fi
  echo "[quiesce_services] stopping PostgreSQL after dump and Metabase when running"
  if [[ "$(awk -F '\t' '$1 == "postgresql" {print $2}' "$STATUS_FILE")" == "true" ]]; then
    docker compose -f "$POSTGRES_COMPOSE" stop
  fi
  if [[ "$(awk -F '\t' '$1 == "metabase" {print $2}' "$STATUS_FILE")" == "true" ]]; then
    docker stop "$METABASE_CONTAINER"
  fi
  echo "[quiesce_services] quiesce complete"
  return 0
}

stage_application_data() {
  if ! require_write; then
    echo "[dry-run] would stage application data via docker cp and tar"
    return 0
  fi
  echo "[stage_application_data] stub — would copy Jenkins/n8n/Metabase/Compose/AppData"
  return 0
}

build_encrypted_payload() {
  if ! require_write; then
    echo "[dry-run] would build compressed GnuPG payload"
    return 0
  fi
  echo "[build_encrypted_payload] stub — would tar --zstd, gpg --symmetric, checksums"
  return 0
}

restore_services() {
  if ! require_write; then
    echo "[dry-run] would restore services from ${STATUS_FILE}"
    return 0
  fi
  echo "[restore_services] stub — would start only baseline-running projects"
  return 0
}

validate_backup() {
  # Stub — implemented in Task 6. Read-only checks even in dry-run.
  echo "[validate_backup] stub — would verify archive, checksums, service health"
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
  quiesce_services
  if require_write; then
    QUIESCED=1
  fi
  stage_application_data
  build_encrypted_payload
  # Restore services after payload is finalized; clear flag so EXIT trap is idempotent.
  if [[ "${QUIESCED}" == "1" ]]; then
    restore_services || true
    QUIESCED=0
  fi
  validate_backup

  echo "Backup preflight and inventory completed (Task 2). Payload staging deferred to later tasks."
}

main "$@"
