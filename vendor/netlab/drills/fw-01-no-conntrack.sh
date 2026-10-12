DRILL_TITLE="Default-deny INPUT with no rule for return traffic"
DRILL_MODULE="fw"
DRILL_LEVEL=2
DRILL_TIME="15 min"
DRILL_TOOLS="iptables -L -v, conntrack, tcpdump"
DRILL_BRIEF="Someone hardened the client with a default-deny INPUT policy. Now
NOTHING works from the client -- not ping, not HTTP, not DNS. Yet tcpdump on the
server proves the requests arrive there and the replies are sent back."
DRILL_GOAL="Make http://10.10.2.10:8080/health work from the client again WITHOUT
weakening the policy. The INPUT policy must stay DROP when you are done."

drill_break() {
  nsx client iptables -F
  nsx client iptables -A INPUT -i lo -j ACCEPT
  nsx client iptables -P INPUT DROP
}

drill_verify() {
  nsx client iptables -S INPUT 2>/dev/null | grep -q '^-P INPUT DROP' || {
    warn "The INPUT policy is no longer DROP -- that is not the fix we are after."
    return 1
  }
  t_ping client "$SERVER_IP" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
Look at the direction of travel. Your request LEAVES the client through the
OUTPUT chain, which is still ACCEPT, so it goes out fine. The reply COMES
BACK and hits the INPUT chain, which now drops everything.

  sudo netlab exec client iptables -L -n -v --line-numbers
  sudo netlab exec client iptables -S

Watch it happen: the reply arrives on the wire and the application never
sees it.
  sudo netlab exec client tcpdump -ni eth0 icmp
  sudo netlab exec client ping -c3 10.10.2.10

The whole point of a stateful firewall is that you do not have to write a
rule for every possible reply. You write ONE rule that says "if this packet
belongs to a connection I already allowed out, let it in".

Look up the conntrack match:  man iptables-extensions, search for ctstate.
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec client iptables -L INPUT -n -v --line-numbers
    Chain INPUT (policy DROP 14 packets, 1176 bytes)
    num  pkts bytes target  prot opt in  out  source     destination
    1       0     0 ACCEPT  all  --  lo  *    0.0.0.0/0  0.0.0.0/0

  The policy counter is climbing: packets ARE hitting the default DROP.
  Only loopback is permitted, so every reply from the network is discarded.

Fix -- add the stateful return rule at the top of INPUT:
  sudo netlab exec client iptables -I INPUT 1 \
       -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

  Insert (-I) at position 1, do not append (-A): order matters and you want
  this evaluated before anything else.

Confirm:
  sudo netlab exec client ping -c2 10.10.2.10
  sudo netlab exec client curl -s http://10.10.2.10:8080/health
  sudo netlab exec client iptables -L INPUT -n -v --line-numbers
    (the new rule now carries the packet counts)

This is the canonical minimum host firewall, and it is worth memorising:

  iptables -P INPUT DROP
  iptables -P FORWARD DROP
  iptables -P OUTPUT ACCEPT
  iptables -A INPUT -i lo -j ACCEPT
  iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -A INPUT -m conntrack --ctstate INVALID -j DROP
  iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -j ACCEPT
  iptables -A INPUT -p icmp --icmp-type echo-request -j ACCEPT

Never set the policy to DROP before the lo and ESTABLISHED rules are in
place, and never do it over SSH without a dead-man switch:
  sudo netlab deadman 10        # auto-restores your rules in 10 minutes
S
}

drill_debrief() { cat <<'D'
Two ideas do most of the work in iptables:

1. DIRECTION. INPUT is traffic terminating on this host. OUTPUT is traffic
   originating on it. FORWARD is traffic passing through it. A host that is
   not a router never uses FORWARD; a router uses FORWARD for the traffic
   you actually care about and INPUT only for traffic aimed at the router
   itself. Getting these confused is the single most common iptables error.

2. STATE. Conntrack tracks every flow, so you allow the outbound NEW packet
   and let ESTABLISHED,RELATED cover everything that comes back. RELATED is
   what lets an ICMP error, or an FTP data channel, through without you
   writing a rule for it.

The packet counters in "iptables -L -n -v" are your debugger. Run your test,
run the command again, and see which rule number incremented. A rule with
zero packets is a rule that is never being reached -- either the traffic is
not what you think, or an earlier rule already handled it.
D
}
