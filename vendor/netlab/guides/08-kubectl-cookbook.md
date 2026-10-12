# 08 - kubectl cookbook

All examples use the lab namespace. Save yourself the `-n` on every command:

```bash
kubectl config set-context --current --namespace=netlab
```

---

## Setup and context

```bash
kubectl version
kubectl cluster-info
kubectl config view --minify
kubectl config get-contexts
kubectl config use-context <name>
kubectl config set-context --current --namespace=netlab
kubectl api-resources                     # every object type + short name
kubectl explain deployment.spec.strategy  # the schema, from the API server
```

`kubectl explain` is underrated - it is authoritative documentation for the
exact cluster version you are on, offline, with no browser.

Aliases worth adding to `~/.bashrc`:

```bash
alias k=kubectl
source <(kubectl completion bash)
complete -o default -F __start_kubectl k
export KUBE_EDITOR=nano        # if you do not want vi on kubectl edit
```

---

## Looking at things

```bash
kubectl get pods
kubectl get pods -o wide                     # + IP, node
kubectl get pods -A                          # all namespaces
kubectl get pods --show-labels
kubectl get pods -l app=web                  # by label
kubectl get pods -l 'env in (prod,staging)'
kubectl get pods --field-selector=status.phase=Running
kubectl get pods --sort-by=.metadata.creationTimestamp
kubectl get pods -w                          # watch for changes

kubectl get all                              # common types (not everything!)
kubectl get deploy,rs,pods,svc,ep
kubectl get pod <pod> -o yaml
kubectl get pod <pod> -o json | jq '.status.containerStatuses'

kubectl describe pod <pod>                   # THE debugging command
kubectl describe svc <svc>
kubectl describe node
```

`kubectl get all` is a lie - it omits ConfigMaps, Secrets, Ingresses,
NetworkPolicies, PVCs and CRDs. When you think something is missing, name it.

JSONPath and custom columns, for scripts:

```bash
kubectl get pods -o jsonpath='{.items[*].metadata.name}'
kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.podIP}{"\n"}{end}'
kubectl get deploy web -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl get pods -o custom-columns='NAME:.metadata.name,NODE:.spec.nodeName,IP:.status.podIP'
kubectl get nodes -o custom-columns='NAME:.metadata.name,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory'
```

---

## Creating things

Imperative - fast, good for quick fixes and exams:

```bash
kubectl create deployment web --image=nginx:1.27-alpine --replicas=3
kubectl expose deployment web --port=80 --target-port=80
kubectl expose deployment web --type=NodePort --port=80
kubectl create configmap app-config --from-literal=KEY=value
kubectl create configmap app-config --from-file=./config.properties
kubectl create secret generic app-secret --from-literal=token=abc
kubectl create namespace myapp
kubectl create job hello --image=busybox:1.36 -- echo hello
kubectl create cronjob nightly --image=busybox:1.36 --schedule="0 2 * * *" -- echo hi
kubectl run tmp --rm -it --restart=Never --image=busybox:1.36 -- sh
```

Declarative - what you keep in git:

```bash
kubectl apply -f manifest.yaml
kubectl apply -f ./manifests/            # a whole directory
kubectl apply -k ./overlays/prod/        # kustomize
kubectl diff -f manifest.yaml            # what WOULD change. Use this first.
kubectl delete -f manifest.yaml
```

**Generate YAML instead of writing it from memory:**

```bash
kubectl create deployment web --image=nginx:1.27-alpine \
  --dry-run=client -o yaml > deploy.yaml

kubectl expose deployment web --port=80 \
  --dry-run=client -o yaml > svc.yaml

kubectl create configmap app --from-literal=A=b --dry-run=client -o yaml
```

---

## Changing things

```bash
kubectl edit deployment web                       # opens $EDITOR, applies on save
kubectl scale deployment web --replicas=5
kubectl set image deployment/web nginx=nginx:1.27-alpine
kubectl set env deployment/web LOG_LEVEL=debug
kubectl set resources deployment/web --requests=cpu=100m,memory=128Mi
kubectl label pod <pod> tier=frontend
kubectl annotate deployment web kubernetes.io/change-cause="pin 1.27" --overwrite
kubectl rollout restart deployment/web            # recreate pods, pick up config
```

Patching, when you need to be precise or scriptable:

```bash
# strategic merge (the usual one)
kubectl patch deployment web -p '{"spec":{"replicas":4}}'

# JSON patch, for exact paths and array indexes
kubectl patch deployment web --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/image","value":"nginx:1.27-alpine"}]'

# replace a whole field
kubectl patch svc web -p '{"spec":{"selector":{"app":"web"}}}'
```

---

## Deleting things

```bash
kubectl delete pod <pod>                     # a managed pod comes straight back
kubectl delete deployment web
kubectl delete -f manifest.yaml
kubectl delete pods -l app=web
kubectl delete pod <pod> --grace-period=0 --force     # last resort
kubectl delete namespace myapp               # deletes everything inside it
```

