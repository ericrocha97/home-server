# Home Server Docker Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and validate an encrypted backup of the current Docker applications before reinstalling Ubuntu Server.

**Architecture:** A shell workflow runs on the remote host through the existing `home-server` SSH alias. It captures Docker metadata, creates a logical PostgreSQL dump, quiesces only the relevant Compose projects, stages application data on the Linux filesystem, creates one compressed GnuPG-encrypted payload on `/ssd`, validates it, and restores the containers that were originally running. No Kubernetes or monitoring data is included.

**Tech Stack:** Bash, OpenSSH, Docker Engine 29.7.2, Docker Compose, PostgreSQL 17.4 utilities, GNU tar, zstd, GnuPG symmetric encryption, SHA-256 checksums.

## Global Constraints

- Use the existing SSH alias `home-server`; do not expose the server address or credentials in artifacts.
- Use `/ssd` as the destination and never format, delete, or overwrite existing data there.
- Treat `/ssd` as a `fuseblk` destination; preserve Linux metadata inside tar archives rather than relying on destination filesystem permissions.
- Include Jenkins, n8n, PostgreSQL, Metabase, Compose definitions, relevant Docker application data, and Docker inventory.
- Exclude Docker images, `/var/lib/docker` layers, build cache, Kubernetes state, Grafana, Prometheus, and dashboards.
- Never print environment variables, passwords, n8n credentials, Jenkins secrets, or GPG passphrases.
- Stop only Jenkins, n8n, PostgreSQL, and Metabase when it is running; preserve the initial running/stopped state.
- Generate a PostgreSQL logical dump before stopping PostgreSQL.
- Run all cleanup and service restoration paths through an `EXIT` trap.
- Do not commit the backup script, generated artifacts, or this plan unless the operator explicitly requests a commit.

---

## File Structure

The implementation creates one reusable, secret-free script in the repository:

- Create: `scripts/backup-docker-apps.sh` - remote-executable backup workflow with preflight, capture, encryption, validation, cleanup, and restoration.

The script creates these remote artifacts:

- Create remotely: `/ssd/home-server-backup-YYYY-MM-DD-HHMMSS/manifest.txt` - non-sensitive backup metadata.
- Create remotely: `/ssd/home-server-backup-YYYY-MM-DD-HHMMSS/docker-inventory.txt` - container, image, mount, port, and Compose inventory without environment values.
- Create remotely: `/ssd/home-server-backup-YYYY-MM-DD-HHMMSS/checksums.sha256` - checksums of the final artifacts.
- Create remotely: `/ssd/home-server-backup-YYYY-MM-DD-HHMMSS/restore-notes.md` - restoration order and captured versions.
- Create remotely: `/ssd/home-server-backup-YYYY-MM-DD-HHMMSS/payload.tar.zst.gpg` - encrypted application data and configuration.

No Kubernetes manifests or monitoring files are modified by this plan.

## Interfaces

The script runs locally for syntax and dry-run checks, and remotely with this
safe SSH workflow:

```bash
scp scripts/backup-docker-apps.sh home-server:/tmp/home-server-docker-backup.sh
ssh -tt home-server 'sudo -v'
ssh home-server 'sudo -n env BACKUP_DRY_RUN=1 bash /tmp/home-server-docker-backup.sh'
ssh -tt home-server 'sudo -n bash /tmp/home-server-docker-backup.sh'
ssh home-server 'rm -f /tmp/home-server-docker-backup.sh'
```

> **Note on remote permissions and `BACKUP_DRY_RUN` propagation:** The remote user needs `sudo` because the CasaOS
> Compose files are root-readable only (`root:root`, mode `0600`). Set `BACKUP_DRY_RUN` inside the remote `sudo`
> command as shown above; client-side environment assignments are not forwarded through SSH by default. `sudo -n`
> intentionally never prompts; run `ssh -tt home-server 'sudo -v'` first. Do not pipe the local script directly into
> a password-requiring root shell: SSH shares stdin with the remote command, so a sudo password prompt can consume
> script lines as password attempts. Copy the script to a remote file first. Running the script without `sudo` is
> unsafe because Docker-group access does not grant access to those Compose files and can allow partial execution
> before a failure is reported.

