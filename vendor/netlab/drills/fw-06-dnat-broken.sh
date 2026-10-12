DRILL_TITLE="Port forward sends traffic to the wrong place"
DRILL_MODULE="fw"
DRILL_LEVEL=4
DRILL_TIME="20 min"
DRILL_TOOLS="iptables -t nat, conntrack, tcpdump"
DRILL_BRIEF="The router is supposed to publish the DMZ web server on its own LAN
address: clients hit http://10.10.1.1:8080/ and the router forwards them to
10.10.2.10:8080. Someone set up the DNAT rule, but connections just hang.
Going directly to http://10.10.2.10:8080/ still works fine."
DRILL_GOAL="Make this work from the client:
  netlab exec client curl -s http://10.10.1.1:8080/health"

drill_break() {
  fw_flush_ns router
  nsx router iptables -t nat -A PREROUTING -i lan0 -p tcp --dport 8080 \
    -j DNAT --to-destination 10.10.2.99:8080
}

drill_verify() {
  t_http client "http://$ROUTER_LAN_IP:$HTTP_PORT/health" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
DNAT lives in the nat table, PREROUTING chain. "iptables -L" will not show
it -- you must ask for the table by name.

  sudo netlab exec router iptables -t nat -L PREROUTING -n -v --line-numbers
  sudo netlab exec router iptables -t nat -S

Then watch where the rewritten packet actually goes:
  sudo netlab exec router tcpdump -ni dmz0 tcp port 8080
  sudo netlab exec client curl --max-time 4 http://10.10.1.1:8080/health

Look at the destination address on the packets leaving dmz0. Is that the
address of the server? Compare with:
  sudo netlab exec server ip -br addr show

Conntrack will show you the translation the kernel believes in:
  sudo netlab exec router conntrack -L -p tcp 2>/dev/null | grep 8080
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec router iptables -t nat -L PREROUTING -n -v --line-numbers
    num pkts bytes target prot opt in    out source    destination
    1     3   180 DNAT   tcp  --  lan0  *   0.0.0.0/0 0.0.0.0/0  tcp dpt:8080
                                                      to:10.10.2.99:8080

  sudo netlab exec server ip -br addr show eth0
    eth0  UP  10.10.2.10/24            <-- the server is .10, not .99

  sudo netlab exec router tcpdump -ni dmz0 tcp port 8080
    IP 10.10.1.10.51234 > 10.10.2.99.8080: Flags [S]
    (rewritten to an address where nothing exists, so it hangs)

Fix -- replace the rule with the correct destination:
  sudo netlab exec router iptables -t nat -D PREROUTING -i lan0 -p tcp \
       --dport 8080 -j DNAT --to-destination 10.10.2.99:8080
  sudo netlab exec router iptables -t nat -A PREROUTING -i lan0 -p tcp \
       --dport 8080 -j DNAT --to-destination 10.10.2.10:8080

  Existing conntrack entries still hold the old translation, so flush them
  or you will chase a ghost for ten minutes:
  sudo netlab exec router conntrack -F 2>/dev/null || true

Confirm:
  sudo netlab exec client curl -s http://10.10.1.1:8080/health
    netlab-ok
  sudo netlab exec router conntrack -L -p tcp | grep 8080
    tcp 6 ... src=10.10.1.10 dst=10.10.1.1 sport=... dport=8080
              src=10.10.2.10 dst=10.10.1.10 sport=8080 dport=...
    (the second line is the reply tuple -- that is the translation)

The three things a working port forward needs:
  1. nat/PREROUTING DNAT     rewrite the destination on the way in
  2. filter/FORWARD ACCEPT   permit the forwarded flow (default ACCEPT here;
                             on a hardened router you must add it, and note
                             that FORWARD sees the POST-DNAT address:
                             -d 10.10.2.10 --dport 8080, not -d 10.10.1.1)
  3. a return path            the server must route replies back via the
                             router. If it does not, add a matching
                             nat/POSTROUTING MASQUERADE (hairpin NAT).
S
}

drill_debrief() { cat <<'D'
Where NAT happens relative to everything else is the thing to internalise:

  wire -> raw/PREROUTING -> conntrack -> nat/PREROUTING (DNAT)
       -> ROUTING DECISION
       -> filter/FORWARD -> nat/POSTROUTING (SNAT/MASQUERADE) -> wire

Consequences you will trip over:
  - DNAT happens BEFORE the routing decision, which is what allows the
    packet to be redirected to another host at all.
  - filter/FORWARD sees the packet AFTER DNAT, so your FORWARD rules must
    match the internal address, not the public one. Almost everyone writes
    this rule wrong once.
  - SNAT happens after routing, in POSTROUTING, which is why it can use the
    outgoing interface address.
  - The nat table is consulted only for the FIRST packet of a connection.
    Everything after that is handled by conntrack, which is why changing a
    NAT rule appears to do nothing until you flush conntrack.

"conntrack -L" and "conntrack -F" (sudo apt install conntrack) are the two
commands that turn NAT from guesswork into observation.
D
}
