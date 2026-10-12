DRILL_TITLE="Missing ConfigMap and Secret"
DRILL_MODULE="k8s"
DRILL_LEVEL=2
DRILL_TIME="20 min"
DRILL_TOOLS="kubectl create configmap/secret, describe pod, exec"
DRILL_BRIEF="The 'cfgapp' Deployment is stuck. The pod never reaches Running --
it sits in ContainerCreating or CreateContainerConfigError. There are no
application logs because the container was never created."
DRILL_GOAL="Create the configuration the Deployment expects so the pod runs:
  - a ConfigMap named 'app-config' with key GREETING = hello-netlab
  - a Secret named 'app-secret' with key token = example-only-token
Success = pod Running, GREETING visible in its environment, and the ConfigMap
mounted at /etc/appconfig."

drill_reset() { k8s_clean_workloads; }

drill_break() {
  k8s_clean_workloads
  kn delete configmap app-config --ignore-not-found >/dev/null 2>&1
  kn delete secret app-secret --ignore-not-found >/dev/null 2>&1
  kube apply -f "$K8S_MANIFESTS/07-configmap-app.yaml" >/dev/null 2>&1
}

drill_verify() {
  k_deploy_ready cfgapp 1 || { warn "Pod 'cfgapp' is not running yet."; return 1; }
  k_env_has cfgapp GREETING "hello-netlab" || { warn "GREETING is not set to hello-netlab."; return 1; }
  k_env_has cfgapp API_TOKEN "example-only-token" || { warn "API_TOKEN is not coming from the Secret."; return 1; }
  k_file_has cfgapp /etc/appconfig/GREETING "hello-netlab"
}

drill_hint() { cat <<'H'
The container was never created, so the failure is in the pod spec, not the
application. Ask what the kubelet could not find:

  kubectl -n netlab get pods -l app=cfgapp
  kubectl -n netlab describe pod -l app=cfgapp | tail -15

Look for "configmap ... not found" or "secret ... not found" in the Events.

Then read exactly what the Deployment is asking for -- the names and the
KEYS both have to match:
  kubectl -n netlab get deploy cfgapp -o yaml | grep -A6 -E 'env:|volumes:'

Create them:
  kubectl create configmap NAME --from-literal=KEY=VALUE
  kubectl create secret generic NAME --from-literal=KEY=VALUE
H
}

drill_solution() { cat <<'S'
Diagnose:
  kubectl -n netlab describe pod -l app=cfgapp | tail -10
    Warning  Failed  ...  Error: configmap "app-config" not found

  kubectl -n netlab get deploy cfgapp -o yaml | grep -B2 -A6 valueFrom
    configMapKeyRef: { name: app-config, key: GREETING }
    secretKeyRef:    { name: app-secret, key: token }

Fix:
  kubectl -n netlab create configmap app-config \
    --from-literal=GREETING=hello-netlab
  kubectl -n netlab create secret generic app-secret \
    --from-literal=token=example-only-token

  The pod is already retrying, but you can force it immediately:
  kubectl -n netlab rollout restart deployment/cfgapp

Confirm:
  kubectl -n netlab get pods -l app=cfgapp
  kubectl -n netlab exec deploy/cfgapp -- printenv GREETING API_TOKEN
    hello-netlab
    example-only-token
  kubectl -n netlab exec deploy/cfgapp -- ls -l /etc/appconfig
  kubectl -n netlab exec deploy/cfgapp -- cat /etc/appconfig/GREETING

Inspect what you created:
  kubectl -n netlab get configmap app-config -o yaml
  kubectl -n netlab get secret app-secret -o yaml
    data:
      token: ZXhhbXBsZS1vbmx5LXRva2Vu # gitleaks:allow -- deliberately synthetic tutorial example          <-- base64, NOT encryption
  kubectl -n netlab get secret app-secret -o jsonpath='{.data.token}' | base64 -d

Other ways to build them, which you will use more often than --from-literal:
  kubectl create configmap app-config --from-file=./app.properties
  kubectl create configmap app-config --from-env-file=./app.env
  kubectl create secret generic app-secret --from-file=./token.txt
S
}

drill_debrief() { cat <<'D'
Two ways to consume a ConfigMap or Secret, and the difference matters:

  As environment variables (env / envFrom)
    Read once at container start. Changing the ConfigMap does NOT update a
    running pod -- you must restart it:
      kubectl rollout restart deployment/<name>

  As a mounted volume
    Projected as files. The kubelet refreshes them within about a minute,
    so an application that re-reads its config file picks up changes with no
    restart. This is why config files beat env vars for anything you want to
    change at runtime.

About Secrets, plainly: the "data" field is base64, which is an encoding,
not encryption. Anyone who can read the Secret in the API, or read etcd, can
read the value. To make Secrets meaningfully secret you need at least:
  - RBAC that actually restricts who can get/list Secrets in the namespace
  - encryption at rest enabled on etcd
  - and for real deployments, an external store (Vault, cloud secret
    manager, External Secrets Operator, SOPS for git)

Never put a Secret in git in plaintext, and note that "kubectl describe
secret" hides values while "kubectl get secret -o yaml" shows them -- which
makes describe the safer command to run while screen-sharing.

Immutable ConfigMaps and Secrets (immutable: true) are worth knowing: they
cannot be edited, only replaced, which prevents surprise config drift and
reduces load on the API server in large clusters.
D
}
