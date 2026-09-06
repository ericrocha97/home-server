#!/usr/bin/env bash
# Slice 3 end-to-end verification — final platform foundation.
#
# Read-only live checks against the provisioned host: Kubernetes workloads
# (monitoring, Portainer, labmonitor foundation), the Docker socket proxy
# boundary, the Docker metrics exporter, Jenkins provider contracts, the
# Grafana Prometheus datasource, and discovery sources.
#
# Secret safety: credentials come only from the process environment or from
# live Kubernetes Secret objects. This script never reads host-rendered
# credential files, never enables shell tracing, and never logs a credential
# value. Values stay in local variables that are only handed to curl or
# kubectl through their standard authentication flags.
#
# Firewall safety: this script never changes firewall state. It only inspects
# (`ufw status`, `iptables -S/-L`, socket bindings) and probes from an
# authorized ephemeral k3s pod. Failing closed is the expected result for
# every negative check.
#
# Usage (run on the server host, as root or via sudo):
#   SERVER_LAN_IP=192.0.2.10 \
#   JENKINS_LABMONITOR_API_TOKEN='<token from Vault>' \
#   GRAFANA_ADMIN_PASSWORD='<password from Vault>' \
#   ./scripts/verify/slice3.sh
#
# Optional overrides:
#   KUBECONFIG=/etc/rancher/k3s/k3s.yaml  (default when KUBECONFIG is unset)
#   K3S_POD_CIDR=10.42.0.0/16
#   ENVIRONMENT_NAME=lab|prod             (default lab)
#   BASE_DOMAIN=lab.arpa                  (default derived from ENVIRONMENT_NAME)
#   PROMETHEUS_RETENTION_EXPECTED=15d
#   JENKINS_PORT=18080  DOCKER_PROXY_PORT=12375
#   JENKINS_LABMONITOR_USER=labmonitor-api
#   GRAFANA_ADMIN_USER=admin
#   PROBE_IMAGE=curlimages/curl:8.11.1
#
# A separate LAN/VPN client must still prove the negative boundary by hand
# (this host cannot prove a remote denial by itself):
#   curl --connect-timeout 5 "http://<server-lan-ip>:12375/version"  # must fail
# Internet exposure is proven by the absence of any port-forward/Ingress for
# 12375 plus the DOCKER-USER DROP rule asserted below.
set -Eeuo pipefail

KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
export KUBECONFIG
K3S_POD_CIDR="${K3S_POD_CIDR:-10.42.0.0/16}"
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-lab}"
if [[ -z "${BASE_DOMAIN:-}" ]]; then
  if [[ "$ENVIRONMENT_NAME" == "prod" ]]; then BASE_DOMAIN="home.arpa"; else BASE_DOMAIN="lab.arpa"; fi
fi
PROMETHEUS_RETENTION_EXPECTED="${PROMETHEUS_RETENTION_EXPECTED:-15d}"
JENKINS_PORT="${JENKINS_PORT:-18080}"
DOCKER_PROXY_PORT="${DOCKER_PROXY_PORT:-12375}"
JENKINS_LABMONITOR_USER="${JENKINS_LABMONITOR_USER:-labmonitor-api}"
GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
PROBE_IMAGE="${PROBE_IMAGE:-curlimages/curl:8.11.1}"
MONITORING_NS="monitoring"
PORTAINER_NS="portainer"
LABMONITOR_NS="labmonitor"

