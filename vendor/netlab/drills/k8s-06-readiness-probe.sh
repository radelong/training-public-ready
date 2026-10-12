DRILL_TITLE="Pods Running but never Ready (bad readiness probe)"
DRILL_MODULE="k8s"
DRILL_LEVEL=3
DRILL_TIME="15 min"
DRILL_TOOLS="kubectl describe pod, probes, port-forward"
DRILL_BRIEF="The 'probeapp' pods show STATUS Running but READY 0/2. The
Deployment never reports itself available, the rollout hangs, and the Service
has no endpoints. The container itself is not restarting."
DRILL_GOAL="Get 'probeapp' to 2 ready replicas with a working readiness probe,
and http://probeapp reachable from the toolbox pod. Keep a readiness probe --
do not just delete it."

drill_reset() { k8s_clean_workloads; }

drill_break() {
  k8s_clean_workloads
  kube apply -f "$K8S_MANIFESTS/06-readiness.yaml" >/dev/null 2>&1
}

drill_verify() {
  kn get deploy probeapp -o jsonpath='{.spec.template.spec.containers[0].readinessProbe}' 2>/dev/null \
    | grep -q . || { warn "Keep a readiness probe -- fix it rather than removing it."; return 1; }
  k_deploy_ready probeapp 2 || return 1
  k_svc_has_endpoints probeapp || return 1
  k_wait 20 k_curl "http://probeapp"
}

drill_hint() { cat <<'H'
Running means the container process is alive. Ready means the readiness
probe is passing. They are independent, and an unready pod is deliberately
removed from its Service endpoints.

  kubectl -n netlab get pods -l app=probeapp
  kubectl -n netlab describe pod -l app=probeapp | tail -15

Look for a "Readiness probe failed" warning in the Events. Note the URL and
port it reports, then check what the container really serves:

  kubectl -n netlab get deploy probeapp \
    -o jsonpath='{.spec.template.spec.containers[0].readinessProbe}'
  kubectl -n netlab exec deploy/probeapp -- wget -qO- -T2 http://127.0.0.1/
  kubectl -n netlab exec deploy/probeapp -- wget -qO- -T2 http://127.0.0.1:8080/

Does nginx listen on 8080? Does it serve /healthz?
H
}

drill_solution() { cat <<'S'
Diagnose:
  kubectl -n netlab get pods -l app=probeapp
    NAME             READY  STATUS   RESTARTS  AGE
    probeapp-...     0/1    Running  0         2m       <-- running, not ready
    probeapp-...     0/1    Running  0         2m

  kubectl -n netlab describe pod -l app=probeapp | tail -8
    Warning  Unhealthy  ...  Readiness probe failed: Get
             "http://10.42.0.19:8080/healthz": dial tcp ...: connect:
             connection refused

  kubectl -n netlab get deploy probeapp \
    -o jsonpath='{.spec.template.spec.containers[0].readinessProbe}'
    {"httpGet":{"path":"/healthz","port":8080},...}

  Prove what the container actually serves:
  kubectl -n netlab exec deploy/probeapp -- wget -qO- -T2 http://127.0.0.1/
    <!DOCTYPE html> ...          <-- port 80, path / works
  kubectl -n netlab exec deploy/probeapp -- wget -qO- -T2 http://127.0.0.1:8080/
    wget: can't connect ...      <-- nothing on 8080

Fix -- point the probe at a port and path that exist:
  kubectl -n netlab patch deployment probeapp --type=json -p='[
    {"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/port","value":80},
    {"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/path","value":"/"}]'

  Or:  kubectl apply -f /opt/netlab/k8s/manifests/solutions/06-readiness-fixed.yaml

Confirm:
  kubectl -n netlab rollout status deployment/probeapp
  kubectl -n netlab get pods -l app=probeapp          # 1/1 Ready
  kubectl -n netlab get endpointslices -l kubernetes.io/service-name=probeapp
  kubectl -n netlab exec toolbox -- wget -qO- http://probeapp | head -3

Debug a probe by hand from your workstation:
  kubectl -n netlab port-forward deploy/probeapp 8081:80
  curl -v http://127.0.0.1:8081/
S
}

drill_debrief() { cat <<'D'
Three probes, three jobs. Confusing them causes outages.

  readinessProbe  "can I take traffic right now?"
                  Failing = removed from Service endpoints. NOT restarted.
                  This is the one that makes zero-downtime rollouts work.

  livenessProbe   "am I wedged and unrecoverable?"
                  Failing = the container is KILLED and restarted.
                  Dangerous when misconfigured: a too-aggressive liveness
                  probe on a slow-starting or briefly-overloaded app creates
                  a self-inflicted restart loop that looks like a crash bug.

  startupProbe    "have I finished booting?"
                  While it is failing, the other two are suspended. This is
                  the correct answer for slow-starting apps (JVMs, big
                  migrations), instead of inflating the liveness threshold.

Rules of thumb that prevent most probe incidents:
  - Every probe endpoint must be cheap and must not depend on downstream
    services. A /health that checks the database turns one database blip
    into every pod being marked unready simultaneously.
  - Set readiness aggressively, liveness conservatively.
  - If you are unsure, ship readiness only. A missing liveness probe costs
    you a manual restart; a bad one costs you an outage.
  - Give slow starters a startupProbe with a generous failureThreshold
    rather than a long initialDelaySeconds.

The stall you saw here is also why a rollout can hang forever: with
maxUnavailable: 0, Kubernetes will not retire old pods until new ones report
Ready, so a broken readiness probe safely freezes the deploy rather than
taking the service down. That is the system protecting you.
D
}