The script accepts these environment variables:

- `BACKUP_ROOT=/ssd` - destination filesystem.
- `BACKUP_MIN_FREE_GB=10` - minimum required free space.
- `BACKUP_DRY_RUN=0` - when `1`, perform read-only checks and inventory without stopping services or writing a payload.

The script exposes these internal functions for focused shell tests and review:

- `preflight()` - validates paths, tools, destination, and Docker access.
- `capture_inventory()` - writes non-sensitive host and Docker metadata.
- `dump_postgres()` - creates and verifies the `homeserver` dump and PostgreSQL globals dump.
- `quiesce_services()` - stops relevant Compose projects after successful database capture.
- `stage_application_data()` - copies container data and Compose/application files into a protected staging directory.
- `build_encrypted_payload()` - creates the compressed GnuPG payload, removes plaintext staging data, and writes checksums.
- `restore_services()` - starts only projects that were running before the backup.
- `validate_backup()` - checks archive readability, PostgreSQL dump structure, checksums, and service health.

### Task 1: Implement the Safe Script Skeleton

**Files:**
- Create: `scripts/backup-docker-apps.sh`

**Interfaces:**
- Consumes: `BACKUP_ROOT`, `BACKUP_MIN_FREE_GB`, `BACKUP_DRY_RUN`, Docker Compose project files, and the current Docker daemon.
- Produces: timestamped backup directory, encrypted payload, metadata files, and restored service state.

- [ ] **Step 1: Create the script header and immutable paths**

Add the following shell safety foundation:

```bash
#!/usr/bin/env bash
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
```

Create `PAYLOAD_DIR` only after preflight succeeds. Register an `EXIT` trap
that removes `WORK_DIR` and calls `restore_services` only when services were
successfully quiesced.

- [ ] **Step 2: Define the exact current service inputs**

Define the current Compose files and containers without embedding secrets:

```bash
readonly JENKINS_COMPOSE=/var/lib/casaos/apps/jenkins/docker-compose.yml
readonly N8N_COMPOSE=/var/lib/casaos/apps/n8n/docker-compose.yml
readonly POSTGRES_COMPOSE=/var/lib/casaos/apps/postgresql/docker-compose.yml
readonly METABASE_CONTAINER=metabase
readonly JENKINS_CONTAINER=Jenkins
readonly N8N_CONTAINER=n8n
readonly POSTGRES_CONTAINER=postgresql
readonly POSTGRES_DATABASE=homeserver
```

Use a `container_running()` helper based on `docker inspect --format
'{{.State.Running}}'`. Do not use `docker inspect` output containing
`.Config.Env`.

- [ ] **Step 3: Add the dry-run boundary**

Implement `require_write()` so all destination creation, service stopping,
data copying, encryption, and service restoration paths exit successfully
without side effects when `BACKUP_DRY_RUN=1`. The dry run must still validate
Docker access, source paths, tool availability, and current container state.

- [ ] **Step 4: Check shell syntax before remote execution**

Run:

```bash
bash -n scripts/backup-docker-apps.sh
```

Expected: exit code `0` and no output.

### Task 2: Add Preflight and Non-Sensitive Inventory

**Files:**
- Modify: `scripts/backup-docker-apps.sh`

**Interfaces:**
- Consumes: `/ssd`, `/DATA/AppData`, `/var/lib/casaos/apps`, Docker daemon, and Compose files.
- Produces: `manifest.txt`, `docker-inventory.txt`, and the baseline container status file.

- [ ] **Step 1: Validate the backup filesystem**

Inside `preflight()`, require the following checks:

```bash
test "$(findmnt -no TARGET /ssd)" = "/ssd"
test "$(findmnt -no SOURCE /ssd)" = "/dev/sdc1"
test ! -e "$FINAL_DIR"
free_kb="$(df -Pk /ssd | awk 'NR == 2 {print $4}')"
test "$free_kb" -ge "$((BACKUP_MIN_FREE_GB * 1024 * 1024))"
```

