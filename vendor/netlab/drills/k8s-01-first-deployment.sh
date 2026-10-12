DRILL_TITLE="Build your first Deployment and Service"
DRILL_MODULE="k8s"
DRILL_LEVEL=1
DRILL_TIME="20 min"
DRILL_TOOLS="kubectl create/apply/get/describe/scale"
DRILL_BRIEF="Nothing is broken. This is the build exercise: you are going to
create a Deployment and put a Service in front of it, by hand, and watch what
Kubernetes does with each object."
DRILL_GOAL="In the 'netlab' namespace, create:
  - a Deployment named 'web' running image nginx:1.27-alpine, 3 replicas,
    with pod label app=web
  - a ClusterIP Service named 'web' on port 80 targeting the pods
Success = 3 ready replicas, the Service has endpoints, and the toolbox pod
can fetch http://web from inside the cluster."

# Nothing to break -- the reset in "netlab start" already gives you an empty
# namespace, which is the starting point for this build exercise.
drill_reset() { k8s_clean_workloads; }
drill_break()  { :; }

drill_verify() {
  k_deploy_ready web 3 || { warn "Deployment 'web' does not have 3 ready replicas yet."; return 1; }
  k_svc_has_endpoints web || { warn "Service 'web' has no endpoints (selector mismatch?)."; return 1; }
  k_wait 20 k_curl "http://web"
}

drill_hint() { cat <<'H'
Two ways to do this. Do it the imperative way first because it is fast, then
look at the YAML it generated -- that is how you learn the schema.

  kubectl -n netlab create deployment web --image=nginx:1.27-alpine --replicas=3
  kubectl -n netlab expose deployment web --port=80 --target-port=80

Watch what happens:
  kubectl -n netlab get deploy,rs,pods -o wide
  kubectl -n netlab get svc web
  kubectl -n netlab get endpointslices

Note the ownership chain: Deployment -> ReplicaSet -> Pods. You never create
pods directly.

Test from inside the cluster (a ClusterIP is only reachable from inside):
  kubectl -n netlab exec toolbox -- wget -qO- http://web

To see the YAML the imperative command produced, and learn to write it:
  kubectl -n netlab get deploy web -o yaml | head -40
  kubectl create deployment web --image=nginx:1.27-alpine --dry-run=client -o yaml
H
}

drill_solution() { cat <<'S'
Imperative (fast, good for exams and quick fixes):
  kubectl -n netlab create deployment web --image=nginx:1.27-alpine --replicas=3
  kubectl -n netlab expose deployment web --port=80 --target-port=80 --name=web

Declarative (what you actually keep in git):
  kubectl apply -f /opt/netlab/k8s/manifests/solutions/01-web.yaml

Inspect every layer:
  kubectl -n netlab get deploy web
    NAME   READY   UP-TO-DATE   AVAILABLE   AGE
    web    3/3     3            3           30s

  kubectl -n netlab get rs                  # the ReplicaSet the Deployment made
  kubectl -n netlab get pods -o wide        # the pods the ReplicaSet made
  kubectl -n netlab get svc web             # the stable virtual IP
  kubectl -n netlab get endpointslices -l kubernetes.io/service-name=web
                                            # the pod IPs behind that virtual IP
  kubectl -n netlab describe svc web

Reach it:
  kubectl -n netlab exec toolbox -- wget -qO- http://web
  kubectl -n netlab exec toolbox -- wget -qO- http://web.netlab.svc.cluster.local

Now play with it:
  kubectl -n netlab scale deployment web --replicas=5
  kubectl -n netlab get pods -w                 # ctrl-c to stop watching
  kubectl -n netlab delete pod <one-pod-name>   # watch it be replaced
  kubectl -n netlab scale deployment web --replicas=3

Clean up when you want:
  kubectl -n netlab delete deploy web
  kubectl -n netlab delete svc web
S
}

drill_debrief() { cat <<'D'
The object chain, and why each layer exists:

  Deployment   declares the desired state and manages rollouts. You edit
               this one.
  ReplicaSet   owned by the Deployment. Keeps N pods alive. A new one is
               created for each rollout, which is how rollback works.
  Pod          one or more containers sharing a network namespace and an IP.
               Cattle, not pets -- it is replaced, never repaired.
  Service      a stable virtual IP and DNS name in front of a changing set
               of pod IPs. It finds its pods purely by LABEL SELECTOR, not
               by name -- remember that, it is the cause of most "my service
               returns nothing" tickets.
  EndpointSlice the actual list of pod IPs behind a Service. Empty
               EndpointSlice = broken selector or unready pods.

Service types:
  ClusterIP    reachable only inside the cluster. The default.
  NodePort     also on every node at a high port (30000-32767).
  LoadBalancer asks the cloud/k3s for an external IP.

DNS inside the cluster follows a fixed pattern:
  <service>.<namespace>.svc.cluster.local
and within the same namespace the short name <service> just works.

Two flags to put in your muscle memory:
  -o yaml               see the whole object as the API server stores it
  --dry-run=client -o yaml   generate a manifest without creating anything.
                        This is the fastest way to write correct YAML.
D
}
