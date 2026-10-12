DRILL_TITLE="Client interface is administratively down"
DRILL_MODULE="net"
DRILL_LEVEL=1
DRILL_TIME="5 min"
DRILL_TOOLS="ip link, ip -br addr"
DRILL_BRIEF="A user reports the client has no network at all. It cannot reach
the gateway, the server, or anything else."
DRILL_GOAL="Bring the client back online so it can reach 10.10.2.10 and fetch
http://10.10.2.10:8080/health."

drill_break() {
  nsx client ip link set eth0 down
}

drill_verify() {
  nsx client ip -br link show eth0 2>/dev/null | grep -qw UP || return 1
  t_ping client "$ROUTER_LAN_IP" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
Work bottom-up through the layers. Layer 1/2 before layer 3.

  sudo netlab exec client ip -br link show
  sudo netlab exec client ip -br addr show

Look at the state column. An interface can hold a perfectly valid IP
address and still be completely dead.

Two different DOWNs are worth telling apart:
  state DOWN            link is not up (admin down, or peer is down)
  state LOWERLAYERDOWN  admin up but no carrier from the other end
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec client ip -br link show
    eth0   DOWN   ...              <-- interface is down
  sudo netlab exec client ip -br addr show
    eth0   DOWN   10.10.1.10/24    <-- address present, link is not up

Fix:
  sudo netlab exec client ip link set eth0 up

Confirm:
  sudo netlab exec client ip -br link show eth0
  sudo netlab exec client ping -c2 10.10.1.1
  sudo netlab exec client curl -s http://10.10.2.10:8080/health

On a real Ubuntu box the persistent equivalent lives in netplan
(/etc/netplan/*.yaml, then "sudo netplan apply"). An "ip link set up"
lasts only until reboot.
S
}

drill_debrief() { cat <<'D'
An interface has two independent states: ADMIN (did someone run
"ip link set X up"?) and OPERATIONAL (is there carrier?). "ip -br link"
shows both at a glance, which is why it is the first command on any
"no network" ticket.

Triage order that never wastes time:
  1. ip -br link   is the interface up?
  2. ip -br addr   does it have the address you expect?
  3. ip route      does it know where to send packets?
  4. ping gateway  is layer 2 to the next hop working?
  5. ping / curl the actual destination
D
}