If the source device has changed after a reboot, fail with the observed
device and require the operator to update the destination decision rather
than writing to an unexpected filesystem.

- [ ] **Step 2: Validate required commands and source paths**

Require `docker`, `tar`, `zstd`, `gpg`, `sha256sum`, `findmnt`, `df`, and
`awk`. Require all three Compose files and the `/DATA/AppData` directory.
Fail before changing services if any requirement is missing.

- [ ] **Step 3: Create the timestamped work structure**

Create these directories with `mkdir -p` on the Linux root filesystem:

```text
${PAYLOAD_DIR}/postgres
${PAYLOAD_DIR}/jenkins/jenkins-home
${PAYLOAD_DIR}/n8n/n8n-data
${PAYLOAD_DIR}/metabase/metabase-data
${PAYLOAD_DIR}/compose/casaos-apps
${PAYLOAD_DIR}/compose/app-data
```

Do not create `FINAL_DIR` until every validation step succeeds.

- [ ] **Step 4: Capture service state**

Write one tab-separated line per relevant container to `STATUS_FILE`:

```text
container_name<TAB>running_boolean<TAB>status
```

Capture `Jenkins`, `n8n`, `postgresql`, and `metabase`. The restoration logic
must use this file rather than assuming all projects were running.

- [ ] **Step 5: Capture non-sensitive Docker metadata**

Write the following commands' output to `docker-inventory.txt` without
printing environment variables:

```bash
docker version
docker compose version
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
docker image ls --digests
docker volume ls
docker compose ls --all
```

For every container, record only name, image, status, mounts, port bindings,
and Compose labels. Do not record `.Config.Env`.

- [ ] **Step 6: Test the preflight and dry run**

Run:

```bash
scp scripts/backup-docker-apps.sh home-server:/tmp/home-server-docker-backup.sh
ssh -tt home-server 'sudo -v'
ssh home-server 'sudo -n env BACKUP_DRY_RUN=1 bash /tmp/home-server-docker-backup.sh'
ssh home-server 'rm -f /tmp/home-server-docker-backup.sh'
```

Expected: the command reports the destination, required source paths, and
container states, but does not create a final backup directory, stop a
container, prompt for GPG, or remove files.

### Task 3: Capture PostgreSQL and Quiesce Docker Applications

**Files:**
- Modify: `scripts/backup-docker-apps.sh`

**Interfaces:**
- Consumes: running `postgresql` container and Compose files.
- Produces: `postgres/homeserver.dump`, `postgres/globals.sql`, and a quiesced application state.

- [ ] **Step 1: Generate the custom-format database dump**

Run the dump without placing a password in the command line:

```bash
docker exec "$POSTGRES_CONTAINER" sh -c \
  'pg_dump -U "$POSTGRES_USER" -d homeserver --format=custom' \
  > "${PAYLOAD_DIR}/postgres/homeserver.dump"
```

- [ ] **Step 2: Generate PostgreSQL globals**

Use `homeserver` as the connection database because the server does not have
the default `postgres` database:

```bash
docker exec "$POSTGRES_CONTAINER" sh -c \
  'pg_dumpall -U "$POSTGRES_USER" -l homeserver --globals-only' \
  > "${PAYLOAD_DIR}/postgres/globals.sql"
```

- [ ] **Step 3: Verify dump outputs before stopping services**

Run `test -s` on both files. Validate the custom dump through the PostgreSQL
container before it is stopped:

```bash
docker exec -i "$POSTGRES_CONTAINER" pg_restore --list - \
  < "${PAYLOAD_DIR}/postgres/homeserver.dump" \
  > "${WORK_DIR}/postgres-restore-list.txt"
```

If any check fails, invoke the cleanup trap and leave all services running.

- [ ] **Step 4: Stop Jenkins and n8n**

Stop only the projects whose containers were running at baseline:

```bash
if [[ "$(awk -F '\t' '$1 == "Jenkins" {print $2}' "$STATUS_FILE")" == "true" ]]; then
  docker compose -f "$JENKINS_COMPOSE" stop
fi
if [[ "$(awk -F '\t' '$1 == "n8n" {print $2}' "$STATUS_FILE")" == "true" ]]; then
  docker compose -f "$N8N_COMPOSE" stop
fi
```