SUDO=""
if [[ "$(id -u)" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

PASS=0
FAIL=0
FAILED_CHECKS=()

log() { printf '[slice3] %s\n' "$*"; }
pass() { PASS=$((PASS + 1)); printf '[slice3] PASS: %s\n' "$*"; }
fail() {
  FAIL=$((FAIL + 1)); FAILED_CHECKS+=("$1")
  printf '[slice3] FAIL: %s\n' "$*" >&2
}

# Wrap a named check so one failure never aborts the remaining suite.
run_check() {
  local name="$1"; shift
  log "--- $name ---"
  if "$@" >/tmp/slice3-check.log 2>&1; then
    pass "$name"
  else
    fail "$name (see output above)"
    sed 's/^/[slice3]   /' /tmp/slice3-check.log >&2 || true
  fi
}

require_cmd() {
  for bin in "$@"; do
    command -v "$bin" >/dev/null 2>&1 || { printf 'missing required command: %s\n' "$bin" >&2; return 1; }
  done
}

K() { kubectl --kubeconfig="$KUBECONFIG" "$@"; }

# ---------------------------------------------------------------------------
# Section: Kubernetes API reachability and kubeconfig contract
# ---------------------------------------------------------------------------
check_kubeconfig() {
  require_cmd kubectl || return 1
  [[ -n "$KUBECONFIG" ]] || { printf 'KUBECONFIG is empty\n' >&2; return 1; }
  [[ -r "$KUBECONFIG" ]] || { printf 'kubeconfig not readable: %s\n' "$KUBECONFIG" >&2; return 1; }
  K cluster-info >/dev/null || return 1
}

# ---------------------------------------------------------------------------
# Section: Prometheus monitoring workloads Ready
# ---------------------------------------------------------------------------
check_monitoring_pods_ready() {
  require_cmd kubectl || return 1
  K -n "$MONITORING_NS" wait --for=condition=available deployment \
    -l app.kubernetes.io/name=grafana --timeout=60s >/dev/null || return 1
  K -n "$MONITORING_NS" wait --for=condition=Ready pod \
    -l app.kubernetes.io/name=prometheus --timeout=60s >/dev/null || return 1
  K -n "$MONITORING_NS" rollout status daemonset \
    -l app.kubernetes.io/name=prometheus-node-exporter --timeout=60s >/dev/null || return 1
  K -n "$MONITORING_NS" wait --for=condition=available deployment \
    -l app.kubernetes.io/name=kube-state-metrics --timeout=60s >/dev/null || return 1
  K -n "$MONITORING_NS" wait --for=condition=available deployment/docker-metrics-exporter \
    --timeout=60s >/dev/null || return 1
  local not_ready
  not_ready="$(K -n "$MONITORING_NS" get pods --no-headers 2>/dev/null | awk '$3 !~ /Completed/ {split($2,a,"/"); if (a[1]+0 != a[2]+0) print $1}' || true)"
  [[ -z "$not_ready" ]] || { printf 'monitoring pods not Ready: %s\n' "$not_ready" >&2; return 1; }
}

# ---------------------------------------------------------------------------
# Section: Portainer Server and Kubernetes Agent Ready
# ---------------------------------------------------------------------------
check_portainer_pods_ready() {
  require_cmd kubectl || return 1
  K -n "$PORTAINER_NS" wait --for=condition=available deployment/portainer --timeout=60s >/dev/null || return 1
  K -n "$PORTAINER_NS" wait --for=condition=available deployment/portainer-agent --timeout=60s >/dev/null || return 1
  local svc eps
  for svc in portainer portainer-agent; do
    eps="$(K -n "$PORTAINER_NS" get endpoints "$svc" -o jsonpath='{.subsets[*].addresses[*].ip}')" || return 1
    [[ -n "$eps" ]] || { printf 'Portainer endpoints empty for %s\n' "$svc" >&2; return 1; }
  done
}

# ---------------------------------------------------------------------------
# Section: labmonitor namespace, ServiceAccount, ConfigMaps, Secrets
# ---------------------------------------------------------------------------
check_labmonitor_foundation() {
  require_cmd kubectl python3 || return 1
  K -n "$LABMONITOR_NS" get serviceaccount labmonitor-api -o name >/dev/null || return 1
  K -n "$LABMONITOR_NS" get configmap labmonitor-catalog -o name >/dev/null || return 1
  K -n "$LABMONITOR_NS" get configmap labmonitor-provider-config -o name >/dev/null || return 1
  K -n "$LABMONITOR_NS" get secret labmonitor-jenkins-readonly -o name >/dev/null || return 1
  local keys
  keys="$(K -n "$LABMONITOR_NS" get secret labmonitor-jenkins-readonly -o json | python3 -c 'import json,sys; print(" ".join(sorted(json.load(sys.stdin)["data"].keys())))')" || return 1
  [[ "$keys" == "api-token username" ]] || { printf 'jenkins readonly Secret keys must be exactly [api-token username], got [%s]\n' "$keys" >&2; return 1; }
}

# No product Deployment may exist: Slice 3 provisions only the foundation.
check_no_labmonitor_api_deployment() {
  require_cmd kubectl python3 || return 1
  if K -n "$LABMONITOR_NS" get deployment labmonitor-api >/dev/null 2>&1; then
    printf 'labmonitor-api Deployment must not exist in Slice 3\n' >&2; return 1
  fi
  local found
  found="$(K get deployments,statefulsets,daemonsets -A -o json 2>/dev/null | python3 -c 'import json,sys; print(" ".join(sorted({i["metadata"]["name"] for i in json.load(sys.stdin)["items"]})))')" || return 1
  case " $found " in
    *" labmonitor-api "*) printf 'unexpected labmonitor-api workload: %s\n' "$found" >&2; return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Section: Prometheus and Grafana PVCs Bound (local-path persistence)
# ---------------------------------------------------------------------------
check_pvcs_bound() {
  require_cmd kubectl python3 || return 1
  local report
  report="$(K -n "$MONITORING_NS" get pvc -o json | python3 -c '
import json, sys
items = json.load(sys.stdin)["items"]
for i in items:
    print(i["metadata"]["name"], i["status"].get("phase", "?"), (i["spec"] or {}).get("storageClassName", "?"))
')" || return 1
  [[ -n "$report" ]] || { printf 'no PVCs in %s\n' "$MONITORING_NS" >&2; return 1; }
  printf '%s\n' "$report"
  local unbound
  unbound="$(printf '%s\n' "$report" | awk '$2 != "Bound" {print $1}')"
  [[ -z "$unbound" ]] || { printf 'PVCs not Bound: %s\n' "$unbound" >&2; return 1; }
  printf '%s\n' "$report" | grep -qi prometheus || { printf 'no Prometheus PVC\n' >&2; return 1; }
  printf '%s\n' "$report" | grep -qi grafana || { printf 'no Grafana PVC\n' >&2; return 1; }
}

# ---------------------------------------------------------------------------
# Section: Prometheus retention (15d default or inventory override)
# ---------------------------------------------------------------------------
check_prometheus_retention() {
  require_cmd kubectl || return 1
  local retention=""
  retention="$(K -n "$MONITORING_NS" get prometheus -o jsonpath='{.items[0].spec.retention}' 2>/dev/null || true)"
  if [[ -z "$retention" ]]; then
    retention="$(K -n "$MONITORING_NS" get statefulset -o jsonpath='{range .items[*]}{range .spec.template.spec.containers[0].args[*]}{.}{"\n"}{end}{end}' 2>/dev/null | grep -o 'storage.tsdb.retention.time=[^ ]*' | head -n1 | cut -d= -f2 || true)"
  fi
  [[ -n "$retention" ]] || { printf 'could not determine Prometheus retention\n' >&2; return 1; }
  printf 'retention=%s expected=%s\n' "$retention" "$PROMETHEUS_RETENTION_EXPECTED"
  [[ "$retention" == "$PROMETHEUS_RETENTION_EXPECTED" ]] || return 1
}

# ---------------------------------------------------------------------------
# Port-forward helper (background, cleaned by trap)
# ---------------------------------------------------------------------------
PF_PIDS=""
pf_start() {
  # pf_start <namespace> <svc> <local-port> <remote-port>
  require_cmd kubectl curl || return 1
  K -n "$1" port-forward "svc/$2" "$3:$4" >/tmp/slice3-pf-"$2".log 2>&1 &
  local pid=$!
  PF_PIDS="$PF_PIDS $pid"
  local attempt=0
  while ! curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:$3/-/healthy" >/dev/null 2>&1 \
    && ! curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:$3/api/health" >/dev/null 2>&1 \
    && ! curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:$3/healthz" >/dev/null 2>&1 \
    && ! curl -fsS --connect-timeout 2 --max-time 5 "http://127.0.0.1:$3/api/status" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [[ "$attempt" -ge 20 ]]; then printf 'port-forward svc/%s never became ready\n' "$2" >&2; return 1; fi
    sleep 2
  done
}
pf_stop_all() {
  local pid
  for pid in $PF_PIDS; do kill "$pid" >/dev/null 2>&1 || true; done
  PF_PIDS=""
}
trap pf_stop_all EXIT

# ---------------------------------------------------------------------------
# Section: Prometheus targets UP (node-exporter, kubelet/cAdvisor,
# kube-state-metrics, Docker exporter, Jenkins)
# ---------------------------------------------------------------------------
check_prometheus_targets_up() {
  require_cmd kubectl curl python3 || return 1
  pf_start "$MONITORING_NS" prometheus 19090 9090 || return 1
  local targets missing
  targets="$(curl -fsS --connect-timeout 5 --max-time 20 'http://127.0.0.1:19090/api/v1/targets?state=active')" || { pf_stop_all; return 1; }
  missing="$(printf '%s' "$targets" | python3 -c '
import json, sys
doc = json.loads(sys.stdin.read())
required = ["node-exporter", "kubelet", "kube-state-metrics", "docker-metrics-exporter", "jenkins"]
seen = set()
for t in doc["data"]["activeTargets"]:
    labels, health = t.get("labels", {}), t.get("health", "")
    job = labels.get("job", "")
    for r in required:
        if r in job and health == "up":
            seen.add(r)
print(" ".join(sorted(set(required) - seen)))
')" || { pf_stop_all; return 1; }
  pf_stop_all
  [[ -z "$missing" ]] || { printf 'Prometheus targets not UP: %s\n' "$missing" >&2; return 1; }
}

# ---------------------------------------------------------------------------
# Ephemeral k3s probe pod (authorized pod-CIDR source for the proxy).
# Probing from a pod proves the pod-CIDR allow path; the pod IP is logged so
# NAT behavior stays observable (see header note on SNAT).
# ---------------------------------------------------------------------------
probe_from_k3s() {
  # probe_from_k3s <name-suffix> <curl-args...> — runs curl inside a one-shot pod.
  require_cmd kubectl || return 1
  local suffix="$1"; shift
  local pod="slice3-probe-${suffix}-$$-$(date +%s)"
  timeout 120 kubectl --kubeconfig="$KUBECONFIG" run "$pod" \
    --image="$PROBE_IMAGE" --restart=Never --rm -i --command -- curl "$@"
}

check_proxy_get_from_k3s() {
  require_cmd kubectl || return 1
  local base="http://${SERVER_LAN_IP}:${DOCKER_PROXY_PORT}"
  local out
  out="$(probe_from_k3s get-version -fsS --connect-timeout 5 --max-time 20 "$base/version")" || return 1
  printf '%s' "$out" | grep -q '"Version"' || { printf 'proxy /version missing Version field\n' >&2; return 1; }
  probe_from_k3s get-info -fsS --connect-timeout 5 --max-time 20 "$base/info" >/dev/null || return 1
  probe_from_k3s get-containers -fsS --connect-timeout 5 --max-time 20 "$base/containers/json" >/dev/null || return 1
  log "Docker proxy GET checks from k3s pod succeeded (pod CIDR ${K3S_POD_CIDR}, proxy ${SERVER_LAN_IP}:${DOCKER_PROXY_PORT})"
}

check_proxy_mutating_denied() {
  require_cmd kubectl || return 1
  local base="http://${SERVER_LAN_IP}:${DOCKER_PROXY_PORT}"
  local code
  code="$(timeout 120 kubectl --kubeconfig="$KUBECONFIG" run "slice3-mut-$$-$(date +%s)" \
    --image="$PROBE_IMAGE" --restart=Never --rm -i --command -- \
    curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 20 \
    -X POST "$base/containers/create?name=slice3-must-fail")" || return 1
  [[ -n "$code" ]] || { printf 'proxy mutating probe produced no HTTP code\n' >&2; return 1; }
  case "$code" in
    2*) printf 'proxy accepted mutating POST (HTTP %s), must reject\n' "$code" >&2; return 1 ;;
    *) log "proxy rejected mutating POST with HTTP $code" ;;
  esac
}

