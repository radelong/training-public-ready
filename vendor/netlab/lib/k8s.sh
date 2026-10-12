#!/usr/bin/env bash
# netlab :: lib/k8s.sh -- single-node Kubernetes (k3s) for the k8s-* drills

K8S_MANIFESTS="${NETLAB_ROOT}/k8s/manifests"

# k3s installs kubectl at /usr/local/bin/kubectl and its kubeconfig here.
K3S_KUBECONFIG="/etc/rancher/k3s/k3s.yaml"

kube() {
  if [ -r "$K3S_KUBECONFIG" ] && [ -z "${KUBECONFIG:-}" ]; then
    KUBECONFIG="$K3S_KUBECONFIG" kubectl "$@"
  else
    kubectl "$@"
  fi
}

# kn -- kubectl scoped to the practice namespace
kn() { kube -n "$K8S_NS" "$@"; }

k8s_available() {
  have kubectl || return 1
  kube version --request-timeout=5s >/dev/null 2>&1 || return 1
  kube get nodes >/dev/null 2>&1
}

k8s_flavor() {
  if systemctl is-active --quiet k3s 2>/dev/null; then echo "k3s"
  elif have kind && kind get clusters 2>/dev/null | grep -q netlab; then echo "kind"
  else echo "external"; fi
}

k8s_require() {
  k8s_available || die "No reachable Kubernetes cluster. Install one with:  sudo netlab k8s up"
  kube get ns "$K8S_NS" >/dev/null 2>&1 || k8s_seed
}

# ------------------------------------------------------------------ install --
k8s_install() {
  need_root "k8s up"
  if k8s_available; then
    ok "Cluster already reachable ($(k8s_flavor))."
  else
    info "Installing k3s (lightweight single-node Kubernetes)..."
    have curl || die "curl is required. Run: sudo apt-get install -y curl"
    if ! curl -sfL https://get.k3s.io | \
         INSTALL_K3S_EXEC="--write-kubeconfig-mode 644 --disable traefik" sh -; then
      die "k3s install failed. Check internet access and DNS, then retry."
    fi
    info "Waiting for the node to become Ready (up to 3 minutes)..."
    local i
    for i in $(seq 1 90); do
      kube get nodes 2>/dev/null | awk 'NR==2 && $2=="Ready"{found=1} END{exit !found}' && break
      sleep 2
    done
  fi

  k8s_user_kubeconfig
  k8s_seed
  ok "Kubernetes lab ready."
  printf '\n  Try:  %skubectl get nodes%s\n' "$C_GREEN" "$C_RESET"
  printf '        %skubectl -n %s get all%s\n' "$C_GREEN" "$K8S_NS" "$C_RESET"
  printf '        %ssudo netlab start k8s-01-first-deployment%s\n\n' "$C_GREEN" "$C_RESET"
}

# Give the human who ran sudo a working ~/.kube/config
k8s_user_kubeconfig() {
  local u="${SUDO_USER:-}" home
  [ -z "$u" ] && return 0
  home="$(getent passwd "$u" | cut -d: -f6)"
  [ -d "$home" ] || return 0
  [ -r "$K3S_KUBECONFIG" ] || return 0
  mkdir -p "$home/.kube"
  cp "$K3S_KUBECONFIG" "$home/.kube/config"
  chown -R "$u":"$u" "$home/.kube"
  chmod 600 "$home/.kube/config"
  info "Wrote $home/.kube/config for user $u (kubectl works without sudo)."
}

# --------------------------------------------------------------------- seed --
k8s_seed() {
  info "Seeding the '$K8S_NS' namespace..."
  kube create namespace "$K8S_NS" >/dev/null 2>&1 || true
  kube apply -f "$K8S_MANIFESTS/00-toolbox.yaml" >/dev/null 2>&1 || true
  info "Waiting for the toolbox pod (used by the drill checks)..."
  kn wait --for=condition=Ready pod/toolbox --timeout=150s >/dev/null 2>&1 \
    || warn "toolbox pod not ready yet -- image pull may still be running."
}

k8s_reset_ns() {
  need_root "k8s reset"
  k8s_available || die "No cluster."
  info "Deleting namespace $K8S_NS ..."
  kube delete namespace "$K8S_NS" --wait=true >/dev/null 2>&1 || true
  k8s_seed
  ok "Namespace $K8S_NS re-seeded."
}

# Remove everything the drills created but keep the toolbox pod and the
# namespace itself. Deliberately does NOT do "delete cm --all", which would
# take out the auto-managed kube-root-ca.crt ConfigMap.
k8s_clean_workloads() {
  kn delete deploy --all --ignore-not-found --wait=false >/dev/null 2>&1 || true
  kn delete svc --all --ignore-not-found --wait=false >/dev/null 2>&1 || true
  kn delete netpol --all --ignore-not-found --wait=false >/dev/null 2>&1 || true
  kn delete configmap app-config --ignore-not-found >/dev/null 2>&1 || true
  kn delete secret app-secret --ignore-not-found >/dev/null 2>&1 || true
  # every pod except the toolbox
  kn delete pods --field-selector=metadata.name!=toolbox \
     --ignore-not-found --wait=false >/dev/null 2>&1 || true
  # make sure the toolbox is present and ready before any check runs
  kube apply -f "$K8S_MANIFESTS/00-toolbox.yaml" >/dev/null 2>&1 || true
  kn wait --for=condition=Ready pod/toolbox --timeout=120s >/dev/null 2>&1 || true
}

