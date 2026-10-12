DRILL_TITLE="Router drops forwarded traffic"
DRILL_MODULE="fw"
DRILL_LEVEL=2
DRILL_TIME="15 min"
DRILL_TOOLS="iptables FORWARD chain, packet counters"
DRILL_BRIEF="The client can ping the router. The router can ping the server. IP
forwarding is enabled and the routes are correct. But the client cannot reach
the server at all, and the packets vanish inside the router."
DRILL_GOAL="Restore client to server connectivity while keeping the router
default-deny. The FORWARD policy must still be DROP when you are done."

drill_break() {
  fw_flush_ns router
  nsx router iptables -P FORWARD DROP
}

drill_verify() {
  nsx router iptables -S FORWARD 2>/dev/null | grep -q '^-P FORWARD DROP' || {
    warn "The FORWARD policy is no longer DROP -- that is not the fix we want."
    return 1
  }
  t_ping client "$SERVER_IP" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
Traffic that terminates ON the router uses INPUT. Traffic that passes
THROUGH the router uses FORWARD. Your ping to the router works because it
is INPUT. Your ping to the server fails because it is FORWARD.

  sudo netlab exec router iptables -L -n -v
  sudo netlab exec router iptables -S

Watch the policy counter on FORWARD climb while you generate traffic:
  sudo netlab exec client ping -c5 10.10.2.10
  sudo netlab exec router iptables -L FORWARD -n -v

You need two things: permission for the forward direction, and permission
for the traffic that comes back.
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec router sysctl net.ipv4.ip_forward
    net.ipv4.ip_forward = 1          <-- routing itself is fine

  sudo netlab exec router iptables -L FORWARD -n -v
    Chain FORWARD (policy DROP 10 packets, 840 bytes)
    (empty, and the counter grows every time you ping)

Fix -- allow the LAN to reach the DMZ, and allow the replies:
  sudo netlab exec router iptables -A FORWARD \
       -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  sudo netlab exec router iptables -A FORWARD \
       -i lan0 -o dmz0 -s 10.10.1.0/24 -d 10.10.2.0/24 -j ACCEPT

  Note what the second rule does NOT say: there is no rule allowing dmz0 to
  initiate connections to lan0. The DMZ can only answer, never initiate.
  That is exactly how you want a DMZ to behave, and the ESTABLISHED rule is
  what makes it work.

Confirm:
  sudo netlab exec client ping -c2 10.10.2.10
  sudo netlab exec client curl -s http://10.10.2.10:8080/health
  sudo netlab exec router iptables -L FORWARD -n -v --line-numbers

  Prove the asymmetry -- the server cannot start a conversation:
  sudo netlab exec server ping -c2 10.10.1.10        # should fail
S
}

drill_debrief() { cat <<'D'
The -i (input interface) and -o (output interface) matches are what turn a
flat ruleset into a real firewall policy. On a router, "-i lan0 -o dmz0"
expresses a direction of trust, and its absence in the reverse direction is
the actual security control.

Which matches are legal in which chain:
  INPUT     -i only   (the packet is not going anywhere else)
  OUTPUT    -o only   (it was generated locally)
  FORWARD   -i and -o (both are known)
iptables rejects the illegal combinations, which is a useful sanity check
that you are writing a rule in the chain you meant.

A router with a default-deny FORWARD policy needs, at minimum:
  iptables -P FORWARD DROP
  iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -A FORWARD -m conntrack --ctstate INVALID -j DROP
  iptables -A FORWARD -i <inside> -o <outside> -j ACCEPT

Docker note for real machines: Docker inserts its own DOCKER-USER and
DOCKER-ISOLATION chains into FORWARD and will happily fight your hand-written
rules. Put your policy in DOCKER-USER, which Docker jumps to first and never
rewrites.
D
}
