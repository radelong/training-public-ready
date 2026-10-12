DRILL_TITLE="Egress filtering blocks one destination"
DRILL_MODULE="fw"
DRILL_LEVEL=3
DRILL_TIME="15 min"
DRILL_TOOLS="iptables OUTPUT chain, tcpdump, ping error text"
DRILL_BRIEF="The client cannot reach the server. tcpdump on the CLIENT interface
shows no packets leaving at all, and ping reports an odd error rather than a
plain timeout. The server and router are both perfectly healthy."
DRILL_GOAL="Restore client access to 10.10.2.10 (ping and HTTP)."

drill_break() {
  fw_flush_ns client
  nsx client iptables -A OUTPUT -d "$SERVER_IP" -j REJECT --reject-with icmp-admin-prohibited
}

drill_verify() {
  t_ping client "$SERVER_IP" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
Everyone checks INPUT. Almost nobody checks OUTPUT. If tcpdump on your own
interface shows nothing leaving, the packet died before it reached the wire
-- which means it died in your own OUTPUT chain.

  sudo netlab exec client tcpdump -ni eth0 icmp     # nothing appears
  sudo netlab exec client iptables -L OUTPUT -n -v --line-numbers
  sudo netlab exec client iptables -S OUTPUT

Read the error text from ping very carefully. It is not a timeout:
  sudo netlab exec client ping -c2 10.10.2.10

The words "Packet filtered" or "Administratively prohibited" are generated
by a firewall telling you, honestly, that it refused.
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec client ping -c2 10.10.2.10
    From 10.10.1.10 icmp_seq=1 Packet filtered
    (a REJECT, not a DROP -- and the source of the rejection is the client
     itself, 10.10.1.10, not some remote device)

  sudo netlab exec client tcpdump -ni eth0 host 10.10.2.10
    (silence: the packets never reach the interface)

  sudo netlab exec client iptables -L OUTPUT -n -v --line-numbers
    num pkts bytes target  prot opt source    destination
    1     4   336 REJECT   all  --  0.0.0.0/0 10.10.2.10  reject-with
                                                          icmp-admin-prohibited

Fix:
  sudo netlab exec client iptables -D OUTPUT -d 10.10.2.10 \
       -j REJECT --reject-with icmp-admin-prohibited

  Or by line number, having checked it first:
  sudo netlab exec client iptables -D OUTPUT 1

Confirm:
  sudo netlab exec client ping -c2 10.10.2.10
  sudo netlab exec client curl -s http://10.10.2.10:8080/health
  sudo netlab exec client iptables -L OUTPUT -n -v
S
}

drill_debrief() { cat <<'D'
Three questions, asked in this order, localise any connectivity fault to a
single machine in about a minute:

  1. Does the packet LEAVE the source?     tcpdump on the source interface
     No  -> the source OUTPUT chain, or routing on the source
  2. Does it ARRIVE at the destination?    tcpdump on the destination
     No  -> something in between: routing, a router FORWARD chain, NAT
  3. Does the REPLY come back?
     No  -> the destination OUTPUT chain, the return route, or an
            asymmetric path

Egress filtering (OUTPUT rules) is genuinely valuable -- it is what stops a
compromised host from calling home or from being used to scan your network.
But it is invisible to everyone who only ever looks at INPUT, so document it
loudly wherever you deploy it.

The reject-with types are worth knowing, because each produces a different
client-side message:
  icmp-port-unreachable   the default; looks like "nothing is listening"
  icmp-host-unreachable   looks like the host is down
  icmp-admin-prohibited   honest: "a policy refused this"
  tcp-reset               TCP only; looks exactly like a closed port
D
}
