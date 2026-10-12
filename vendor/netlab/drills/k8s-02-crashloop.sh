DRILL_TITLE="CrashLoopBackOff"
DRILL_MODULE="k8s"
DRILL_LEVEL=2
DRILL_TIME="15 min"
DRILL_TOOLS="kubectl describe, logs, logs --previous"
DRILL_BRIEF="A Deployment named 'crashy' was rolled out and the pod keeps
restarting. kubectl get pods shows CrashLoopBackOff and a restart count that
climbs every minute."
DRILL_GOAL="Get the 'crashy' Deployment to 1 ready replica that stays running.
The container must keep running rather than exiting."

drill_reset() { k8s_clean_workloads; }

drill_break() {
  k8s_clean_workloads
  kube apply -f "$K8S_MANIFESTS/02-crashloop.yaml" >/dev/null 2>&1
}

drill_verify() {
  k_deploy_ready crashy 1 || return 1
  local rs
  rs="$(kn get pods -l app=crashy -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null)"
  [ -n "$rs" ] || return 1
  sleep 5
  k_deploy_ready crashy 1
}

drill_hint() { cat <<'H'
CrashLoopBackOff means the container starts, exits, and Kubernetes restarts
it with an increasing delay. The pod is not broken -- the process inside it
is deciding to exit.

Find out why. The logs of the CURRENT container are usually empty because it
has only just restarted, so ask for the previous one:

  kubectl -n netlab get pods -l app=crashy
  kubectl -n netlab logs -l app=crashy --tail=20
  kubectl -n netlab logs <pod-name> --previous

And read the container state block, which carries the exit code:
  kubectl -n netlab describe pod <pod-name>

Look for "Last State: Terminated", "Reason", and "Exit Code".

Then look at what the container is actually being told to run:
  kubectl -n netlab get deploy crashy -o jsonpath='{.spec.template.spec.containers[0].command}'
H
}

drill_solution() { cat <<'S'
Diagnose:
  kubectl -n netlab get pods -l app=crashy
    NAME                     READY  STATUS             RESTARTS  AGE
    crashy-5d9f...-x2k4l     0/1    CrashLoopBackOff   4         2m

  kubectl -n netlab logs -l app=crashy --previous --tail=20
    starting
    FATAL: config not found

  kubectl -n netlab describe pod -l app=crashy | sed -n '/Last State/,/Ready/p'
    Last State:     Terminated
      Reason:       Error
      Exit Code:    1

  Exit code 1 with a message means the application chose to stop. The
  container image is fine, the scheduling is fine -- the command is wrong.

  kubectl -n netlab get deploy crashy \
    -o jsonpath='{.spec.template.spec.containers[0].command}'
    ["sh","-c","echo starting; sleep 2; echo 'FATAL: config not found'; exit 1"]

Fix -- patch the command so the process stays alive:
  kubectl -n netlab patch deployment crashy --type=json -p='[
    {"op":"replace","path":"/spec/template/spec/containers/0/command",
     "value":["sh","-c","echo starting; sleep infinity"]}]'

  Or interactively, which is what you will usually do:
  kubectl -n netlab edit deployment crashy
  (change the command, save, quit -- the rollout happens automatically)

Confirm:
  kubectl -n netlab rollout status deployment/crashy
  kubectl -n netlab get pods -l app=crashy
    crashy-...   1/1   Running   0   20s
S
}

drill_debrief() { cat <<'D'
Read the STATUS column as a diagnosis, not a description. Each value points
at a different subsystem:

  Pending            not scheduled yet -> describe the pod, read Events.
                     Usually resources, taints, or no matching node.
  ContainerCreating  scheduled, still setting up -> usually image pull,
                     volume mount, or a missing ConfigMap/Secret.
  ImagePullBackOff   cannot fetch the image -> name, tag, or registry auth.
  CrashLoopBackOff   it runs and exits -> logs --previous. Your bug.
  Error              exited non-zero and is not being restarted.
  OOMKilled          exceeded its memory limit -> raise limits or fix the leak.
  Running but 0/1    readiness probe failing -> describe the pod.
  Terminating stuck  a finalizer or a long terminationGracePeriodSeconds.

Exit codes worth recognising:
  0    clean exit. In a Deployment this still restarts -- use a Job instead.
  1    generic application error. Read the logs.
  137  SIGKILL, 128+9. Almost always OOMKilled, or a failed graceful stop.
  143  SIGTERM, 128+15. Normal shutdown during a rollout or scale-down.

The single most useful debugging command in Kubernetes:
  kubectl -n <ns> describe pod <pod>
The Events section at the bottom is a timeline of every decision the
scheduler, kubelet and container runtime made about that pod.

And the one people forget: --previous. When a container is restarting, the
current instance has no logs yet. The evidence is in the last one.
D
}
