#!/usr/bin/env bash
# shellcheck disable=SC2155
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
  # Stub for Task 1 — full validation implemented in Task 2.
  # Must still validate Docker access, source paths, tool availability,
  # and container state even when BACKUP_DRY_RUN=1 (no gating here).
  # Reference service constants so shellcheck sees them as used (SC2034).
  : "${JENKINS_COMPOSE}" "${N8N_COMPOSE}" "${POSTGRES_COMPOSE}"
  : "${METABASE_CONTAINER}" "${JENKINS_CONTAINER}" "${N8N_CONTAINER}" "${POSTGRES_CONTAINER}" "${POSTGRES_DATABASE}"
  echo "[preflight] BACKUP_ROOT=${BACKUP_ROOT} BACKUP_MIN_FREE_GB=${BACKUP_MIN_FREE_GB} BACKUP_DRY_RUN=${BACKUP_DRY_RUN}"
  echo "[preflight] FINAL_DIR=${FINAL_DIR} WORK_DIR=${WORK_DIR}"
  echo "[preflight] checking required tools and source paths (stub)"
  return 0
}

capture_inventory() {
  # Stub — implemented in Task 2. Writes docker-inventory.txt without env vars.
  echo "[capture_inventory] stub — would write docker-inventory.txt"
  return 0
}

dump_postgres() {
  if ! require_write; then
    echo "[dry-run] would dump PostgreSQL database ${POSTGRES_DATABASE} via docker exec ${POSTGRES_CONTAINER}"
    return 0
  fi
  echo "[dump_postgres] stub — would run pg_dump custom format and pg_dumpall globals"
  return 0
}

quiesce_services() {
  if ! require_write; then
    echo "[dry-run] would quiesce services (stop Jenkins, n8n, PostgreSQL, Metabase when running)"
    return 0
  fi
  echo "[quiesce_services] stub — would stop relevant Compose projects"
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

  # PAYLOAD_DIR is created only after preflight succeeds (Task 1 constraint).
  if ! require_write; then
    echo "[dry-run] would create PAYLOAD_DIR=${PAYLOAD_DIR} (skipped)"
  else
    mkdir -p "${PAYLOAD_DIR}"
  fi

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

  echo "Backup skeleton completed (Task 1). Full workflow implemented in later tasks."
}

main "$@"