k8s_uninstall() {
  need_root "k8s down"
  if [ -x /usr/local/bin/k3s-uninstall.sh ]; then
    warn "This removes k3s and every workload on it."
    /usr/local/bin/k3s-uninstall.sh
    ok "k3s removed."
  else
    die "k3s uninstall script not found. Nothing done."
  fi
}

# ------------------------------------------------------------------ status --
k8s_status() {
  k8s_available || die "No reachable cluster. sudo netlab k8s up"
  title "Kubernetes ($(k8s_flavor))"
  kube get nodes -o wide 2>/dev/null | sed 's/^/  /'
  printf '\n  Namespace %s:\n' "$K8S_NS"
  kn get all 2>/dev/null | sed 's/^/  /'
  printf '\n  Recent events:\n'
  kn get events --sort-by=.lastTimestamp 2>/dev/null | tail -12 | sed 's/^/  /'
  printf '\n'
}

k8s_show_iptables() {
  need_root "k8s iptables"
  title "What kube-proxy wrote into iptables"
  printf '\n  %sService entry points (nat/KUBE-SERVICES)%s\n\n' "$C_BOLD" "$C_RESET"
  iptables -t nat -L KUBE-SERVICES -n --line-numbers 2>/dev/null | head -30 | sed 's/^/    /'
  printf '\n  %sPer-service load-balancing chains (KUBE-SVC-*)%s\n\n' "$C_BOLD" "$C_RESET"
  iptables -t nat -S 2>/dev/null | grep -E 'KUBE-SVC-' | head -15 | sed 's/^/    /'
  printf '\n  %sPer-endpoint DNAT chains (KUBE-SEP-*)%s\n\n' "$C_BOLD" "$C_RESET"
  iptables -t nat -S 2>/dev/null | grep -E 'KUBE-SEP-.*DNAT' | head -15 | sed 's/^/    /'
  printf '\n  Read guides/10-k8s-networking-and-iptables.md for what this all means.\n\n'
}

# ------------------------------------------------- verification primitives --
# Used by drill_verify() in the k8s-* drills.

k_deploy_ready() { # k_deploy_ready <name> <min-ready-replicas>
  local n="$1" want="${2:-1}" got
  got="$(kn get deploy "$n" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)"
  [ -n "$got" ] && [ "$got" -ge "$want" ] 2>/dev/null
}

k_pods_running() { # k_pods_running <label-selector> <count>
  local sel="$1" want="${2:-1}" got
  got="$(kn get pods -l "$sel" --field-selector=status.phase=Running \
         -o name 2>/dev/null | wc -l)"
  [ "$got" -ge "$want" ] 2>/dev/null
}

k_svc_has_endpoints() { # k_svc_has_endpoints <svc>
  local s="$1" eps
  eps="$(kn get endpointslices -l "kubernetes.io/service-name=$s" \
         -o jsonpath='{.items[*].endpoints[*].addresses[*]}' 2>/dev/null)"
  [ -z "$eps" ] && eps="$(kn get endpoints "$s" \
         -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null)"
  [ -n "$eps" ]
}

k_curl() { # k_curl <url-from-inside-cluster>  -- returns 0 if it answered
  kn exec toolbox -- sh -c "wget -q -T 4 -O /dev/null '$1'" >/dev/null 2>&1
}

k_curl_blocked() { # inverse of k_curl, used by the NetworkPolicy drill
  ! k_curl "$1"
}

k_env_has() { # k_env_has <deploy> <ENV_NAME> <expected value substring>
  local d="$1" k="$2" v="$3" pod
  pod="$(kn get pods -l "app=$d" -o name 2>/dev/null | head -1)"
  [ -z "$pod" ] && return 1
  kn exec "${pod#pod/}" -- sh -c "printenv $k" 2>/dev/null | grep -q "$v"
}

k_file_has() { # k_file_has <deploy> <path> <substring>
  local d="$1" p="$2" v="$3" pod
  pod="$(kn get pods -l "app=$d" -o name 2>/dev/null | head -1)"
  [ -z "$pod" ] && return 1
  kn exec "${pod#pod/}" -- sh -c "cat $p" 2>/dev/null | grep -q "$v"
}

k_image_is() { # k_image_is <deploy> <substring>
  kn get deploy "$1" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null \
    | grep -q "$2"
}

k_wait() { # k_wait <seconds> <command...>  -- retry until true or timeout
  local secs="$1"; shift
  local i
  for i in $(seq 1 "$secs"); do
    "$@" && return 0
    sleep 1
  done
  return 1
}
