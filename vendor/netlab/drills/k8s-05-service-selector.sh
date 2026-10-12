DRILL_TITLE="Service has no endpoints (selector mismatch)"
DRILL_MODULE="k8s"
DRILL_LEVEL=2
DRILL_TIME="15 min"
DRILL_TOOLS="kubectl get endpointslices, describe svc, --show-labels"
DRILL_BRIEF="The 'shop' Deployment is healthy: 2/2 pods Running and Ready. The
'shop' Service exists and has a ClusterIP. But every request to http://shop
from inside the cluster hangs or is refused."
DRILL_GOAL="Make http://shop reachable from the toolbox pod. Do not delete the
Deployment -- fix the wiring."

drill_reset() { k8s_clean_workloads; }

drill_break() {
  k8s_clean_workloads
  kube apply -f "$K8S_MANIFESTS/05-service-selector.yaml" >/dev/null 2>&1
}

drill_verify() {
  k_deploy_ready shop 2 || return 1
  k_svc_has_endpoints shop || { warn "Service 'shop' still has no endpoints."; return 1; }
  k_wait 20 k_curl "http://shop"
}

drill_hint() { cat <<'H'
A Service is not connected to a Deployment. It finds pods purely by LABEL
SELECTOR. If the selector matches nothing, the Service exists, has an IP,
and forwards to an empty list.

The one command that answers this instantly:
  kubectl -n netlab get endpointslices -l kubernetes.io/service-name=shop

If the ENDPOINTS column is empty, either no pod matches the selector, or
matching pods are not Ready.

Compare the two sides:
  kubectl -n netlab get svc shop -o jsonpath='{.spec.selector}'
  kubectl -n netlab get pods --show-labels

  kubectl -n netlab describe svc shop      # shows Selector and Endpoints

Character by character. Really.
H
}

drill_solution() { cat <<'S'
Diagnose:
  kubectl -n netlab get pods -l app=shop
    shop-...-abc  1/1  Running  0  1m
    shop-...-def  1/1  Running  0  1m           <-- pods are perfectly healthy

  kubectl -n netlab describe svc shop
    Selector:    app=shopp
    Endpoints:   <none>                         <-- nothing behind the IP

  kubectl -n netlab get pods --show-labels
    shop-...-abc  1/1  Running  0  1m  app=shop,pod-template-hash=...
                                       ^^^^^^^^ one 'p', the selector has two

Fix -- correct the Service selector:
  kubectl -n netlab patch svc shop -p '{"spec":{"selector":{"app":"shop"}}}'

  Or declaratively:
  kubectl apply -f /opt/netlab/k8s/manifests/solutions/05-service-fixed.yaml

Confirm:
  kubectl -n netlab get endpointslices -l kubernetes.io/service-name=shop
    NAME        ADDRESSTYPE  PORTS  ENDPOINTS
    shop-x7k2q  IPv4         80     10.42.0.14,10.42.0.15
  kubectl -n netlab exec toolbox -- wget -qO- http://shop | head -3

The full checklist for "my Service returns nothing", in order:
  1. Do the pods exist and are they READY?    get pods
  2. Does the selector match their labels?    describe svc / --show-labels
  3. Is targetPort the port the container actually listens on?
     (port = the Service port; targetPort = the container port. Mixing them
      up gives you endpoints that exist and still refuse connections.)
  4. Is a NetworkPolicy blocking it?          get netpol
  5. Is DNS resolving?  kubectl exec toolbox -- nslookup shop
S
}

drill_debrief() { cat <<'D'
Labels and selectors are the only glue in Kubernetes. Nothing references
anything else by name: Services find Pods by label, ReplicaSets own Pods by
label, NetworkPolicies select Pods by label. A typo in a label is a silent,
total disconnection -- no error, no event, just nothing happening.

"Does the Service have endpoints?" is the single highest-value question in
Kubernetes networking, because it cleanly splits the problem in half:

  No endpoints  -> the problem is BEFORE the network: selector, labels, or
                   pods that are not Ready. Stop looking at DNS and CNI.
  Has endpoints -> the problem is AFTER: DNS, NetworkPolicy, the port
                   numbers, or the application itself.

Two related traps:
  - An unready pod is deliberately removed from the endpoint list. So "0
    endpoints" can also mean "the readiness probe is failing" -- that is the
    next drill.
  - port vs targetPort. port is what clients connect to on the Service;
    targetPort is the container's own port. Using a named port
    (targetPort: http, with ports: [{name: http, containerPort: 80}]) makes
    this self-documenting and survives a container port change.
D
}
