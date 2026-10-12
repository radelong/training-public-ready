DRILL_TITLE="NetworkPolicy is blocking legitimate traffic"
DRILL_MODULE="k8s"
DRILL_LEVEL=4
DRILL_TIME="25 min"
DRILL_TOOLS="kubectl get netpol, describe netpol, exec wget"
DRILL_BRIEF="The 'secure' Deployment is healthy: 2/2 Ready, and its Service has
endpoints. DNS resolves. Yet the toolbox pod cannot reach http://secure at all
-- the connection just hangs. A security change went in yesterday."
DRILL_GOAL="Let the toolbox pod (label role=toolbox) reach the 'secure' pods on
port 80, while KEEPING the default-deny policy in place. Deleting the
default-deny is not the answer -- add a targeted allow."

drill_reset() { k8s_clean_workloads; }

drill_break() {
  k8s_clean_workloads
  kn delete netpol --all --ignore-not-found >/dev/null 2>&1
  kube apply -f "$K8S_MANIFESTS/09-secure.yaml" >/dev/null 2>&1
  kn rollout status deployment/secure --timeout=150s >/dev/null 2>&1
  sleep 3
  if k_curl "http://secure"; then
    warn "This cluster does not appear to enforce NetworkPolicy."
    warn "k3s enforces it by default; a cluster started with"
    warn "--disable-network-policy, or a CNI without policy support, does not."
    warn "You can still practise the YAML, but the check will pass trivially."
  fi
}

drill_verify() {
  kn get netpol secure-default-deny >/dev/null 2>&1 || {
    warn "The 'secure-default-deny' policy must stay in place -- add an allow instead."
    return 1
  }
  k_wait 25 k_curl "http://secure"
}

drill_hint() { cat <<'H'
Rule out everything except policy first, because the symptoms overlap:
  kubectl -n netlab get pods -l app=secure          # 2/2 Ready?
  kubectl -n netlab get endpointslices -l kubernetes.io/service-name=secure
  kubectl -n netlab exec toolbox -- nslookup secure  # DNS fine?
  kubectl -n netlab exec toolbox -- wget -qO- -T3 http://secure   # hangs

Endpoints exist and DNS works, so the packet is being dropped in the
network. Look for policy:
  kubectl -n netlab get netpol
  kubectl -n netlab describe netpol secure-default-deny

Read the semantics carefully. In Kubernetes, NetworkPolicy is additive
allow-listing:
  - A pod with NO policy selecting it accepts everything.
  - As soon as ANY policy selects a pod for Ingress, that pod denies all
    ingress except what some policy explicitly allows.
  - Multiple policies are OR-ed together. So you never edit a deny -- you
    add another policy that allows what you need.

Write a second policy that selects app=secure and allows from
podSelector role=toolbox on TCP 80.
H
}

drill_solution() { cat <<'S'
Diagnose:
  kubectl -n netlab get netpol
    NAME                  POD-SELECTOR  AGE
    secure-default-deny   app=secure    5m

  kubectl -n netlab describe netpol secure-default-deny
    Allowing ingress traffic:
      <none> (Selected pods are isolated for ingress connectivity)

  An empty ingress list plus policyTypes: [Ingress] is the canonical
  default-deny. Nothing can reach these pods until another policy allows it.

Fix -- add a narrow allow policy:
  kubectl apply -f /opt/netlab/k8s/manifests/solutions/09-allow-toolbox.yaml

  Or write it yourself:
  cat <<'EOF' | kubectl apply -f -
  apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: secure-allow-toolbox
    namespace: netlab
  spec:
    podSelector:
      matchLabels: { app: secure }
    policyTypes: ["Ingress"]
    ingress:
      - from:
          - podSelector:
              matchLabels: { role: toolbox }
        ports:
          - protocol: TCP
            port: 80
  EOF

Confirm:
  kubectl -n netlab get netpol
  kubectl -n netlab exec toolbox -- wget -qO- -T3 http://secure | head -3

  And prove the deny still works for everything else:
  kubectl -n netlab run probe --rm -it --restart=Never --image=busybox:1.36 \
    -- wget -qO- -T3 http://secure
    (this pod has no role=toolbox label, so it should time out)

The four selector forms in a "from" block, and the trap:
  podSelector:       pods in the SAME namespace matching these labels
  namespaceSelector: all pods in namespaces matching these labels
  podSelector AND namespaceSelector in ONE list item: the intersection
    ("pods labelled X in namespaces labelled Y")
  two SEPARATE list items: the union ("either of these")
  ipBlock:           CIDR, for traffic from outside the cluster

That AND/OR distinction is a single YAML dash, and it is the most common
NetworkPolicy mistake there is.
S
}

drill_debrief() { cat <<'D'
NetworkPolicy semantics, condensed:

  - Policies are ALLOW rules only. There is no deny rule.
  - A pod is "isolated" for a direction the moment any policy selects it for
    that direction. Before that, everything is permitted.
  - Isolated pods accept only the union of what all selecting policies
    allow.
  - Ingress and Egress are isolated independently.
  - The policy applies to the POD, not to the Service. Traffic sent to a
    ClusterIP is DNAT-ed to a pod IP before the policy is evaluated, so you
    write rules about pods and ports, never about Service names.

The standard production pattern is exactly what you just built: one
default-deny per namespace, then narrow allows per dependency.

  # deny all ingress in the namespace
  spec:
    podSelector: {}          # empty = every pod in the namespace
    policyTypes: ["Ingress"]

If you also enable default-deny EGRESS, remember to allow DNS or nothing in
the namespace will resolve anything:

  egress:
    - to:
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: kube-system }
          podSelector:
            matchLabels: { k8s-app: kube-dns }
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }

Forgetting that DNS rule is the classic self-inflicted cluster outage.

Finally, enforcement is the CNI plugin's job, not the API server's. You can
apply a perfectly valid NetworkPolicy to a cluster with a CNI that ignores
it, and get no error and no enforcement. Always verify with an actual
connection test, exactly as you did here.
D
}
