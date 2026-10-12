# 09 - Kubernetes troubleshooting

A decision tree. Find your symptom, follow the branch.

---

## Always start here

```bash
kubectl -n <ns> get pods -o wide
kubectl -n <ns> describe pod <pod>          # read Events at the BOTTOM
kubectl -n <ns> logs <pod> --previous
kubectl -n <ns> get events --sort-by=.lastTimestamp | tail -20
```

The `STATUS` column is a diagnosis, not a description. Each value points at a
different subsystem.

---

## Pod status decision tree

### `Pending`

The scheduler could not place it. There is no container, so no logs.

```bash
kubectl -n <ns> describe pod <pod> | tail -12
```

The `FailedScheduling` event names the failed predicate:

| Message | Cause | Fix |
|---|---|---|
| `Insufficient cpu` / `memory` | requests exceed free capacity | lower requests, or add capacity |
| `had untolerated taint` | node is tainted | add a toleration, or use another node |
| `didn't match node selector` | `nodeSelector` matches no node | fix the label or the selector |
| `didn't match pod affinity` | affinity rules unsatisfiable | relax them |
| `had volume node affinity conflict` | PV is pinned to another node | fix storage class / zone |
| `0/N nodes are available` (all) | nodes cordoned or NotReady | `kubectl get nodes` |

```bash
kubectl describe node | grep -A8 "Allocated resources"
kubectl get nodes -o custom-columns='NAME:.metadata.name,TAINTS:.spec.taints'
```

If it is a PVC: `kubectl -n <ns> get pvc` - a `Pending` PVC means no
StorageClass, or no provisioner, and the pod waits forever.

Drill: `k8s-04-pending-pod`.

### `ContainerCreating` (stuck)

Scheduled, but the kubelet cannot start it.

```bash
kubectl -n <ns> describe pod <pod> | tail -15
```

Usual causes:
- `configmap "x" not found` / `secret "x" not found` -> create it (drill `k8s-07`)
- volume mount failing -> check the PVC is `Bound` and the node can attach it
- image still pulling -> just slow; a big image on a slow link
- CNI failure -> `failed to set up sandbox`; check the CNI pods in `kube-system`

### `ImagePullBackOff` / `ErrImagePull`

```bash
kubectl -n <ns> describe pod <pod> | tail -10
```

The registry's own error text is quoted in the event:

| Text | Cause |
|---|---|
| `manifest unknown`, `not found` | wrong image name or tag (a typo) |
| `unauthorized`, `denied` | private registry, missing or wrong `imagePullSecrets` |
| `no such host`, `i/o timeout` | the node cannot reach the registry (DNS, egress firewall, proxy) |
| `toomanyrequests` | Docker Hub rate limit - authenticate or use a mirror |

```bash
kubectl -n <ns> get deploy <d> -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl -n <ns> set image deployment/<d> <container>=<correct-image>
```

Drill: `k8s-03-imagepullbackoff`.

### `CrashLoopBackOff`

The container starts, exits, and is restarted with increasing delay. The
container is fine; the process is choosing to exit.

```bash
kubectl -n <ns> logs <pod> --previous            # <- the important one
kubectl -n <ns> describe pod <pod> | grep -A6 "Last State"
```

| Exit code | Meaning |
|---|---|
| `0` | clean exit. In a Deployment this still restarts - you wanted a Job. |
| `1` | application error. Read the logs. |
| `137` | SIGKILL (128+9). Almost always **OOMKilled**. Check memory limits. |
| `143` | SIGTERM (128+15). Normal shutdown during a rollout. |
| `126` / `127` | command not executable / not found. Wrong `command` or image. |

```bash
kubectl -n <ns> get pod <pod> -o jsonpath='{.status.containerStatuses[0].lastState}'
```

If OOMKilled: raise `limits.memory`, or fix the leak. Note the container is
killed at the **limit**, not the request.

To debug a container that dies too fast to exec into, override the command
temporarily:

```bash
kubectl -n <ns> patch deployment <d> --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/command",
   "value":["sh","-c","sleep infinity"]}]'
kubectl -n <ns> exec -it deploy/<d> -- sh
```

Drill: `k8s-02-crashloop`.

### `Running` but `0/1 READY`

The process is alive; the readiness probe is failing. The pod is deliberately
removed from Service endpoints.

```bash
kubectl -n <ns> describe pod <pod> | grep -A4 -i readiness
kubectl -n <ns> get deploy <d> -o jsonpath='{.spec.template.spec.containers[0].readinessProbe}'
kubectl -n <ns> exec <pod> -- wget -qO- -T2 http://127.0.0.1:<port><path>
```

Check the probe's port and path against what the container actually serves.
Then check `initialDelaySeconds` is long enough for the app to start.

Drill: `k8s-06-readiness-probe`.

### `Terminating` (stuck)

```bash
kubectl -n <ns> get pod <pod> -o json | jq '.metadata.finalizers'
kubectl -n <ns> describe pod <pod>
```

Causes: a finalizer waiting on something, a long
`terminationGracePeriodSeconds`, a volume that will not unmount, or a node that
is gone. Last resort:

```bash
kubectl -n <ns> delete pod <pod> --grace-period=0 --force
```

### `Evicted`

The node ran out of a resource (usually disk or memory) and the kubelet evicted
pods to recover.

