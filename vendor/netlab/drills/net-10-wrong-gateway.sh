DRILL_TITLE="Default route points at a gateway that does not exist"
DRILL_MODULE="net"
DRILL_LEVEL=2
DRILL_TIME="10 min"
DRILL_TOOLS="ip route get, ip neigh, ping"
DRILL_BRIEF="The client has an address and a default route, and its interface is
up. Pings to anything off-subnet fail with Host is unreachable rather than the
Network is unreachable you would get with no route at all."
DRILL_GOAL="Restore reachability from the client to 10.10.2.10."

drill_break() {
  nsx client ip route replace default via 10.10.1.99
}

drill_verify() {
  t_ping client "$SERVER_IP" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
"Host is unreachable" is a different animal from "Network is unreachable".
It means the kernel HAD a route, picked a next hop, and then could not
resolve that next hop to a MAC address.

  sudo netlab exec client ip route get 10.10.2.10     # which next hop?
  sudo netlab exec client ip neigh show               # did ARP succeed?

An entry in state FAILED means nobody answered the ARP request.

Now check whether that next hop is the address the router actually holds:
  sudo netlab exec router ip -br addr show lan0
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec client ping -c1 10.10.2.10
    From 10.10.1.10 icmp_seq=1 Destination Host Unreachable

  sudo netlab exec client ip route get 10.10.2.10
    10.10.2.10 via 10.10.1.99 dev eth0 src 10.10.1.10   <-- .99, not .1

  sudo netlab exec client ip neigh show
    10.10.1.99 dev eth0  FAILED             <-- ARP got no reply

  sudo netlab exec router ip -br addr show lan0
    lan0  UP  10.10.1.1/24                  <-- the real gateway is .1

Fix:
  sudo netlab exec client ip route replace default via 10.10.1.1 dev eth0

Confirm:
  sudo netlab exec client ip route get 10.10.2.10
  sudo netlab exec client ip neigh show      # 10.10.1.1 ... REACHABLE
  sudo netlab exec client curl -s http://10.10.2.10:8080/health

On a real host, check where the wrong value came from before you "fix" it,
or DHCP or netplan will put it straight back:
  ip route show                     # is the route proto dhcp or proto static?
  grep -r gateway /etc/netplan/
  resolvectl status                 # DHCP-supplied settings per link
S
}

drill_debrief() { cat <<'D'
The exact wording of a failure narrows the problem enormously. Learn these
by heart:

  Network is unreachable          no route matched at all (no default route)
  Destination Host Unreachable    route matched, ARP for the next hop failed
  Destination Port Unreachable    host answered, nothing is listening (UDP)
  Connection refused              host answered, nothing listening (TCP)
  100% packet loss, no message    packet left, silence -- firewall DROP,
                                  asymmetric return path, or host is down
  Connection timed out            same as above, at the TCP layer

Note the last two. A DROP rule produces silence and a timeout, while a
REJECT rule produces an immediate "refused" or "prohibited" message. When a
user says "it hangs" versus "it fails immediately", they have already told
you which one they hit.
D
}
