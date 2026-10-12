DRILL_TITLE="Wrong prefix length puts the gateway off-subnet"
DRILL_MODULE="net"
DRILL_LEVEL=2
DRILL_TIME="10 min"
DRILL_TOOLS="ip addr, ipcalc, ip route"
DRILL_BRIEF="Someone edited the client network config by hand. Now the client
cannot even reach its own gateway, and adding a default route fails with
RTNETLINK answers: Network is unreachable."
DRILL_GOAL="Fix the client addressing so it can reach 10.10.1.1 and 10.10.2.10."

drill_break() {
  nsx client ip route del default 2>/dev/null || true
  nsx client ip addr flush dev eth0
  nsx client ip addr add 10.10.1.10/30 dev eth0
  nsx client ip link set eth0 up
}

drill_verify() {
  t_ping client "$ROUTER_LAN_IP" || return 1
  t_ping client "$SERVER_IP" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
Compare what the client believes its local subnet is against where the
gateway actually lives.

  sudo netlab exec client ip -br addr show eth0
  sudo netlab exec client ip route show

A /30 covers only four addresses. Work out which four, then ask whether
10.10.1.1 is one of them. If the gateway is not on a directly connected
subnet, the kernel refuses to install a route via it.

Check what the other end of the cable thinks:
  sudo netlab exec router ip -br addr show lan0
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec client ip -br addr show eth0
    eth0  UP  10.10.1.10/30

  A /30 anchored on 10.10.1.10 spans 10.10.1.8 - 10.10.1.11.
  The gateway 10.10.1.1 is NOT in that range, so there is no connected
  route toward it and the kernel rejects the default route.

  The router side is a /24:
    sudo netlab exec router ip -br addr show lan0
      lan0  UP  10.10.1.1/24

Fix:
  sudo netlab exec client ip addr flush dev eth0
  sudo netlab exec client ip addr add 10.10.1.10/24 dev eth0
  sudo netlab exec client ip route replace default via 10.10.1.1

Confirm:
  sudo netlab exec client ip route get 10.10.2.10
  sudo netlab exec client ping -c2 10.10.1.1
  sudo netlab exec client curl -s http://10.10.2.10:8080/health

Prefix maths worth memorising:
  /24  256 addresses   255.255.255.0
  /25  128             255.255.255.128
  /26   64             255.255.255.192
  /27   32             255.255.255.224
  /28   16             255.255.255.240
  /29    8             255.255.255.248
  /30    4             255.255.255.252   (2 usable, point-to-point)
S
}

drill_debrief() { cat <<'D'
Both ends of a link must agree on the prefix length. A mismatch produces a
maddening one-way or no-way failure that people mistake for a cable fault.

The tell: "ip addr" shows an address, the connected route in "ip route" is
narrower or wider than you expect, and the gateway falls outside it.
"ipcalc 10.10.1.10/30" (sudo apt install ipcalc) prints the range for you.

If you genuinely must route via a gateway that is off-subnet, the keyword
is "onlink":
  ip route add default via 10.10.1.1 dev eth0 onlink
That is legitimate in a few cloud networks and a red flag almost everywhere
else -- it tells the kernel to stop sanity-checking you.
D
}