# ---------------------------------------------------------------------------
# Section: k3s pod CIDR reaches Jenkins with authentication.
# Credentials travel only as a Secret reference into the probe pod; the host
# command line carries variable names, never values.
# ---------------------------------------------------------------------------
check_jenkins_from_k3s_authenticated() {
  require_cmd kubectl || return 1
  K -n "$LABMONITOR_NS" get secret labmonitor-jenkins-readonly -o name >/dev/null || return 1
  local pod="slice3-jk-$$-$(date +%s)"
  K apply -f - >/dev/null <<EOF || return 1
apiVersion: v1
kind: Pod
metadata:
  name: $pod
  namespace: $LABMONITOR_NS
spec:
  restartPolicy: Never
  containers:
    - name: probe
      image: $PROBE_IMAGE
      command: ["sh", "-c", "sleep 90"]
      env:
        - name: PROBE_JENKINS_USER
          valueFrom:
            secretKeyRef: {name: labmonitor-jenkins-readonly, key: username}
        - name: PROBE_JENKINS_TOKEN
          valueFrom:
            secretKeyRef: {name: labmonitor-jenkins-readonly, key: api-token}
EOF
  K -n "$LABMONITOR_NS" wait --for=condition=Ready "pod/$pod" --timeout=90s >/dev/null || { K -n "$LABMONITOR_NS" delete pod "$pod" --wait=false >/dev/null 2>&1 || true; return 1; }
  local code
  code="$(K -n "$LABMONITOR_NS" exec "$pod" -- sh -c 'curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 20 -u "$PROBE_JENKINS_USER:$PROBE_JENKINS_TOKEN" "http://'"$SERVER_LAN_IP:$JENKINS_PORT"'/api/json"')" || { K -n "$LABMONITOR_NS" delete pod "$pod" --wait=false >/dev/null 2>&1 || true; return 1; }
  K -n "$LABMONITOR_NS" delete pod "$pod" --wait=false >/dev/null 2>&1 || true
  [[ "$code" == 2* ]] || { printf 'k3s Jenkins authenticated probe got HTTP %s\n' "$code" >&2; return 1; }
  log "k3s pod CIDR reached Jenkins ${SERVER_LAN_IP}:${JENKINS_PORT} with authentication (HTTP $code)"
}

