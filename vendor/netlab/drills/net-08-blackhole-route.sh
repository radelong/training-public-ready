DRILL_TITLE="A more-specific route swallows the traffic"
DRILL_MODULE="net"
DRILL_LEVEL=3
DRILL_TIME="10 min"
DRILL_TOOLS="ip route get, ip route show, tcpdump"
DRILL_BRIEF="The client has a valid address and a valid default route via
10.10.1.1. It can reach the gateway. But traffic to the 10.10.2.0/24 network
fails instantly, and tcpdump on the router sees nothing at all arrive."
DRILL_GOAL="Restore reachability from the client to 10.10.2.10 without removing
the default route."

drill_break() {
  nsx client ip route replace blackhole 10.10.2.0/24
}

drill_verify() {
  nsx client ip route show 2>/dev/null | grep -q "blackhole" && return 1
  t_ping client "$SERVER_IP" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
The packets are dying on the client itself -- the router never sees them.
Prove it:
  sudo netlab exec router tcpdump -ni lan0 icmp
  sudo netlab exec client ping -c3 10.10.2.10      # nothing appears above

So the client is making a forwarding decision you did not expect. Do not
read the table by eye, ask the kernel:
  sudo netlab exec client ip route get 10.10.2.10

Then look at the whole table and think about longest-prefix match. A
default route (/0) is the LEAST specific route there is; anything more
specific beats it.
  sudo netlab exec client ip route show
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec client ip route get 10.10.2.10
    RTNETLINK answers: Invalid argument
    (or: "blackhole 10.10.2.10 ...")

  sudo netlab exec client ip route show
    blackhole 10.10.2.0/24                 <-- discard route, more specific
    default via 10.10.1.1 dev eth0            than the default, so it wins
    10.10.1.0/24 dev eth0 proto kernel scope link src 10.10.1.10

  Routing is longest-prefix-match: /24 beats /0 every time. The default
  route was never even considered.

Fix:
  sudo netlab exec client ip route del blackhole 10.10.2.0/24

  If "del blackhole" is refused, delete by prefix:
  sudo netlab exec client ip route del 10.10.2.0/24

Confirm:
  sudo netlab exec client ip route get 10.10.2.10
    10.10.2.10 via 10.10.1.1 dev eth0 src 10.10.1.10
  sudo netlab exec client curl -s http://10.10.2.10:8080/health

The three discard route types, worth recognising in a table:
  blackhole   drop silently
  unreachable reply with ICMP host unreachable / EHOSTUNREACH
  prohibit    reply with ICMP admin prohibited / EACCES
S
}

drill_debrief() { cat <<'D'
Longest-prefix match is the rule that decides everything: the kernel picks
the route with the most specific (longest) matching prefix, and the metric
only breaks ties between routes of equal length. A single stray /32 or /24
will quietly override a perfectly correct default route.

This is a very common production failure, though usually not as a literal
blackhole. The realistic versions are:
  - a VPN client that pushed 10.0.0.0/8 into your table and never cleaned up
  - Docker claiming 172.17.0.0/16 that collides with a corporate subnet
  - a routing daemon leaking a summary route
  - a leftover /32 host route from a failover script

Always run "ip route get <dst>" first. It answers the only question that
matters -- what will the kernel actually do with this packet -- and it takes
policy routing rules ("ip rule show", multiple tables) into account too,
which reading "ip route show" by eye does not.
D
}