A namespace stuck `Terminating` is almost always a finalizer on some object
inside it:

```bash
kubectl get namespace myapp -o json | jq '.spec.finalizers'
kubectl api-resources --verbs=list --namespaced -o name \
  | xargs -n1 kubectl get -n myapp --ignore-not-found
```

---

## Logs

```bash
kubectl logs <pod>
kubectl logs <pod> -c <container>            # multi-container pod
kubectl logs <pod> --previous                # the CRASHED instance. Essential.
kubectl logs -f <pod>                        # follow
kubectl logs --tail=100 <pod>
kubectl logs --since=15m <pod>
kubectl logs --timestamps <pod>
kubectl logs -l app=web --all-containers --prefix    # across every matching pod
kubectl logs deploy/web                      # picks one pod from the deployment
```

`--previous` is the one people forget. When a container is in
CrashLoopBackOff, the current instance has barely started - the evidence is in
the one that died.

---

## Exec, copy, port-forward

```bash
kubectl exec -it <pod> -- sh
kubectl exec -it <pod> -c <container> -- bash
kubectl exec <pod> -- ls -l /etc
kubectl exec deploy/web -- printenv
kubectl exec -it toolbox -- wget -qO- http://web

kubectl cp <pod>:/etc/nginx/nginx.conf ./nginx.conf
kubectl cp ./file.txt <pod>:/tmp/file.txt

kubectl port-forward pod/<pod> 8080:80
kubectl port-forward deploy/web 8080:80
kubectl port-forward svc/web 8080:80
```

`port-forward` is how you test a ClusterIP Service from your laptop without
exposing anything. It is also the safest way to reach a database in-cluster.

Ephemeral debug containers, for images with no shell:

```bash
kubectl debug -it <pod> --image=busybox:1.36 --target=<container>
kubectl debug node/<node> -it --image=busybox:1.36
```

---

## Events and status

```bash
kubectl get events --sort-by=.lastTimestamp | tail -20
kubectl get events -A --sort-by=.lastTimestamp | tail -30
kubectl get events --field-selector type=Warning
kubectl get events --field-selector involvedObject.name=<pod>
kubectl get events -w
```

Events expire after about an hour by default. A failure from overnight leaves
no events behind - fall back to object status and logs.

---

## Rollouts

```bash
kubectl rollout status deployment/web
kubectl rollout status deployment/web --timeout=60s
kubectl rollout history deployment/web
kubectl rollout history deployment/web --revision=2
kubectl rollout undo deployment/web
kubectl rollout undo deployment/web --to-revision=2
kubectl rollout pause deployment/web
kubectl rollout resume deployment/web
kubectl rollout restart deployment/web
```

Set the change-cause on every deploy and `rollout history` becomes readable:

```bash
kubectl annotate deployment web kubernetes.io/change-cause="upgrade to 1.27.3" --overwrite
```

---

## Nodes and capacity

```bash
kubectl get nodes -o wide
kubectl describe node <node>
kubectl top nodes                     # needs metrics-server
kubectl top pods
kubectl cordon <node>                 # stop scheduling new pods here
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
kubectl uncordon <node>
kubectl taint nodes <node> key=value:NoSchedule
kubectl taint nodes <node> key-       # remove the taint (note trailing dash)
```

What is actually allocated on a node:

```bash
kubectl describe node | grep -A8 "Allocated resources"
kubectl get pods -A -o wide --field-selector spec.nodeName=<node>
```

---

## Permissions

```bash
kubectl auth can-i create deployments
kubectl auth can-i delete pods -n netlab
kubectl auth can-i --list
kubectl auth can-i get secrets --as=system:serviceaccount:netlab:default
```

`--as` is the fastest way to debug an RBAC problem: impersonate the identity
that is failing and ask the API server directly.

---

## Quick recipes

```bash
# every pod not Running
kubectl get pods -A --field-selector=status.phase!=Running

# pods with restarts
kubectl get pods -A -o json | jq -r '
  .items[] | select(.status.containerStatuses[]?.restartCount > 0)
  | "\(.metadata.namespace)/\(.metadata.name) \(.status.containerStatuses[0].restartCount)"'

# every image in use
kubectl get pods -A -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.image}{"\n"}{end}{end}' | sort -u

# services with no endpoints (broken selectors)
kubectl get endpoints -A | awk '$3=="<none>"'

# what is eating the cluster
kubectl top pods -A --sort-by=memory | head -20

# a temporary network debugging pod
kubectl run netshoot --rm -it --image=nicolaka/netshoot -- bash

# decode a secret
kubectl get secret app-secret -o jsonpath='{.data.token}' | base64 -d

# force every pod of a deployment to restart
kubectl rollout restart deployment/web

# delete evicted / completed pods
kubectl delete pods --field-selector=status.phase==Failed -A
kubectl delete pods --field-selector=status.phase==Succeeded -A
```