# ---------------------------------------------------------------------------
# Section: Docker exporter /metrics carries container series, and the
# exporter Deployment mounts no socket (proxy-only input)
# ---------------------------------------------------------------------------
check_exporter_metrics() {
  require_cmd kubectl curl || return 1
  pf_start "$MONITORING_NS" docker-metrics-exporter 19797 9797 || return 1
  local metrics
  metrics="$(curl -fsS --connect-timeout 5 --max-time 20 http://127.0.0.1:19797/metrics)" || { pf_stop_all; return 1; }
  pf_stop_all
  local series
  for series in labmonitor_docker_container_info \
    labmonitor_docker_container_cpu_usage_seconds_total \
    labmonitor_docker_container_memory_usage_bytes; do
    printf '%s' "$metrics" | grep -q "^$series" || { printf 'exporter metrics missing %s\n' "$series" >&2; return 1; }
  done
}

check_exporter_has_no_socket() {
  require_cmd kubectl || return 1
  local rendered
  rendered="$(K -n "$MONITORING_NS" get deployment docker-metrics-exporter -o yaml)" || return 1
  case "$rendered" in
    *docker.sock*) printf 'exporter Deployment must not reference a socket file\n' >&2; return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Section: Jenkins REST contract (read ok, mutation/admin denied, anon denied)
