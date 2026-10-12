DRILL_TITLE="ImagePullBackOff"
DRILL_MODULE="k8s"
DRILL_LEVEL=1
DRILL_TIME="10 min"
DRILL_TOOLS="kubectl describe, events, set image"
DRILL_BRIEF="A Deployment named 'imgtest' will not start. The pod sits at
ErrImagePull, then ImagePullBackOff, and never produces any application logs
at all."
DRILL_GOAL="Get 'imgtest' to 1 ready replica running a real nginx image."

drill_reset() { k8s_clean_workloads; }

drill_break() {
  k8s_clean_workloads
  kube apply -f "$K8S_MANIFESTS/03-imagepull.yaml" >/dev/null 2>&1
}

drill_verify() {
  k_image_is imgtest "nginx" || { warn "The Deployment should still run an nginx image."; return 1; }
  k_deploy_ready imgtest 1
}

drill_hint() { cat <<'H'
No application logs at all is the tell: the container never started, so
there is nothing to log. The failure is earlier than the application.

  kubectl -n netlab get pods -l app=imgtest
  kubectl -n netlab describe pod -l app=imgtest | tail -20

Read the Events at the bottom. The registry error text is quoted there
verbatim, and it distinguishes the three causes:
  "manifest unknown" / "not found"  -> the tag does not exist (typo)
  "unauthorized" / "denied"         -> private registry, missing pull secret
  "no such host" / i/o timeout      -> the node cannot reach the registry

Then compare the image string in the Deployment against reality:
  kubectl -n netlab get deploy imgtest \
    -o jsonpath='{.spec.template.spec.containers[0].image}'
H
}

drill_solution() { cat <<'S'
Diagnose:
  kubectl -n netlab get pods -l app=imgtest
    NAME              READY  STATUS             RESTARTS  AGE
    imgtest-...       0/1    ImagePullBackOff   0         45s

  kubectl -n netlab describe pod -l app=imgtest | tail -15
    Events:
      Warning  Failed  ...  Failed to pull image "nginx:1.27-alpin":
               failed to resolve reference: not found
      Warning  Failed  ...  Error: ErrImagePull
      Normal   BackOff ...  Back-off pulling image "nginx:1.27-alpin"

  kubectl -n netlab get deploy imgtest \
    -o jsonpath='{.spec.template.spec.containers[0].image}'
    nginx:1.27-alpin                <-- the tag is misspelled

Fix:
  kubectl -n netlab set image deployment/imgtest web=nginx:1.27-alpine

  "web" is the CONTAINER name, not the deployment name. Find it with:
  kubectl -n netlab get deploy imgtest \
    -o jsonpath='{.spec.template.spec.containers[*].name}'

Confirm:
  kubectl -n netlab rollout status deployment/imgtest
  kubectl -n netlab get pods -l app=imgtest

If it had been a PRIVATE registry, the fix is a pull secret instead:
  kubectl -n netlab create secret docker-registry regcred \
    --docker-server=registry.example.com \
    --docker-username=USER --docker-password=PASS
  kubectl -n netlab patch deployment imgtest -p \
    '{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"regcred"}]}}}}'
S
}

drill_debrief() { cat <<'D'
The Events list is where Kubernetes tells you the truth. Two ways in:

  kubectl -n netlab describe pod <pod>          # events for one object
  kubectl -n netlab get events --sort-by=.lastTimestamp | tail -20
                                                # everything, newest last

Events expire (one hour by default), so a pod that failed overnight may
have no events left. That is when you fall back to the object status.

Tag discipline, since this failure is entirely self-inflicted:
  - Never use :latest in anything you care about. It is unpinned, it is
    cached inconsistently across nodes, and rollbacks become meaningless.
  - Pin a real version (nginx:1.27-alpine), or pin a digest
    (nginx@sha256:...) when you need to be certain the bytes never change.
  - imagePullPolicy defaults to IfNotPresent for a fixed tag and Always for
    :latest. That surprise alone is a good reason to avoid :latest.

Also worth knowing: ErrImagePull is the first attempt failing;
ImagePullBackOff is the kubelet backing off before retrying. Seeing the
second one just means it has already tried a few times.
D
}
