DRILL_TITLE="Default route is missing"
DRILL_MODULE="net"
DRILL_LEVEL=1
DRILL_TIME="5 min"
DRILL_TOOLS="ip route, ip route get"
DRILL_BRIEF="The client can ping its own gateway 10.10.1.1 but cannot reach
anything beyond its own subnet. Attempts fail instantly, not after a timeout."
DRILL_GOAL="Restore reachability from the client to 10.10.2.10."

drill_break() {
  nsx client ip route del default 2>/dev/null || true
}

drill_verify() {
  t_ping client "$SERVER_IP" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
The error message is the clue. Run it and read it carefully:

  sudo netlab exec client ping -c1 10.10.2.10

"Network is unreachable" means the kernel had NO route to try, so it never
put a packet on the wire. That is very different from a timeout, which
means the packet left and nothing came back.

Ask the kernel which route it would actually pick:
  sudo netlab exec client ip route get 10.10.2.10
  sudo netlab exec client ip route show
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec client ip route show
    10.10.1.0/24 dev eth0 proto kernel scope link src 10.10.1.10
    (there is no "default" line)

  sudo netlab exec client ip route get 10.10.2.10
    RTNETLINK answers: Network is unreachable

Fix (runtime):
  sudo netlab exec client ip route add default via 10.10.1.1 dev eth0

  In scripts prefer "ip route replace" -- it succeeds whether or not the
  route already exists, so it is idempotent.

Confirm:
  sudo netlab exec client ip route get 10.10.2.10
    10.10.2.10 via 10.10.1.1 dev eth0 src 10.10.1.10
  sudo netlab exec client ping -c2 10.10.2.10

Persistent equivalent on Ubuntu, /etc/netplan/01-lab.yaml:
  network:
    version: 2
    ethernets:
      ens18:
        addresses: [10.10.1.10/24]
        routes:
          - to: default
            via: 10.10.1.1

  sudo netplan try      # applies with an automatic rollback after 120s
  sudo netplan apply    # commits permanently
S
}

drill_debrief() { cat <<'D'
"ip route get <dst>" is the most useful routing command there is: it makes
the kernel run its real forwarding decision and report the exact route,
source address and output interface it chose. Use it instead of reading the
routing table by eye.

Learn the three distinct failure signatures:
  Network is unreachable   no matching route at all
  Host is unreachable      route exists, ARP for the next hop failed
  timeout / 100% loss      packet left, nothing came back (firewall,
                           asymmetric routing, or the far end is down)

Always run "netplan try" rather than "netplan apply" on a remote box. If
your change kills your own SSH session, netplan rolls it back for you.
D
}