# ---------------------------------------------------------------------------
jenkins_base() { printf 'http://%s:%s' "$SERVER_LAN_IP" "$JENKINS_PORT"; }

check_jenkins_rest_authenticated() {
  require_cmd curl python3 || return 1
  [[ -n "${JENKINS_LABMONITOR_API_TOKEN:-}" ]] || { printf 'set JENKINS_LABMONITOR_API_TOKEN\n' >&2; return 1; }
  local body
  body="$(curl -fsS --connect-timeout 5 --max-time 20 -u "${JENKINS_LABMONITOR_USER}:${JENKINS_LABMONITOR_API_TOKEN}" "$(jenkins_base)/api/json?tree=jobs[name,builds[number]]")" || return 1
  printf '%s' "$body" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d.get("jobs", None), list); print("jenkins jobs=%d" % len(d["jobs"]))' || return 1
}

check_jenkins_mutation_denied() {
  require_cmd curl || return 1
  [[ -n "${JENKINS_LABMONITOR_API_TOKEN:-}" ]] || { printf 'set JENKINS_LABMONITOR_API_TOKEN\n' >&2; return 1; }
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 20 \
    -u "${JENKINS_LABMONITOR_USER}:${JENKINS_LABMONITOR_API_TOKEN}" -X POST "$(jenkins_base)/job/nonexistent/build")" || return 1
  case "$code" in 2*) printf 'Jenkins accepted build mutation (HTTP %s)\n' "$code" >&2; return 1 ;; esac
  code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 20 \
    -u "${JENKINS_LABMONITOR_USER}:${JENKINS_LABMONITOR_API_TOKEN}" "$(jenkins_base)/manage")" || return 1
  case "$code" in 2*) printf 'Jenkins granted admin page (HTTP %s)\n' "$code" >&2; return 1 ;; esac
}

check_jenkins_anonymous_denied() {
  require_cmd curl || return 1
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 20 "$(jenkins_base)/api/json")" || return 1
  case "$code" in 2*) printf 'Jenkins anonymous read got HTTP %s, must be non-2xx\n' "$code" >&2; return 1 ;; esac
}

# ---------------------------------------------------------------------------
# Section: Grafana Prometheus datasource serving technical dashboards
# ---------------------------------------------------------------------------
check_grafana_datasource() {
  require_cmd kubectl curl python3 || return 1
  local grafana_password="${GRAFANA_ADMIN_PASSWORD:-}"
  if [[ -z "$grafana_password" ]]; then
    grafana_password="$(K -n "$MONITORING_NS" get secret grafana-admin -o jsonpath='{.data.admin-password}' | python3 -c 'import base64,sys; print(base64.b64decode(sys.stdin.read().strip()).decode())')" || return 1
  fi
  [[ -n "$grafana_password" ]] || { printf 'Grafana admin credential unavailable\n' >&2; return 1; }
  for board in host docker kubernetes jenkins; do
    K -n "$MONITORING_NS" get configmap "grafana-dashboard-$board" -o name >/dev/null || return 1
  done
  pf_start "$MONITORING_NS" grafana 13000 3000 || return 1
  local sources
  sources="$(curl -fsS --connect-timeout 5 --max-time 20 -u "${GRAFANA_ADMIN_USER}:${grafana_password}" http://127.0.0.1:13000/api/datasources)" || { pf_stop_all; return 1; }
  pf_stop_all
  printf '%s' "$sources" | python3 -c '
import json, sys
sources = json.load(sys.stdin)
prom = [s for s in sources if s.get("type") == "prometheus"]
assert prom, "no prometheus datasource"
print("datasources=%d prometheus=%s" % (len(sources), prom[0].get("name")))
' || return 1
}

