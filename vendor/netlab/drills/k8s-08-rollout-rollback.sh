DRILL_TITLE="A bad deploy is stuck mid-rollout -- roll it back"
DRILL_MODULE="k8s"
DRILL_LEVEL=3
DRILL_TIME="20 min"
DRILL_TOOLS="kubectl rollout status/history/undo, get rs"
DRILL_BRIEF="Someone pushed a new image tag to the 'api' Deployment ten minutes
ago. The rollout never finished. The old pods are still serving traffic (good),
but a new pod is stuck failing to start and the deploy is frozen. Your job is
to get back to a known-good state fast, the way you would during an incident."
DRILL_GOAL="Return 'api' to 2 ready replicas running the previous, working
nginx:1.27-alpine image."

drill_reset() { k8s_clean_workloads; }

drill_break() {
  k8s_clean_workloads
  kube apply -f "$K8S_MANIFESTS/08-api.yaml" >/dev/null 2>&1
  kn rollout status deployment/api --timeout=150s >/dev/null 2>&1
  # The bad deploy: a tag that does not exist anywhere.
  kn set image deployment/api web=nginx:9.99-doesnotexist >/dev/null 2>&1
  sleep 6
}

drill_verify() {
  k_image_is api "1.27-alpine" || { warn "The api Deployment is not on nginx:1.27-alpine."; return 1; }
  k_deploy_ready api 2 || return 1
  k_svc_has_endpoints api
}

drill_hint() { cat <<'H'
First, confirm the situation rather than guessing:
  kubectl -n netlab rollout status deployment/api --timeout=10s
  kubectl -n netlab get deploy api
  kubectl -n netlab get rs -l app=api
  kubectl -n netlab get pods -l app=api

Notice there are TWO ReplicaSets: the old one still running your good pods,
and a new one whose pod cannot start. That is the Deployment protecting you
-- maxUnavailable: 0 means it will not retire working pods until the new
ones are Ready.

Kubernetes keeps the history for exactly this moment:
  kubectl -n netlab rollout history deployment/api
  kubectl -n netlab rollout history deployment/api --revision=1

During a real incident you roll back first and investigate afterwards.
H
}

drill_solution() { cat <<'S'
Diagnose:
  kubectl -n netlab get deploy api
    NAME  READY  UP-TO-DATE  AVAILABLE  AGE
    api   2/2    1           2          3m       <-- UP-TO-DATE stuck at 1

  kubectl -n netlab get rs -l app=api
    api-6c4f8...   2   2   2   3m     <-- old ReplicaSet, healthy
    api-7d9a1...   1   1   0   1m     <-- new ReplicaSet, 0 available

  kubectl -n netlab get pods -l app=api
    api-7d9a1...-qq2  0/1  ImagePullBackOff  0  1m

  kubectl -n netlab describe pod -l app=api | tail -6
    Failed to pull image "nginx:9.99-doesnotexist": not found

Fix -- roll back to the previous revision:
  kubectl -n netlab rollout history deployment/api
    REVISION  CHANGE-CAUSE
    1         <none>
    2         <none>

  kubectl -n netlab rollout undo deployment/api
  kubectl -n netlab rollout status deployment/api

  To a specific revision instead of just "the last one":
  kubectl -n netlab rollout undo deployment/api --to-revision=1

Confirm:
  kubectl -n netlab get deploy api
    api   2/2   2   2
  kubectl -n netlab get deploy api \
    -o jsonpath='{.spec.template.spec.containers[0].image}'
    nginx:1.27-alpine
  kubectl -n netlab exec toolbox -- wget -qO- http://api | head -3

Other rollout controls worth practising right now:
  kubectl -n netlab rollout pause deployment/api      # stop mid-rollout
  kubectl -n netlab rollout resume deployment/api
  kubectl -n netlab rollout restart deployment/api    # recreate all pods
                                                      # (picks up new config)
  kubectl -n netlab set image deployment/api web=nginx:1.27-alpine
  kubectl -n netlab annotate deployment/api \
    kubernetes.io/change-cause="pin nginx 1.27-alpine" --overwrite
    (the annotation is what fills in CHANGE-CAUSE in rollout history --
     set it on every deploy and your history becomes readable)
S
}

drill_debrief() { cat <<'D'
Why a Deployment keeps old ReplicaSets around: each revision IS a
ReplicaSet. "rollout undo" simply scales the previous one back up and the
new one down. revisionHistoryLimit (default 10) controls how many are kept,
and setting it to 0 means you cannot roll back at all.

The rollout strategy fields decide how safe a bad deploy is:
  maxUnavailable: 0   never take capacity away. A broken new version stalls
                      the rollout instead of causing an outage. This is the
                      setting that saved you here.
  maxSurge: 1         allow one extra pod above the replica count while
                      rolling.
  strategy: Recreate  kill everything, then start the new version. Causes
                      real downtime; only correct when two versions cannot
                      run at once (some schema migrations, singletons).

Incident habit worth building: roll back first, investigate second. The
history is right there, the rollback takes seconds, and a stalled rollout
holds your capacity hostage while you debug. Capture what you need
(kubectl describe, logs --previous) and then undo.

Also note: a rollout only happens when the POD TEMPLATE changes. Editing
replicas is a scale, not a rollout. Editing a ConfigMap the pods read does
not trigger anything at all, which is precisely why
"kubectl rollout restart" exists.
D
}
