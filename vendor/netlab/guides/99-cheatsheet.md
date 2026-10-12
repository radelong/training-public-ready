# 99 - One-page cheat sheet

---

## Triage ladder (stop at the first failure)

```
1. ip -br link                 interface up?
2. ip -br addr                 right address and prefix?
3. ip route get <dst>          route exists? which next hop?
4. ping <gateway>              layer 2 to next hop? ip neigh show
5. tcpdump both ends           where does the packet stop?
6. ss -ltnp   (on server)      is anything listening, on which address?
7. getent hosts <name>         does the name resolve, and to what?
```

## Error message -> cause

| Message | Look at |
|---|---|
| `Network is unreachable` | no route. Default route missing. |
| `Destination Host Unreachable` | ARP failed. Wrong gateway, or dead next hop. |
| `Connection refused` | nothing listening. Or a REJECT. |
| `Connection timed out` / 100% loss | firewall DROP, or return path broken. |
| `Packet filtered` | an explicit REJECT somewhere. |
| Works by IP, not by name | DNS / `/etc/hosts` / nsswitch. |
| Small works, large hangs | **MTU**. Always. |
| ping fails, TCP works | ICMP filtered. Nothing is down. |

---

## Networking

```bash
ip -br addr / ip -br link / ip -c -br addr        # fast status
ip addr add 10.0.0.5/24 dev eth0
ip addr flush dev eth0
ip link set eth0 up|down
ip link set eth0 mtu 1400

ip route show
ip route get 10.10.2.10                          # THE routing command
ip route replace default via 10.0.0.1            # idempotent
ip route del 10.10.2.0/24
ip rule show                                     # policy routing

ip neigh show                                    # ARP cache
ip neigh flush all
arping -I eth0 -c3 10.0.0.1                      # who owns this IP?

ss -ltnp                                         # listening TCP + process
ss -tnp                                          # established

tcpdump -ni eth0 host 10.10.2.10
tcpdump -ni eth0 tcp port 8080
tcpdump -ni any icmp -c 20

ping -M do -s 1472 <host>                        # test MTU 1500
tracepath <host>                                 # per-hop MTU
getent hosts <name>                              # what the APP sees
dig +short <name>                                # what DNS says
resolvectl status                                # real upstream resolvers

ip netns list
ip netns exec <ns> <cmd>
sysctl -w net.ipv4.ip_forward=1                  # temporary!
```

Persistence: `/etc/netplan/*.yaml` -> `sudo netplan try` (auto-rollback) then
`sudo netplan apply`. Sysctls: `/etc/sysctl.d/99-x.conf` -> `sysctl --system`.

---

## iptables

```bash
iptables -S                                      # everything, as commands
iptables -L -n -v --line-numbers                 # with counters
iptables -t nat -S                               # NAT IS A SEPARATE TABLE
iptables -Z                                      # zero counters, then re-test

iptables -A CHAIN ...                            # append (end)
iptables -I CHAIN 1 ...                          # insert at position 1
iptables -D CHAIN 3                              # delete by number
iptables -D CHAIN -p tcp --dport 80 -j DROP      # delete by spec (safer)
iptables -P INPUT DROP                           # default policy
iptables -F / -X                                 # flush / delete chains
```

Chains: `PREROUTING` -> routing -> `INPUT` (to me) / `FORWARD` (through me) ->
`OUTPUT` (from me) -> `POSTROUTING`.

Tables: `filter` (allow/deny), `nat` (DNAT in PREROUTING, SNAT in POSTROUTING),
`mangle` (MSS, marks), `raw` (NOTRACK).

Minimum host firewall:

```bash
iptables -P INPUT DROP; iptables -P FORWARD DROP; iptables -P OUTPUT ACCEPT
iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -m conntrack --ctstate INVALID -j DROP
iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -j ACCEPT
iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 5/s -j ACCEPT
```

Router / NAT:

```bash
sysctl -w net.ipv4.ip_forward=1
iptables -t nat -A POSTROUTING -s 10.10.0.0/16 -o ens18 -j MASQUERADE
iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A FORWARD -i ens19 -o ens18 -j ACCEPT
```