Do not run `down`, `rm`, `prune`, or `systemctl stop docker`.

- [ ] **Step 5: Stop PostgreSQL after the dump**

Stop PostgreSQL after the logical dump succeeds:

```bash
if [[ "$(awk -F '\t' '$1 == "postgresql" {print $2}' "$STATUS_FILE")" == "true" ]]; then
  docker compose -f "$POSTGRES_COMPOSE" stop
fi
if [[ "$(awk -F '\t' '$1 == "metabase" {print $2}' "$STATUS_FILE")" == "true" ]]; then
  docker stop "$METABASE_CONTAINER"
fi
```

Stop Metabase only when its baseline status is running. Do not change its
currently stopped state.

### Task 4: Stage Application Data and Compose Configuration

**Files:**
- Modify: `scripts/backup-docker-apps.sh`

**Interfaces:**
- Consumes: stopped Jenkins, n8n, PostgreSQL, and Metabase containers; Compose files; `/DATA/AppData`.
- Produces: complete staged application data under `PAYLOAD_DIR`.

- [ ] **Step 1: Copy Jenkins data from the stopped container**

Copy the contents of `/var/jenkins_home` into
`${PAYLOAD_DIR}/jenkins/jenkins-home`. Include `jobs`, `plugins`, `workspace`,
`secrets`, and configuration files. Do not filter the Jenkins home directory.

```bash
docker cp "${JENKINS_CONTAINER}:/var/jenkins_home/." \
  "${PAYLOAD_DIR}/jenkins/jenkins-home/"
```

- [ ] **Step 2: Copy n8n data from the stopped container**

Copy the contents of `/home/node/.n8n` into
`${PAYLOAD_DIR}/n8n/n8n-data`. Verify that `database.sqlite`, its `-wal` and
`-shm` files, `config`, `binaryData`, and `nodes` are present without printing
their contents.

```bash
docker cp "${N8N_CONTAINER}:/home/node/.n8n/." \
  "${PAYLOAD_DIR}/n8n/n8n-data/"
test -s "${PAYLOAD_DIR}/n8n/n8n-data/database.sqlite"
test -f "${PAYLOAD_DIR}/n8n/n8n-data/config"
```

- [ ] **Step 3: Copy Metabase data**

Copy `/metabase-data` from the stopped `metabase` container when the path is
available. If the container has no data at that path, record that fact in the
manifest and continue because Metabase is currently stopped.

```bash
if docker cp "${METABASE_CONTAINER}:/metabase-data/." \
  "${PAYLOAD_DIR}/metabase/metabase-data/"; then
  printf '%s\n' 'Metabase data captured' >> "${WORK_DIR}/manifest-events.txt"
else
  printf '%s\n' 'Metabase data path unavailable' >> "${WORK_DIR}/manifest-events.txt"
fi
```

- [ ] **Step 4: Copy Compose definitions**

Archive the complete `/var/lib/casaos/apps` tree into
`${PAYLOAD_DIR}/compose/casaos-apps`, preserving `.env` files inside the
encrypted payload. Include the stopped `passionate_jeanie` project definition
so it can be reviewed during restoration.

```bash
tar --numeric-owner -C /var/lib/casaos/apps -cf - . \
  | tar -C "${PAYLOAD_DIR}/compose/casaos-apps" -xf -
test -f "${PAYLOAD_DIR}/compose/casaos-apps/jenkins/docker-compose.yml"
test -f "${PAYLOAD_DIR}/compose/casaos-apps/n8n/docker-compose.yml"
test -f "${PAYLOAD_DIR}/compose/casaos-apps/postgresql/docker-compose.yml"
```

- [ ] **Step 5: Copy non-PostgreSQL Docker application data**

Archive `/DATA/AppData` into `${PAYLOAD_DIR}/compose/app-data`, excluding the
raw `postgresql` data directory because the logical dump is the supported
restore source. Include application directories such as Jenkins, n8n,
Metabase, btop, and Firefox when present.

