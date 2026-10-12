DRILL_TITLE="Expose a Deployment on a NodePort and trace it into iptables"
DRILL_MODULE="k8s"
DRILL_LEVEL=4
DRILL_TIME="25 min"
DRILL_TOOLS="kubectl expose, iptables -t nat, conntrack"
DRILL_BRIEF="This drill joins the two halves of the course. The 'edge'
Deployment is running but has no Service. You will publish it on a fixed
NodePort, reach it from the VM itself, and then find the exact iptables rules
kube-proxy wrote to make that work."
DRILL_GOAL="Create a Service named 'edge' of type NodePort, port 80, nodePort
30080, selecting the edge pods. Success = curl http://127.0.0.1:30080/ from the
VM returns the nginx page."

drill_reset() { k8s_clean_workloads; }

drill_break() {
  k8s_clean_workloads
  kn delete svc edge --ignore-not-found >/dev/null 2>&1
  kube apply -f "$K8S_MANIFESTS/10-edge.yaml" >/dev/null 2>&1
  kn rollout status deployment/edge --timeout=150s >/dev/null 2>&1
}

drill_verify() {
  local np
  np="$(kn get svc edge -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null)"
  [ "$np" = "30080" ] || { warn "Service 'edge' does not expose nodePort 30080 (got: ${np:-none})."; return 1; }
  k_svc_has_endpoints edge || { warn "Service 'edge' has no endpoints."; return 1; }
  k_wait 20 bash -c 'curl -s -o /dev/null --max-time 4 http://127.0.0.1:30080/'
}

drill_hint() { cat <<'H'
Create the Service:
  kubectl -n netlab expose deployment edge --type=NodePort --port=80 \
    --target-port=80 --name=edge

That gives you a RANDOM nodePort. To pin it to 30080 you must patch it or
write the YAML yourself:
  kubectl -n netlab patch svc edge \
    -p '{"spec":{"ports":[{"port":80,"targetPort":80,"nodePort":30080}]}}'

  kubectl -n netlab get svc edge

Test from the VM itself, not from inside a pod -- a NodePort is reachable on
every node address:
  curl -s http://127.0.0.1:30080/ | head -5

Then go and find the machinery:
  sudo iptables -t nat -L KUBE-NODEPORTS -n
  sudo netlab k8s iptables
H
}

drill_solution() { cat <<'S'
Create it (declarative is easier when you need a fixed nodePort):
  kubectl apply -f /opt/netlab/k8s/manifests/solutions/10-nodeport.yaml

Or imperatively, in two steps:
  kubectl -n netlab expose deployment edge --type=NodePort --port=80 \
    --target-port=80 --name=edge
  kubectl -n netlab patch svc edge \
    -p '{"spec":{"ports":[{"port":80,"targetPort":80,"nodePort":30080}]}}'

Confirm:
  kubectl -n netlab get svc edge
    NAME  TYPE      CLUSTER-IP     PORT(S)        AGE
    edge  NodePort  10.43.120.44   80:30080/TCP   20s
  curl -s http://127.0.0.1:30080/ | head -5

Now trace the packet. This is the payoff for the fw-* drills.

1. The entry point. Every NAT-table PREROUTING packet is sent to
   KUBE-SERVICES, and non-local destinations fall through to KUBE-NODEPORTS:
     sudo iptables -t nat -L PREROUTING -n --line-numbers
     sudo iptables -t nat -S KUBE-NODEPORTS | grep 30080

2. The per-service chain. It matches your nodePort and jumps to a KUBE-SVC-*
   chain, which is the load balancer:
     sudo iptables -t nat -S | grep -i 'dpt:30080\|--dport 30080'
     sudo iptables -t nat -S KUBE-SVC-XXXXXXXX

   With 2 endpoints you will see statistical matching -- this IS the load
   balancing algorithm, implemented as probability:
     -m statistic --mode random --probability 0.50000000000 -j KUBE-SEP-AAA
     -j KUBE-SEP-BBB

3. The per-endpoint chain does the actual DNAT to one pod IP:
     sudo iptables -t nat -S KUBE-SEP-AAAAAAAA
     -A KUBE-SEP-AAAAAAAA -p tcp -j DNAT --to-destination 10.42.0.23:80

4. Watch a live translation:
     sudo conntrack -L -p tcp --dport 30080 2>/dev/null | head
     (src=your-ip dst=node-ip dport=30080 ... reply src=10.42.0.23 sport=80)

5. See the whole picture with the helper:
     sudo netlab k8s iptables

Now compare the endpoint count to the rules:
  kubectl -n netlab scale deployment edge --replicas=4
  sudo iptables -t nat -S KUBE-SVC-XXXXXXXX      # probabilities changed
S
}

drill_debrief() { cat <<'D'
Everything you learned about iptables is what makes Kubernetes Services
work. There is no magic layer -- kube-proxy watches the API for Services and
EndpointSlices and writes DNAT rules.

The chain structure, in the order a packet meets it:
  KUBE-SERVICES     entry point from nat/PREROUTING and nat/OUTPUT
  KUBE-NODEPORTS    matched when the destination is a node IP, not a
                    ClusterIP
  KUBE-SVC-<hash>   one chain per Service. Contains the load-balancing:
                    -m statistic --mode random --probability, evaluated in
                    order, so the probabilities are conditional (with 3
                    endpoints: 0.333, then 0.5 of the rest, then the last).
  KUBE-SEP-<hash>   one chain per endpoint. Does the DNAT to a pod IP.
  KUBE-MARK-MASQ    marks packets that also need SNAT on the way out, so
                    replies come back through the node that DNAT-ed them.

Consequences that matter operationally:
  - Load balancing is per-CONNECTION, not per-request. A keep-alive HTTP
    client pins to one pod for the life of the connection. This is why gRPC
    and HTTP/2 clients famously do not spread load across pods without a
    proper L7 proxy or client-side balancing.
  - Rule count grows with services multiplied by endpoints. At a few
    thousand services the linear iptables traversal becomes measurable,
    which is the reason IPVS mode and, more recently, nftables mode exist.
  - Because it is all conntrack-based DNAT, "conntrack -L" and
    "conntrack -F" are as useful in a cluster as they are on a NAT gateway.
  - "iptables-save | grep KUBE" is a legitimate, and sometimes the fastest,
    way to answer "is kube-proxy actually programming this Service?"

Check which mode your cluster uses:
  kubectl -n kube-system logs -l k8s-app=kube-proxy 2>/dev/null | grep -i proxier
  (k3s embeds kube-proxy in the agent, so look at: journalctl -u k3s | grep -i proxier)
D
}
