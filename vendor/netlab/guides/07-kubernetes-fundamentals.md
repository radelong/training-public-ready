# 07 - Kubernetes fundamentals

What the objects are, what runs where, and the handful of ideas that make the
rest obvious.

---

## The one big idea: declarative reconciliation

You do not tell Kubernetes to *do* things. You declare the state you want, and
controllers continuously work to make reality match.

```
you: "I want 3 replicas of nginx"
  -> stored in etcd via the API server
  -> the Deployment controller notices reality has 0
  -> creates a ReplicaSet
  -> the ReplicaSet controller creates 3 Pods
  -> the scheduler assigns each Pod to a node
  -> each kubelet starts the containers
  -> a pod dies -> the ReplicaSet controller notices -> creates another
```

This is why `kubectl delete pod` "does not work" - deleting a pod owned by a
ReplicaSet just triggers a replacement. You change the **Deployment**, not the
pod.

It is also why almost every problem is diagnosed by asking *why has the
controller not reconciled this yet*, and the answer is nearly always in
`kubectl describe` and the Events list.

---

## What runs where

**Control plane** (on a single-node k3s cluster, all inside the `k3s` process):

| Component | Job |
|---|---|
| `kube-apiserver` | the only thing that talks to etcd. Every request goes here. |
| `etcd` | the database. All cluster state. |
| `kube-scheduler` | decides which node each new pod goes to |
| `kube-controller-manager` | runs the built-in controllers (Deployment, ReplicaSet, Node...) |

**Every node**:

| Component | Job |
|---|---|
| `kubelet` | talks to the container runtime, starts/stops containers, runs probes |
| `kube-proxy` | writes the iptables rules that implement Services (guide 10) |
| container runtime | containerd. Actually runs containers. |
| CNI plugin | gives each pod an IP and wires up pod-to-pod networking |

```bash
kubectl get nodes -o wide
kubectl -n kube-system get pods
sudo systemctl status k3s
sudo journalctl -u k3s -f
```

---

## The object model

```
Deployment          declares desired state, manages rollouts   <- you edit this
   |
   +-- ReplicaSet   keeps N pods alive; one per revision       <- rollback lives here
          |
          +-- Pod   one or more containers, one IP, shared namespaces
                       |
                       +-- Container
```

Alongside them:

| Object | Purpose |
|---|---|
| `Service` | stable virtual IP + DNS name in front of a changing set of pods |
| `EndpointSlice` | the actual pod IPs behind a Service |
| `ConfigMap` | non-secret configuration, as env vars or mounted files |
| `Secret` | the same, base64-encoded, with slightly more access control |
| `Namespace` | a scope for names and a boundary for quota and policy |
| `Ingress` | HTTP routing from outside into Services (needs a controller) |
| `NetworkPolicy` | pod-level firewall rules (needs a CNI that enforces them) |
| `PersistentVolumeClaim` | a request for storage |
| `DaemonSet` | one pod on every node (agents, log shippers, CNI) |
| `StatefulSet` | ordered, stable identities and storage (databases) |
| `Job` / `CronJob` | run to completion, once or on a schedule |

---

## Pods

A pod is the smallest schedulable unit: one or more containers that share a
network namespace (so they reach each other on `localhost`) and can share
volumes.

```bash
kubectl -n netlab get pods
kubectl -n netlab get pods -o wide            # + IP and node
kubectl -n netlab describe pod <pod>
kubectl -n netlab logs <pod>
kubectl -n netlab logs <pod> -c <container>   # multi-container pod
kubectl -n netlab exec -it <pod> -- sh
```

Pods are **cattle**. They get replaced, never repaired. Their IP changes every
time. Never hard-code a pod IP anywhere.

Multi-container patterns worth recognising:

- **sidecar** - a helper alongside the app (log shipper, service mesh proxy)
- **init container** - runs to completion *before* the app starts (migrations,
  waiting for a dependency). A pod stuck in `Init:0/1` is waiting on one.

---

## Deployments

```bash
kubectl -n netlab create deployment web --image=nginx:1.27-alpine --replicas=3
kubectl -n netlab get deploy,rs,pods
kubectl -n netlab scale deployment web --replicas=5
kubectl -n netlab set image deployment/web nginx=nginx:1.27-alpine
kubectl -n netlab rollout status deployment/web
kubectl -n netlab rollout history deployment/web
kubectl -n netlab rollout undo deployment/web
kubectl -n netlab rollout restart deployment/web
```

Rollout strategy fields that decide how safe a bad deploy is:

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 0    # never lose capacity; a broken deploy STALLS instead
    maxSurge: 1          # allow one extra pod while rolling