```bash
tar --exclude=./postgresql --numeric-owner -C /DATA/AppData -cf - . \
  | tar -C "${PAYLOAD_DIR}/compose/app-data" -xf -
```

Use tar extraction into the Linux staging directory so source metadata is
preserved before the final payload is created. If the source permissions block
the archive, fail clearly rather than silently producing a partial backup.

- [ ] **Step 6: Record staged sizes**

Write `du -sh` results for each payload section into `manifest.txt` without
including file contents or secrets.

### Task 5: Compress, Encrypt, Checksum, and Finalize

**Files:**
- Modify: `scripts/backup-docker-apps.sh`

**Interfaces:**
- Consumes: complete `PAYLOAD_DIR` and inventory files.
- Produces: finalized `/ssd/home-server-backup-YYYY-MM-DD-HHMMSS/`.

- [ ] **Step 1: Create the compressed plaintext archive in temporary storage**

Run:

```bash
tar --zstd --numeric-owner \
  -C "${PAYLOAD_DIR}" \
  -cf "${WORK_DIR}/payload.tar.zst" \
  .
```

Do not write an unencrypted payload to `/ssd`.

- [ ] **Step 2: Encrypt with interactive GnuPG**

Run from a terminal with an allocated TTY so the operator can enter the
passphrase directly:

```bash
gpg --symmetric --cipher-algo AES256 \
  --output "${WORK_DIR}/payload.tar.zst.gpg" \
  "${WORK_DIR}/payload.tar.zst"
```

Never add a passphrase to the command arguments, environment, script, logs, or
conversation. Remove `${WORK_DIR}/payload.tar.zst` immediately after the
encrypted file is created.

- [ ] **Step 3: Validate encrypted payload readability**

Decrypt the payload to a pipe and list its contents:

```bash
gpg --decrypt "${WORK_DIR}/payload.tar.zst.gpg" \
  | tar --zstd -tf - \
  > "${WORK_DIR}/payload-list.txt"
```

The operator may need to confirm the passphrase through the local GPG agent.

- [ ] **Step 4: Assemble non-sensitive metadata**

Write `restore-notes.md` with the current image versions, PostgreSQL major
version, source paths, restore order, and the explicit note that the Docker
Agent secret must be regenerated. Do not include environment values.

- [ ] **Step 5: Create the final directory and checksums**

Create the final timestamped directory only now, copy `manifest.txt`,
`docker-inventory.txt`, `restore-notes.md`, and the encrypted payload into it,
then run:

```bash
(cd "${FINAL_DIR}" && sha256sum payload.tar.zst.gpg manifest.txt docker-inventory.txt restore-notes.md) \
  > "${FINAL_DIR}/checksums.sha256"
```

Verify the checksum file before reporting success.

- [ ] **Step 6: Remove temporary data and print the final location**

Remove `WORK_DIR` through the cleanup trap and print only the final directory,
artifact sizes, checksum result, and service restoration result.

### Task 6: Restore Services and Verify the Server

**Files:**
- Modify: `scripts/backup-docker-apps.sh`

**Interfaces:**
- Consumes: `STATUS_FILE`, Compose files, and completed backup artifacts.
- Produces: the original running/stopped service state and a validated backup report.

- [ ] **Step 1: Implement conditional restoration**

For each baseline-running project, run the matching Compose `start` command:

```bash
start_if_running() {
  local container="$1"
  local compose_file="$2"
  if awk -F '\t' -v name="$container" \
    '$1 == name && $2 == "true" {found = 1} END {exit !found}' \
    "$STATUS_FILE"; then
    docker compose -f "$compose_file" start
  fi
}

start_if_running "$JENKINS_CONTAINER" "$JENKINS_COMPOSE"
start_if_running "$N8N_CONTAINER" "$N8N_COMPOSE"
start_if_running "$POSTGRES_CONTAINER" "$POSTGRES_COMPOSE"
if awk -F '\t' -v name="$METABASE_CONTAINER" \
  '$1 == name && $2 == "true" {found = 1} END {exit !found}' \
  "$STATUS_FILE"; then
  docker start "$METABASE_CONTAINER"
fi
```