```bash
kubectl -n <ns> describe pod <pod> | grep -i "Message"
kubectl describe node <node> | grep -A5 Conditions      # DiskPressure? MemoryPressure?
kubectl delete pods --field-selector=status.phase==Failed -A
```

### `Init:0/1` or `Init:Error`

An init container has not completed.

```bash
kubectl -n <ns> logs <pod> -c <init-container-name>
kubectl -n <ns> describe pod <pod> | grep -A10 "Init Containers"
```

---

## "The Service does not work"

Ask this first, always:

```bash
kubectl -n <ns> get endpointslices -l kubernetes.io/service-name=<svc>
```

### No endpoints

The problem is **before** the network. Do not touch DNS or CNI.

```bash
kubectl -n <ns> describe svc <svc>          # what is the Selector?
kubectl -n <ns> get pods --show-labels      # what are the pod LABELS?
kubectl -n <ns> get pods                    # are they READY?
```

- Selector does not match pod labels -> fix the Service (drill `k8s-05`).
- Pods are `0/1` -> readiness probe (drill `k8s-06`).
- No pods at all -> the Deployment is the problem, go back up this guide.

### Has endpoints, still unreachable

The problem is **after**. Work through:

```bash
# 1. DNS
kubectl -n <ns> exec toolbox -- nslookup <svc>
kubectl -n kube-system get pods -l k8s-app=kube-dns

# 2. the right port
kubectl -n <ns> get svc <svc> -o yaml | grep -A5 ports
#    port = what clients connect to; targetPort = the CONTAINER's port

# 3. NetworkPolicy
kubectl -n <ns> get netpol
kubectl -n <ns> describe netpol <name>

# 4. the app itself, bypassing the Service entirely
kubectl -n <ns> exec toolbox -- wget -qO- http://<POD-IP>:<targetPort>
```

That last test is the decisive one. If the pod IP works and the Service IP does
not, the problem is the Service or kube-proxy. If the pod IP also fails, it is
the application or a NetworkPolicy.

Drills: `k8s-05`, `k8s-09`.

---

## DNS problems

```bash
kubectl -n netlab exec toolbox -- nslookup kubernetes.default
kubectl -n netlab exec toolbox -- cat /etc/resolv.conf
kubectl -n kube-system get pods -l k8s-app=kube-dns
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=50
```

A pod's `/etc/resolv.conf` should look like:

```
nameserver 10.43.0.10
search netlab.svc.cluster.local svc.cluster.local cluster.local
options ndots:5
```

`ndots:5` means any name with fewer than 5 dots is tried against every search
domain first. This is why `wget http://web` works and why external lookups can
be slow - each one does several failed searches first. Use a trailing dot
(`example.com.`) to skip the search list.

If DNS fails for everything, and you have default-deny **egress**
NetworkPolicies, you almost certainly forgot to allow UDP/TCP 53 to
`kube-system`. That is the classic self-inflicted cluster outage.

---

## Rollout is stuck

```bash
kubectl -n <ns> rollout status deployment/<d> --timeout=10s
kubectl -n <ns> get rs -l app=<d>            # two ReplicaSets: old good, new bad
kubectl -n <ns> get pods -l app=<d>          # what is wrong with the new pods?
kubectl -n <ns> describe pod <new-pod>
```

With `maxUnavailable: 0`, a broken new version stalls rather than causing an
outage - the old pods keep serving. Roll back first, investigate second:

```bash
kubectl -n <ns> rollout undo deployment/<d>
```

Drill: `k8s-08-rollout-rollback`.

---

## Node problems

```bash
kubectl get nodes
kubectl describe node <node> | grep -A10 Conditions
```

| Condition | Meaning |
|---|---|
| `Ready=False` | kubelet not reporting. Check the kubelet and the network. |
| `MemoryPressure=True` | node is low on RAM; eviction is imminent |
| `DiskPressure=True` | low disk. Usually image or log accumulation. |
| `PIDPressure=True` | too many processes |
| `NetworkUnavailable=True` | CNI is not configured |

On the node itself (k3s):

```bash
sudo systemctl status k3s
sudo journalctl -u k3s -n 100 --no-pager
sudo crictl ps -a
sudo crictl logs <container-id>
df -h /var/lib/rancher
```

---

## Permissions (RBAC)

```bash
kubectl auth can-i --list
kubectl auth can-i create pods -n netlab
kubectl auth can-i get secrets --as=system:serviceaccount:netlab:default
```

`Forbidden` errors name the missing verb, resource and identity - read the
whole message, it usually tells you exactly what to add to the Role.

---

## Emergency toolkit

```bash
# a shell with real network tools
kubectl -n netlab run netshoot --rm -it --image=nicolaka/netshoot -- bash

# a shell in the same network namespace as a broken pod
kubectl -n netlab debug -it <pod> --image=nicolaka/netshoot --target=<container>

# reach a Service from your laptop without exposing it
kubectl -n netlab port-forward svc/<svc> 8080:80

# everything unhealthy, cluster-wide
kubectl get pods -A --field-selector=status.phase!=Running

# recent warnings everywhere
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp | tail -30

# what changed
kubectl -n netlab rollout history deployment/<d>
kubectl -n netlab get deploy <d> -o yaml | grep -A3 change-cause
```