```

`maxUnavailable: 0` plus a correct readiness probe is what makes a bad image
freeze the rollout rather than cause an outage.

A rollout only happens when the **pod template** changes. Changing `replicas`
is a scale. Changing a ConfigMap the pods read triggers nothing at all - which
is exactly why `kubectl rollout restart` exists.

---

## Services

A Service is a stable virtual IP and DNS name in front of a set of pods it
finds **by label selector**. It has no link to the Deployment at all.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web
spec:
  type: ClusterIP
  selector:
    app: web          # <- matches POD labels. Typo here = no endpoints.
  ports:
    - port: 80        # the port clients connect to on the Service
      targetPort: 80  # the port the CONTAINER listens on
```

| Type | Reachable from |
|---|---|
| `ClusterIP` | inside the cluster only (the default) |
| `NodePort` | also on every node IP at a high port, 30000-32767 |
| `LoadBalancer` | asks the cloud (or k3s ServiceLB) for an external IP |
| `ExternalName` | just a CNAME to an external hostname |
| headless (`clusterIP: None`) | DNS returns pod IPs directly; used by StatefulSets |

Cluster DNS follows a fixed pattern:

```
<service>.<namespace>.svc.cluster.local
web.netlab.svc.cluster.local
web.netlab                            # works
web                                   # works within the same namespace
```

**The one question to ask when a Service does not work:**

```bash
kubectl -n netlab get endpointslices -l kubernetes.io/service-name=web
```

Empty means the selector matches nothing, or the matching pods are not Ready.
Non-empty means look at DNS, NetworkPolicy, ports, or the app.

---

## Configuration

```bash
kubectl -n netlab create configmap app-config --from-literal=GREETING=hello
kubectl -n netlab create configmap app-config --from-file=./app.properties
kubectl -n netlab create secret generic app-secret --from-literal=token=abc123
```

```yaml
env:
  - name: GREETING
    valueFrom:
      configMapKeyRef: { name: app-config, key: GREETING }
envFrom:
  - configMapRef: { name: app-config }      # every key becomes an env var
volumeMounts:
  - name: config
    mountPath: /etc/appconfig
volumes:
  - name: config
    configMap: { name: app-config }
```

The difference that matters: **env vars are read once at container start**, so
changing the ConfigMap needs `kubectl rollout restart`. **Mounted files are
refreshed** within about a minute, so an app that re-reads its config picks up
changes with no restart.

Secrets are base64, which is an encoding, not encryption. Anyone who can read
the Secret through the API can read the value. Real protection needs RBAC,
etcd encryption at rest, and ideally an external secret store.

---

## Probes

| Probe | Question | Failure means |
|---|---|---|
| `readinessProbe` | can I take traffic now? | removed from Service endpoints. **Not restarted.** |
| `livenessProbe` | am I wedged? | container is **killed and restarted** |
| `startupProbe` | have I finished booting? | suspends the other two until it passes |

```yaml
readinessProbe:
  httpGet: { path: /healthz, port: 8080 }
  initialDelaySeconds: 5
  periodSeconds: 10
  failureThreshold: 3
```

Rules that prevent most probe incidents:

- Readiness aggressive, liveness conservative.
- Probe endpoints must be cheap and must **not** check downstream services. A
  `/health` that checks the database turns one database blip into every pod
  going unready at once.
- If unsure, ship readiness only. A missing liveness probe costs you a manual
  restart; a bad one costs you an outage.
- Slow starters get a `startupProbe`, not an inflated liveness threshold.

---

## Resources

```yaml
resources:
  requests:            # what the SCHEDULER reserves
    cpu: "100m"        # 100 millicores = 0.1 core
    memory: "128Mi"
  limits:              # what the KERNEL enforces (cgroups)
    cpu: "500m"
    memory: "256Mi"
```

- Exceeding a **memory** limit gets the container OOMKilled, exit code 137.
- Exceeding a **CPU** limit only throttles it - it shows up as latency, not
  errors, which makes it much harder to spot.
- `Mi` (1024^2) and `M` (1000^2) are different. So are `Gi` and `G`.
- The scheduler only counts **requests**. A cluster can be "100% allocated" at
  5% real utilisation because someone copied optimistic requests from a blog.

---

## Namespaces

```bash
kubectl get namespaces
kubectl create namespace myapp
kubectl -n myapp get all
kubectl config set-context --current --namespace=netlab   # stop typing -n
```

Namespaces scope names, RBAC, quotas and NetworkPolicy. They are **not** a
security boundary on their own - pods in different namespaces can reach each
other freely unless a NetworkPolicy says otherwise.

---

## The five commands that solve most problems

```bash
kubectl -n <ns> get pods
kubectl -n <ns> describe pod <pod>          # read the Events at the bottom
kubectl -n <ns> logs <pod> --previous       # for a restarting container
kubectl -n <ns> get events --sort-by=.lastTimestamp | tail -20
kubectl -n <ns> get endpointslices
```

And two flags that make you faster at everything:

```bash
kubectl ... -o yaml                              # the object as stored
kubectl create ... --dry-run=client -o yaml      # generate correct YAML
```