Run the Metabase start command only if the baseline status was running. Never
start a project that was originally stopped.

- [ ] **Step 2: Verify container state**

Wait for Docker to report the expected containers as running. Fail if any
container that was running before the backup remains stopped or exited.

- [ ] **Step 3: Verify PostgreSQL and application ports**

Run `pg_isready` inside the PostgreSQL container for `homeserver`. Verify the
known current HTTP endpoints on ports `18080` for Jenkins and `15678` for n8n
with bounded `curl` requests. Verify Metabase only when it was running before
the backup.

```bash
docker exec "$POSTGRES_CONTAINER" pg_isready -d homeserver
curl --fail --silent --show-error --max-time 10 \
  http://127.0.0.1:18080/login >/dev/null
curl --fail --silent --show-error --max-time 10 \
  http://127.0.0.1:15678/ >/dev/null
```

- [ ] **Step 4: Verify final backup checksums**

Run from the final directory:

```bash
sha256sum -c checksums.sha256
```

Expected: all listed files report `OK`.

### Task 7: Test and Review the Backup Workflow

**Files:**
- Modify: `scripts/backup-docker-apps.sh`

**Interfaces:**
- Consumes: local shell tooling, remote `home-server`, and the generated backup.
- Produces: verified script behavior and a human-readable final report.

- [ ] **Step 1: Run static shell checks**

Run:

```bash
bash -n scripts/backup-docker-apps.sh
shellcheck scripts/backup-docker-apps.sh
```

Expected: syntax check succeeds and ShellCheck reports no errors. If
ShellCheck is unavailable, record that limitation and still run `bash -n`.

- [ ] **Step 2: Run the remote dry run**

Run:

```bash
scp scripts/backup-docker-apps.sh home-server:/tmp/home-server-docker-backup.sh
ssh -tt home-server 'sudo -v'
ssh home-server 'sudo -n env BACKUP_DRY_RUN=1 bash /tmp/home-server-docker-backup.sh'
ssh home-server 'rm -f /tmp/home-server-docker-backup.sh'
```

Verify no service state changed, no GPG prompt occurred, and no final backup
directory was created.

- [ ] **Step 3: Run the real backup with a TTY**

Run:

```bash
scp scripts/backup-docker-apps.sh home-server:/tmp/home-server-docker-backup.sh
ssh -tt home-server 'sudo -v'
ssh -tt home-server 'sudo -n bash /tmp/home-server-docker-backup.sh'
ssh home-server 'rm -f /tmp/home-server-docker-backup.sh'
```

Enter the GPG passphrase directly in the terminal. Do not send it through the
assistant, shell arguments, or environment variables.

- [ ] **Step 4: Inspect the final report**

Confirm the script reports:

- Final path below `/ssd`.
- Payload and metadata sizes.
- Valid checksums.
- Valid PostgreSQL dump.
- Successful service restoration.
- No Kubernetes or monitoring artifacts included.

- [ ] **Step 5: Leave the repository uncommitted**

Review `git status --short` and `git diff -- scripts/backup-docker-apps.sh`.
Do not commit the script or generated backup unless the operator explicitly
requests version control integration.

## Plan Self-Review

- Spec coverage: preflight, inventory, PostgreSQL logical backup, service
  quiescing, Jenkins/n8n/Metabase data, Compose configuration, encryption,
  checksums, failure recovery, service restoration, and acceptance checks are
  covered by Tasks 1 through 7.
- Scope coverage: Kubernetes, Grafana, Prometheus, dashboards, images, layers,
  and build cache are explicitly excluded in the global constraints and Task 4.
- Secret safety: no command records environment values; the payload is
  encrypted before leaving temporary Linux storage; the passphrase is always
  operator-entered.
- Completeness scan: no unresolved marker or unspecified implementation step
  is required.
- Type/interface consistency: all tasks use the same `BACKUP_ROOT`, `FINAL_DIR`,
  `WORK_DIR`, `PAYLOAD_DIR`, `STATUS_FILE`, container names, and Compose paths.
