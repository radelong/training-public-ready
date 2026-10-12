DRILL_TITLE="Pod stuck in Pending -- unschedulable"
DRILL_MODULE="k8s"
DRILL_LEVEL=2
DRILL_TIME="15 min"
DRILL_TOOLS="kubectl describe, get events, describe node"
DRILL_BRIEF="The 'bigapp' Deployment was applied ten minutes ago. Its pod is
still Pending. It has never been assigned to a node, there are no container
logs, and describing the pod shows a FailedScheduling event."
DRILL_GOAL="Get 'bigapp' to 1 ready replica by making its resource requests
something this node can actually satisfy."

drill_reset() { k8s_clean_workloads; }

drill_break() {
  k8s_clean_workloads
  kube apply -f "$K8S_MANIFESTS/04-pending.yaml" >/dev/null 2>&1
}

drill_verify() {
  k_deploy_ready bigapp 1
}

drill_hint() { cat <<'H'
Pending means the scheduler could not find a node. The pod has not started,
so there is nothing to log -- the evidence is entirely in the events.

  kubectl -n netlab get pods -l app=bigapp -o wide     # NODE column is empty
  kubectl -n netlab describe pod -l app=bigapp | tail -12

Read the FailedScheduling message carefully; it names the exact predicate
that failed, for example "Insufficient memory" or "Insufficient cpu".

Now compare what the pod ASKS for against what the node HAS:
  kubectl -n netlab get deploy bigapp \
    -o jsonpath='{.spec.template.spec.containers[0].resources}'
  kubectl describe node | grep -A8 "Allocatable"
  kubectl describe node | grep -A8 "Allocated resources"

Requests are what the scheduler uses to place the pod. Limits are what the
kernel enforces at runtime. Only requests matter here.
H
}

drill_solution() { cat <<'S'
Diagnose:
  kubectl -n netlab get pods -l app=bigapp -o wide
    NAME          READY  STATUS   RESTARTS  AGE  IP   NODE
    bigapp-...    0/1    Pending  0         5m   <none>  <none>

  kubectl -n netlab describe pod -l app=bigapp | tail -8
    Events:
      Warning  FailedScheduling  ...  0/1 nodes are available:
               1 Insufficient memory, 1 Insufficient cpu.

  kubectl -n netlab get deploy bigapp \
    -o jsonpath='{.spec.template.spec.containers[0].resources}'
    {"requests":{"cpu":"8","memory":"900Gi"}}       <-- absurd

  kubectl describe node | grep -A6 Allocatable
    cpu:     4
    memory:  8000000Ki                              <-- about 7.6Gi

Fix -- request something the node can provide:
  kubectl -n netlab patch deployment bigapp --type=json -p='[
    {"op":"replace","path":"/spec/template/spec/containers/0/resources",
     "value":{"requests":{"cpu":"50m","memory":"64Mi"},
              "limits":{"cpu":"200m","memory":"128Mi"}}}]'

  Or:  kubectl -n netlab edit deployment bigapp

Confirm:
  kubectl -n netlab rollout status deployment/bigapp
  kubectl -n netlab get pods -l app=bigapp -o wide     # NODE is now populated

Units, because they cause real outages:
  cpu: "1"      one full core          cpu: "500m"  half a core
  memory: 128Mi  mebibytes (1024^2)    memory: 128M  megabytes (1000^2)
  Mi and M are NOT the same. Gi and G are not either.
S
}

drill_debrief() { cat <<'D'
Pending is a scheduling problem, and there are only a handful of causes.
The FailedScheduling event names which one:

  Insufficient cpu / memory     requests exceed what any node has free
  node(s) had untolerated taint the node is tainted (control-plane,
                                NoSchedule); the pod needs a toleration
  didn't match node selector    nodeSelector or nodeAffinity matches nothing
  didn't match pod affinity     affinity/anti-affinity cannot be satisfied
  had volume node affinity      a PersistentVolume is pinned to another node
  no nodes available            every node is cordoned or NotReady

Requests versus limits, the distinction that matters most:
  requests  what the SCHEDULER reserves. Too high and the pod never places;
            too low and the node gets oversubscribed and everything suffers.
  limits    what the KERNEL enforces (cgroups). Exceeding a memory limit
            gets the container OOMKilled with exit code 137. Exceeding a CPU
            limit just throttles it, which shows up as latency, not errors.

Note that the scheduler only counts REQUESTS against node capacity. A
cluster can be 100% "allocated" while sitting at 5% real utilisation, purely
because someone copied optimistic requests from an example manifest.
D
}