# ---------------------------------------------------------------------------
# Section: Portainer Server reaches Docker and Kubernetes Agents
# ---------------------------------------------------------------------------
check_portainer_agents() {
  require_cmd kubectl curl python3 || return 1
  pf_start "$PORTAINER_NS" portainer 19000 9000 || return 1
  local status
  status="$(curl -fsS --connect-timeout 5 --max-time 20 http://127.0.0.1:19000/api/status)" || { pf_stop_all; return 1; }
  pf_stop_all
  printf '%s' "$status" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("Version"); print("portainer version=%s" % d["Version"])' || return 1
  local agent_eps
  agent_eps="$(K -n "$PORTAINER_NS" get endpoints portainer-agent -o jsonpath='{.subsets[*].addresses[*].ip}')" || return 1
  [[ -n "$agent_eps" ]] || { printf 'Portainer Kubernetes Agent has no endpoints\n' >&2; return 1; }
  $SUDO docker inspect portainer-agent --format '{{json .State}}' 2>/dev/null | grep -q '"Running":true' \
    || { printf 'host Docker Agent container portainer-agent not Running\n' >&2; return 1; }
  # The Docker Agent answers the k3s pod network with an auth gate (any HTTP
  # code proves the path; 000/timeout would prove the firewall drops it).
  local agent_code
  agent_code="$(timeout 120 kubectl --kubeconfig="$KUBECONFIG" run "slice3-pa-$$-$(date +%s)" \
    --image="$PROBE_IMAGE" --restart=Never --rm -i --command -- \
    curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 20 "http://${SERVER_LAN_IP}:9001")" || return 1
  [[ -n "$agent_code" && "$agent_code" != "000" ]] || { printf 'k3s pods cannot reach Docker Agent 9001\n' >&2; return 1; }
  log "Docker Agent reachable from k3s (HTTP $agent_code auth gate)"
}

# ---------------------------------------------------------------------------
# Section: Kubernetes RBAC denial for the future reader identity
# ---------------------------------------------------------------------------
check_kubernetes_secret_denial() {
  require_cmd kubectl || return 1
  local sa="system:serviceaccount:${LABMONITOR_NS}:labmonitor-api"
  [[ "$(K auth can-i get secrets --as="$sa" --all-namespaces)" == "no" ]] || { printf 'reader identity must not read Secrets\n' >&2; return 1; }
  [[ "$(K auth can-i create pods --as="$sa" --all-namespaces)" == "no" ]] || { printf 'reader identity must not create pods\n' >&2; return 1; }
  [[ "$(K auth can-i get pods --as="$sa" --all-namespaces)" == "yes" ]] || { printf 'reader identity must read pods\n' >&2; return 1; }
}

# ---------------------------------------------------------------------------
# Section: discovery sources — Docker labels, Kubernetes Services,
# catalog and provider ConfigMaps normalize to seven applications
# ---------------------------------------------------------------------------
check_discovery_docker_labels() {
  require_cmd docker python3 || return 1
  local labels
  labels="$($SUDO docker inspect jenkins n8n metabase --format '{{json .Config.Labels}}')" || return 1
  [[ -n "$labels" ]] || { printf 'docker inspect returned no labels\n' >&2; return 1; }
  printf '%s' "$labels" | BASE_DOMAIN="$BASE_DOMAIN" python3 -c '
import json, os, sys
expected = {"jenkins", "n8n", "metabase"}
found, urls = set(), []
docs = json.load(sys.stdin)
if isinstance(docs, dict):
    docs = [docs]
for doc in docs:
    lab = doc.get("Config", {}).get("Labels", {}) if "Config" in doc else doc
    if "labmonitor.id" in lab:
        found.add(lab["labmonitor.id"])
        urls.append(lab.get("labmonitor.open.url", ""))
assert expected <= found, "docker labels missing: %s" % sorted(expected - found)
domain = os.environ["BASE_DOMAIN"]
for u in urls:
    assert u.endswith(domain), "docker URL %r must end with %s" % (u, domain)
print("docker discovery ids=%s" % sorted(found))
' || return 1
}

