# 10 - Kubernetes networking, and the iptables underneath it

This guide joins the two halves of the lab. Everything you learned about
routing and iptables is what Kubernetes Services are actually built from.

---

## The four networks

A cluster has several address spaces that must not overlap:

| Network | Example (k3s default) | What lives there |
|---|---|---|
| Node network | `192.0.2.0/24` | the VM's real address |
| Pod network | `10.42.0.0/16` | one IP per pod, routable cluster-wide |
| Service network | `10.43.0.0/16` | **virtual** IPs. Nothing owns them. |
| Cluster DNS | `10.43.0.10` | a Service IP, so it is virtual too |

```bash
kubectl get nodes -o wide                                  # node IPs
kubectl -n netlab get pods -o wide                         # pod IPs
kubectl -n netlab get svc                                  # service IPs
ip route show | grep 10.42                                 # pod routes on the host
```

The rules of the model:

1. Every pod gets its own IP.
2. Every pod can reach every other pod **without NAT**.
3. Nodes can reach all pods without NAT.
4. **Service IPs do not exist on any interface.** No process binds them and no
   ARP answers for them. They only exist as iptables DNAT rules.

That fourth point is the one that surprises people. You cannot `ping` a
ClusterIP meaningfully, and `tcpdump` will never show you a packet whose
destination is still a Service IP after the first hop.

---

## What kube-proxy does

kube-proxy watches the API server for Services and EndpointSlices and writes
iptables rules. That is the whole implementation. There is no proxy process in
the data path in iptables mode.

Look at it in the lab:

```bash
sudo netlab k8s iptables
```

or by hand:

```bash
sudo iptables -t nat -L PREROUTING -n --line-numbers
sudo iptables -t nat -S KUBE-SERVICES | head -20
sudo iptables -t nat -S | grep KUBE-SVC- | head
sudo iptables -t nat -S | grep KUBE-SEP- | head
```

### The chain structure

```
nat/PREROUTING  -> KUBE-SERVICES
nat/OUTPUT      -> KUBE-SERVICES        (for traffic from the node itself)

KUBE-SERVICES
   |-- match ClusterIP + port  -> KUBE-SVC-<hash>
   |-- fall through            -> KUBE-NODEPORTS   (destination is a node IP)

KUBE-SVC-<hash>          one chain per Service = the load balancer
   |-- -m statistic --mode random --probability 0.333  -> KUBE-SEP-<a>
   |-- -m statistic --mode random --probability 0.500  -> KUBE-SEP-<b>
   |--                                                 -> KUBE-SEP-<c>

KUBE-SEP-<hash>          one chain per endpoint
   |-- -j KUBE-MARK-MASQ           (mark for SNAT if needed)
   |-- -j DNAT --to-destination 10.42.0.23:80
```

### Reading the load balancing

With three endpoints you see `0.333`, then `0.5`, then no probability. That is
not a bug - the probabilities are **conditional**, evaluated in order:

- 1/3 of traffic takes the first rule
- of the remaining 2/3, half takes the second = 1/3
- the rest falls to the third = 1/3

Watch it change:

```bash
kubectl -n netlab scale deployment edge --replicas=4
sudo iptables -t nat -S | grep KUBE-SVC- -A5
```

### Consequences that matter operationally

- **Load balancing is per-CONNECTION, not per-request.** A keep-alive HTTP
  client, and especially gRPC or HTTP/2, pins to one pod for the life of the
  connection. This is the well-known reason gRPC does not spread load across
  pods without an L7 proxy or client-side balancing.
- **Rule count grows as services x endpoints.** At a few thousand services the
  linear traversal becomes measurable, which is why IPVS mode and, more
  recently, nftables mode exist.
- **It is all conntrack-based DNAT.** So `conntrack -L` and `conntrack -F` are
  as useful in a cluster as on a NAT gateway.
- `iptables-save | grep KUBE` is a legitimate and fast way to answer "is
  kube-proxy actually programming this Service?"

Which mode is in use:

```bash
kubectl -n kube-system logs -l k8s-app=kube-proxy 2>/dev/null | grep -i proxier
sudo journalctl -u k3s | grep -i proxier          # k3s embeds kube-proxy
```

---

## Following a packet

### Pod to Service, same node

```
pod A (10.42.0.11) sends to 10.43.120.44:80
   -> leaves the pod's veth into the host namespace
   -> nat/PREROUTING -> KUBE-SERVICES
   -> matches the ClusterIP -> KUBE-SVC-xxx
   -> random pick -> KUBE-SEP-yyy
   -> DNAT to 10.42.0.23:80
   -> routing decision: 10.42.0.23 is on this node's bridge
   -> delivered to pod B
   -> reply is un-DNAT-ed by conntrack, so pod A sees it as from 10.43.120.44
```

### External to NodePort

```
client -> node-ip:30080
   -> nat/PREROUTING -> KUBE-SERVICES -> KUBE-NODEPORTS
   -> matches nodePort 30080 -> KUBE-SVC-xxx -> KUBE-SEP-yyy
   -> KUBE-MARK-MASQ marks it (so the reply returns via this node)
   -> DNAT to a pod IP, possibly on ANOTHER node
   -> nat/POSTROUTING SNATs it to the node IP
   -> pod replies to the node, which un-NATs and returns to the client
```

That SNAT is why the pod sees the **node's** IP as the source, not the real
client's. To preserve the client IP:

```yaml
spec:
  externalTrafficPolicy: Local    # only send to pods on THIS node, no SNAT
```

