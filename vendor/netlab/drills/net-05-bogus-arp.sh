DRILL_TITLE="Stale static ARP entry poisons the gateway"
DRILL_MODULE="net"
DRILL_LEVEL=2
DRILL_TIME="10 min"
DRILL_TOOLS="ip neigh, arping, tcpdump"
DRILL_BRIEF="The client has a correct address, a correct default route, and the
router is healthy and forwarding. Yet every ping to the gateway times out.
Packets are clearly leaving the client -- they just never get an answer."
DRILL_GOAL="Restore reachability from the client to 10.10.1.1 and 10.10.2.10."

drill_break() {
  nsx client ip neigh replace "$ROUTER_LAN_IP" lladdr 00:11:22:33:44:55 \
    dev eth0 nud permanent
}

drill_verify() {
  t_ping client "$ROUTER_LAN_IP" || return 1
  t_ping client "$SERVER_IP" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
Layer 3 looks perfect, so drop to layer 2. To send an IP packet to a
neighbour the kernel must first know its MAC address.

  sudo netlab exec client ip neigh show
  sudo netlab exec router ip -br link show lan0

Compare the MAC the client has cached for 10.10.1.1 against the MAC the
router interface actually has. Pay attention to the state word at the end
of the neigh entry: REACHABLE, STALE, FAILED and PERMANENT mean very
different things.

Watch the frames go out and nothing come back:
  sudo netlab exec router tcpdump -ni lan0 icmp or arp
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec client ip neigh show
    10.10.1.1 dev eth0 lladdr 00:11:22:33:44:55 PERMANENT

  sudo netlab exec router ip -br link show lan0
    lan0  UP  9a:3f:...            <-- a completely different MAC

  The client is addressing its frames to a MAC that does not exist on the
  wire, so nothing ever replies. PERMANENT means the entry will never age
  out or be corrected by ARP.

Fix -- remove the bad entry:
  sudo netlab exec client ip neigh del 10.10.1.1 dev eth0

  or flush the whole table:
  sudo netlab exec client ip neigh flush all

Confirm:
  sudo netlab exec client ping -c2 10.10.1.1
  sudo netlab exec client ip neigh show
    10.10.1.1 dev eth0 lladdr 9a:3f:... REACHABLE

Who really owns that IP on the wire (great for duplicate-IP hunts):
  sudo netlab exec client arping -I eth0 -c3 10.10.1.1
  (sudo apt install iputils-arping)
S
}

drill_debrief() { cat <<'D'
The neighbour table is the layer 2 half of routing, and it is invisible
unless you look. Read the states:

  REACHABLE   confirmed working recently
  STALE       cached but unconfirmed; will be re-validated on next use
  DELAY/PROBE re-validation in progress
  FAILED      ARP was attempted and nobody answered -- the host is gone,
              or a firewall is eating ARP, or the IP is wrong
  PERMANENT   manually pinned; never expires, never self-corrects

"FAILED" on the gateway plus "Host is unreachable" from ping is the classic
signature of a next hop that does not exist. A wrong PERMANENT entry, as
here, is what you get from a stale /etc/ethers, a botched anti-spoofing
script, or genuine ARP spoofing.

Two duplicate-IP tells worth remembering: the neigh entry keeps flipping
between two MACs, and "arping" returns replies from more than one MAC.
D
}