check_discovery_k8s_services() {
  require_cmd kubectl || return 1
  local spec ns svc sid surl
  for spec in "$MONITORING_NS/grafana" "$MONITORING_NS/prometheus" "$PORTAINER_NS/portainer"; do
    ns="${spec%%/*}" svc="${spec##*/}"
    sid="$(K -n "$ns" get service "$svc" -o jsonpath='{.metadata.labels.labmonitor\.id}')" || return 1
    surl="$(K -n "$ns" get service "$svc" -o jsonpath='{.metadata.annotations.labmonitor\.open\.url}')" || return 1
    [[ -n "$sid" ]] || { printf 'service %s/%s missing labmonitor.id\n' "$ns" "$svc" >&2; return 1; }
    [[ -n "$surl" ]] || { printf 'service %s/%s missing labmonitor.open.url\n' "$ns" "$svc" >&2; return 1; }
    case "$surl" in
      *"$BASE_DOMAIN") ;;
      *) printf 'service %s/%s URL %s must end with %s\n' "$ns" "$svc" "$surl" "$BASE_DOMAIN" >&2; return 1 ;;
    esac
  done
}

check_discovery_catalog_provider() {
  require_cmd kubectl python3 || return 1
  local catalog providers
  catalog="$(K -n "$LABMONITOR_NS" get configmap labmonitor-catalog -o jsonpath='{.data.catalog\.yaml}')" || return 1
  providers="$(K -n "$LABMONITOR_NS" get configmap labmonitor-provider-config -o jsonpath='{.data.providers\.yaml}')" || return 1
  [[ -n "$catalog" && -n "$providers" ]] || { printf 'catalog or provider ConfigMap empty\n' >&2; return 1; }
  printf '%s' "$catalog" | BASE_DOMAIN="$BASE_DOMAIN" python3 -c '
import os, sys
body = sys.stdin.read()
assert "id: cockpit" in body, "catalog must list cockpit"
assert body.count("- id:") == 1, "catalog must hold exactly the cockpit entry"
assert os.environ["BASE_DOMAIN"] in body, "catalog must use the environment domain"
' || return 1
  printf '%s' "$providers" | python3 -c '
import sys
body = sys.stdin.read()
for name in ("prometheus:", "docker:", "jenkins:", "kubernetes:"):
    assert name in body, "provider config missing %s" % name
assert "password" not in body.lower() and "token" not in body.lower(), "provider config must not carry credentials"
' || return 1
  # Seven navigable applications across all sources; providers and the
  # database carry no navigable URL.
  local count=0
  count=$((count + $($SUDO docker inspect jenkins n8n metabase --format '{{json .Config.Labels}}' 2>/dev/null | grep -o 'labmonitor.open.url' | wc -l))) || return 1
  count=$((count + $(K -n "$MONITORING_NS" get service grafana prometheus -o json 2>/dev/null | grep -o 'labmonitor.open.url' | wc -l))) || return 1
  count=$((count + $(K -n "$PORTAINER_NS" get service portainer -o json 2>/dev/null | grep -o 'labmonitor.open.url' | wc -l))) || return 1
  count=$((count + $(printf '%s' "$catalog" | grep -c 'open_url'))) || return 1
  [[ "$count" -eq 7 ]] || { printf 'discovery must normalize to 7 navigable entries, got %s\n' "$count" >&2; return 1; }
  if $SUDO docker inspect postgres --format '{{json .Config.Labels}}' 2>/dev/null | grep -q 'labmonitor.open.url'; then
    printf 'postgres must not carry a navigable URL\n' >&2; return 1
  fi
  # Environment isolation: the selected domain only.
  local other="home.arpa"
  [[ "$BASE_DOMAIN" == "home.arpa" ]] && other="lab.arpa"
  local all_urls
  all_urls="$( { $SUDO docker inspect jenkins n8n metabase --format '{{json .Config.Labels}}' 2>/dev/null; K -n "$MONITORING_NS" get service grafana prometheus -o json 2>/dev/null; K -n "$PORTAINER_NS" get service portainer -o json 2>/dev/null; printf '%s' "$catalog"; } )" || return 1
  case "$all_urls" in
    *"$other"*) printf 'environment leak: found %s while expecting %s\n' "$other" "$BASE_DOMAIN" >&2; return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Section: network boundary evidence (read-only; never weakens the firewall)
# ---------------------------------------------------------------------------
check_provider_ports_have_no_public_route() {
  require_cmd kubectl || return 1
  local nodeports
  nodeports="$(K get svc -A -o jsonpath='{range .items[*]}{range .spec.ports[*]}{.nodePort}{"\n"}{end}{end}' 2>/dev/null | sort -u | tr '\n' ' ')" || return 1
  case "$nodeports" in
    *12375*|*9797*|*9001*) printf 'provider port exposed as NodePort: %s\n' "$nodeports" >&2; return 1 ;;
  esac
  local ingress
  ingress="$(K get ingress -A -o jsonpath='{range .items[*]}{.spec.rules[*].host}{" "}{end}' 2>/dev/null || true)"
  case "$ingress" in
    *12375*|*9797*) printf 'provider port exposed via Ingress\n' >&2; return 1 ;;
  esac
  [[ "$nodeports" == *"30300"* && "$nodeports" == *"30909"* && "$nodeports" == *"30900"* ]] \
    || { printf 'human NodePorts 30300/30909/30900 incomplete: %s\n' "$nodeports" >&2; return 1; }
}