Port forward (remember FORWARD sees the **post-DNAT** address):

```bash
iptables -t nat -A PREROUTING -i ens18 -p tcp --dport 8080 \
         -j DNAT --to-destination 10.10.2.10:80
iptables -A FORWARD -d 10.10.2.10 -p tcp --dport 80 -j ACCEPT
conntrack -F                                     # after ANY nat change
```

Persist: `apt install iptables-persistent` then `netfilter-persistent save`.

Emergency reset (set policies FIRST):

```bash
iptables -P INPUT ACCEPT; iptables -P FORWARD ACCEPT; iptables -P OUTPUT ACCEPT
iptables -t nat -F; iptables -F; iptables -X
```

Remote safety: `netlab snapshot save x` + `netlab deadman 15`, and always test
from a **new** SSH session.

---

## Kubernetes

```bash
kubectl config set-context --current --namespace=netlab

kubectl get pods -o wide / -A / --show-labels / -l app=web
kubectl describe pod <pod>                       # Events at the BOTTOM
kubectl logs <pod> --previous                    # the crashed instance
kubectl get events --sort-by=.lastTimestamp | tail -20
kubectl get endpointslices                       # THE service question

kubectl create deployment web --image=nginx:1.27-alpine --replicas=3
kubectl expose deployment web --port=80
kubectl scale deployment web --replicas=5
kubectl set image deployment/web nginx=nginx:1.27
kubectl edit deployment web
kubectl rollout status|history|undo|restart deployment/web

kubectl exec -it <pod> -- sh
kubectl port-forward svc/web 8080:80
kubectl run tmp --rm -it --restart=Never --image=busybox:1.36 -- sh
kubectl create ... --dry-run=client -o yaml      # generate correct YAML
kubectl explain deployment.spec.strategy         # offline schema docs
```

Status -> cause:

| Status | Cause |
|---|---|
| `Pending` | scheduling: resources, taints, selectors, PVC |
| `ContainerCreating` (stuck) | missing ConfigMap/Secret, volume, CNI |
| `ImagePullBackOff` | image name/tag, registry auth, egress |
| `CrashLoopBackOff` | app exits. `logs --previous`. 137 = OOMKilled |
| `Running 0/1` | readiness probe failing |
| `Evicted` | node disk/memory pressure |

Service debugging:

```
endpoints EMPTY   -> selector mismatch, or pods not Ready
endpoints PRESENT -> DNS, NetworkPolicy, ports, or the app
pod IP works, ClusterIP does not -> Service / kube-proxy
```

Probes: readiness = take traffic (no restart). liveness = kill and restart
(dangerous if wrong). startup = suspends the others while booting.

NetworkPolicy: allow-only, additive. A pod is unrestricted until a policy
selects it, then denies all but the union of allows. Enable egress deny and you
**must** allow DNS to kube-system.

kube-proxy chains: `KUBE-SERVICES` -> `KUBE-SVC-*` (statistic-based load
balancing) -> `KUBE-SEP-*` (DNAT to a pod IP). Load balancing is per
**connection**, not per request.

---

## netlab

```bash
sudo netlab lab up | down | rebuild | map
sudo netlab list [net|fw|k8s]
sudo netlab start <id> / check / hint / solution / reset
sudo netlab challenge net|fw|k8s                 # random undisclosed fault
sudo netlab reveal
sudo netlab status / progress / doctor
sudo netlab exec client|router|server <cmd>
sudo netlab sh client
sudo netlab k8s up | status | reset | iptables
sudo netlab snapshot save|restore|list
sudo netlab deadman 15 / deadman-cancel
netlab guide [00-10|99]
```

Lab addresses: client `10.10.1.10`, router `10.10.1.1` / `10.10.2.1` /
`10.10.0.2`, server `10.10.2.10` (ports 8080, 9090), host `10.10.0.1`.
Server paths: `/health` returns `netlab-ok`, `/big.bin` is 6 MB.