The trade-off: nodes with no local pod will refuse the connection, so your
external load balancer must health-check the NodePort.

Prove it in the lab:

```bash
sudo conntrack -L -p tcp --dport 30080 | head
```

Drill: `k8s-10-nodeport-iptables`.

---

## Cluster DNS

CoreDNS runs as a normal Deployment, exposed by a Service at `10.43.0.10`,
which is itself just more iptables DNAT rules.

```bash
kubectl -n kube-system get pods -l k8s-app=kube-dns
kubectl -n kube-system get svc kube-dns
kubectl -n netlab exec toolbox -- cat /etc/resolv.conf
kubectl -n netlab exec toolbox -- nslookup web.netlab.svc.cluster.local
```

A pod's resolv.conf:

```
nameserver 10.43.0.10
search netlab.svc.cluster.local svc.cluster.local cluster.local
options ndots:5
```

`ndots:5` means any name with fewer than five dots is tried against every
search domain **before** being tried as-is. So `web` becomes four queries and
`api.example.com` becomes four failed queries before the right one. Ending a
name with a dot (`api.example.com.`) skips the search list, which is a real
latency fix in DNS-heavy applications.

Name forms:

```
web                                  same namespace
web.netlab                           explicit namespace
web.netlab.svc.cluster.local         fully qualified
10-42-0-23.netlab.pod.cluster.local  a pod, by IP-derived name
```

---

## NetworkPolicy

This is the Kubernetes equivalent of iptables rules, expressed against pod
labels rather than IP addresses. The CNI plugin translates it into real rules -
on k3s that means kube-router writes them, and you can see them.

### The semantics, which are easy to get wrong

- Policies are **allow-only**. There is no deny rule.
- A pod is **not isolated** until some policy selects it. Before that,
  everything is permitted.
- As soon as **any** policy selects a pod for a direction, that pod denies
  everything in that direction except what some policy allows.
- Multiple policies are **OR-ed**. So you never edit a deny - you add an allow.
- Ingress and Egress are isolated independently.
- Policy applies to the **pod**, not the Service. Traffic to a ClusterIP is
  DNAT-ed to a pod IP before policy is evaluated, so you write rules about pods
  and ports, never Service names.

### Default-deny for a namespace

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: netlab
spec:
  podSelector: {}          # {} = every pod in the namespace
  policyTypes: ["Ingress"]
```

### Then allow what you need

```yaml
spec:
  podSelector:
    matchLabels: { app: api }
  policyTypes: ["Ingress"]
  ingress:
    - from:
        - podSelector:
            matchLabels: { app: frontend }
      ports:
        - { protocol: TCP, port: 8080 }
```

### The AND / OR trap

```yaml
# AND -- pods labelled role=frontend IN namespaces labelled env=prod
  - from:
      - namespaceSelector:
          matchLabels: { env: prod }
        podSelector:
          matchLabels: { role: frontend }

# OR -- any pod in those namespaces, OR any pod with that label locally
  - from:
      - namespaceSelector:
          matchLabels: { env: prod }
      - podSelector:
          matchLabels: { role: frontend }
```

The difference is a single YAML dash. It is the most common NetworkPolicy bug.

### If you enable default-deny egress, allow DNS

```yaml
  egress:
    - to:
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: kube-system }
          podSelector:
            matchLabels: { k8s-app: kube-dns }
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }
```

Forgetting this breaks every name lookup in the namespace, and it looks like a
CoreDNS outage rather than a policy mistake.

### Enforcement is the CNI's job

You can apply a perfectly valid NetworkPolicy to a cluster whose CNI ignores
policy, and get **no error and no enforcement**. Always verify with a real
connection test:

```bash
kubectl -n netlab exec toolbox -- wget -qO- -T3 http://secure
```

Drill: `k8s-09-networkpolicy`.

---

## Debugging cluster networking

```bash
# does the Service have backends?
kubectl -n netlab get endpointslices -l kubernetes.io/service-name=web

# does the pod IP work directly? (bypasses Service + kube-proxy)
kubectl -n netlab get pods -o wide
kubectl -n netlab exec toolbox -- wget -qO- http://10.42.0.23:80

# does DNS resolve?
kubectl -n netlab exec toolbox -- nslookup web

# is a policy in the way?
kubectl -n netlab get netpol

# what did kube-proxy write?
sudo iptables -t nat -S | grep -i <service-name>
sudo netlab k8s iptables

# live translations
sudo conntrack -L -p tcp | grep 10.43

# a shell with real tools
kubectl -n netlab run netshoot --rm -it --image=nicolaka/netshoot -- bash
```

The decisive test is **pod IP versus Service IP**:

- Pod IP works, Service IP does not -> Service definition or kube-proxy.
- Both fail -> the application, or a NetworkPolicy.
- Both work from inside, neither from outside -> Service type, Ingress, or the
  host firewall.

---

## Ingress, briefly

A Service of type `LoadBalancer` per application does not scale. An Ingress
controller (Traefik, nginx-ingress) is a reverse proxy running in the cluster
that routes HTTP by hostname and path to many Services behind one entry point.

```bash
kubectl get ingressclass
kubectl -n netlab get ingress
kubectl -n netlab describe ingress <name>
```

Note that this lab installs k3s with `--disable traefik`, so there is no
Ingress controller here by default - the drills use ClusterIP and NodePort,
which is where the interesting iptables behaviour lives anyway.