check_firewall_boundary_readonly() {
  # Read-only inspection: the 12375 allow stays scoped to the pod CIDR,
  # LAN/VPN never gain an allow, and the DOCKER-USER chain drops the rest.
  local ufw_out chain
  ufw_out="$($SUDO ufw status verbose 2>/dev/null || true)"
  [[ -n "$ufw_out" ]] || { printf 'ufw status unavailable\n' >&2; return 1; }
  printf '%s\n' "$ufw_out" | grep -q '12375' || { printf 'UFW shows no 12375 rule at all\n' >&2; return 1; }
  if printf '%s\n' "$ufw_out" | grep '12375' | grep -q 'ALLOW.*Anywhere'; then
    printf 'UFW grants 12375 to Anywhere; must stay pod-CIDR only\n' >&2; return 1
  fi
  chain="$($SUDO iptables -S HOME_SERVER_DOCKER 2>/dev/null || $SUDO iptables -S DOCKER-USER 2>/dev/null || true)"
  [[ -n "$chain" ]] || { printf 'DOCKER-USER chain unreadable\n' >&2; return 1; }
  printf '%s\n' "$chain" | grep -q '12375.*DROP' || { printf 'no DROP rule for 12375 in DOCKER-USER policy\n' >&2; return 1; }
  printf '%s\n' "$chain" | grep -q '9001.*DROP' || { printf 'no DROP rule for 9001 in DOCKER-USER policy\n' >&2; return 1; }
  log "LAN/VPN to ${SERVER_LAN_IP}:${DOCKER_PROXY_PORT} is denied by default-drop plus DOCKER-USER DROP (manual client proof still required, see header)"
}

main() {
  [[ -n "${SERVER_LAN_IP:-}" ]] || { printf 'set SERVER_LAN_IP to the server LAN address\n' >&2; exit 2; }
  require_cmd kubectl curl python3 docker timeout || exit 2

  run_check "kubeconfig (Kubernetes API reachable)" check_kubeconfig
  run_check "monitoring pods Ready (Prometheus stack)" check_monitoring_pods_ready
  run_check "Portainer Server and Agent Ready" check_portainer_pods_ready
  run_check "labmonitor namespace/ServiceAccount/ConfigMaps/Secrets" check_labmonitor_foundation
  run_check "no LabMonitor API Deployment" check_no_labmonitor_api_deployment
  run_check "Prometheus and Grafana PVCs Bound" check_pvcs_bound
  run_check "Prometheus retention ${PROMETHEUS_RETENTION_EXPECTED}" check_prometheus_retention
  run_check "Prometheus targets UP (node-exporter/kubelet/cAdvisor/ksm/Docker/Jenkins)" check_prometheus_targets_up
  run_check "Docker proxy GET reads from authorized k3s pod" check_proxy_get_from_k3s
  run_check "Docker proxy mutating requests rejected" check_proxy_mutating_denied
  run_check "k3s pod CIDR Jenkins authenticated success" check_jenkins_from_k3s_authenticated
  run_check "Docker exporter /metrics container series" check_exporter_metrics
  run_check "exporter Deployment mounts no socket" check_exporter_has_no_socket
  run_check "Jenkins authenticated REST valid JSON" check_jenkins_rest_authenticated
  run_check "Jenkins build mutation and admin denied" check_jenkins_mutation_denied
  run_check "Jenkins anonymous access denied" check_jenkins_anonymous_denied
  run_check "Grafana Prometheus datasource" check_grafana_datasource
  run_check "Portainer reaches Docker and Kubernetes Agents" check_portainer_agents
  run_check "Kubernetes Secret denial for reader identity" check_kubernetes_secret_denial
  run_check "discovery: Docker labels carry environment URLs" check_discovery_docker_labels
  run_check "discovery: Kubernetes Services carry environment URLs" check_discovery_k8s_services
  run_check "discovery: catalog/provider normalize to seven apps" check_discovery_catalog_provider
  run_check "provider ports have no NodePort or Ingress" check_provider_ports_have_no_public_route
  run_check "firewall boundary read-only (LAN and Internet denied 12375)" check_firewall_boundary_readonly

  pf_stop_all
  printf '\n[slice3] result: %d passed, %d failed (%s, base domain %s)\n' "$PASS" "$FAIL" "$ENVIRONMENT_NAME" "$BASE_DOMAIN"
  if [[ "$FAIL" -gt 0 ]]; then
    printf '[slice3] failed checks: %s\n' "${FAILED_CHECKS[*]}" >&2
    return 1
  fi
}

main "$@"
