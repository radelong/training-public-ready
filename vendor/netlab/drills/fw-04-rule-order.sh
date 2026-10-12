DRILL_TITLE="The ACCEPT rule exists but never fires"
DRILL_MODULE="fw"
DRILL_LEVEL=2
DRILL_TIME="15 min"
DRILL_TOOLS="iptables --line-numbers, -v counters, -I vs -A"
DRILL_BRIEF="A colleague swears they added an ACCEPT rule for port 8080 on the
server, and you can see it in the ruleset. The client still cannot connect.
The colleague is now blaming the network."
DRILL_GOAL="Get http://10.10.2.10:8080/health working from the client, while
leaving the server otherwise protected from the LAN."

drill_break() {
  fw_flush_ns server
  nsx server iptables -A INPUT -i lo -j ACCEPT
  nsx server iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  nsx server iptables -A INPUT -s 10.10.1.0/24 -j DROP
  nsx server iptables -A INPUT -p tcp --dport 8080 -j ACCEPT
  nsx server iptables -A INPUT -p tcp --dport 9090 -j ACCEPT
}

drill_verify() {
  t_http client "http://$SERVER_IP:$HTTP_PORT/health" || return 1
  nsx server iptables -S INPUT 2>/dev/null | grep -q -- '--dport 8080 -j ACCEPT' || {
    warn "The ACCEPT rule for 8080 should still exist -- fix the ordering, do not delete it."
    return 1
  }
  return 0
}

drill_hint() { cat <<'H'
Chains are evaluated top to bottom and the FIRST matching rule with a
terminating target wins. Nothing below it is ever consulted.

Print the chain with numbers and counters:
  sudo netlab exec server iptables -L INPUT -n -v --line-numbers

Now generate traffic and print it again:
  sudo netlab exec client curl --max-time 3 http://10.10.2.10:8080/health
  sudo netlab exec server iptables -L INPUT -n -v --line-numbers

Which rule number incremented? The counters do not lie. If the ACCEPT rule
shows 0 packets, the packet never got that far.

Then look at what sits above it and ask what that earlier rule matches.
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec server iptables -L INPUT -n -v --line-numbers
    num pkts bytes target prot opt source        destination
    1     0    0  ACCEPT all  --  0.0.0.0/0      0.0.0.0/0      (lo)
    2     0    0  ACCEPT all  --  0.0.0.0/0      0.0.0.0/0      ctstate RELATED,ESTABLISHED
    3     8  480  DROP   all  --  10.10.1.0/24   0.0.0.0/0      <-- fires here
    4     0    0  ACCEPT tcp  --  0.0.0.0/0      0.0.0.0/0      tcp dpt:8080
    5     0    0  ACCEPT tcp  --  0.0.0.0/0      0.0.0.0/0      tcp dpt:9090

  Rule 3 drops everything from the client subnet. Rules 4 and 5 are dead
  code -- their counters stay at zero forever.

Fix -- move the specific ACCEPT above the broad DROP. Insert at position 3:
  sudo netlab exec server iptables -I INPUT 3 -p tcp --dport 8080 -j ACCEPT

  Then remove the now-duplicated rule further down (renumber first):
  sudo netlab exec server iptables -L INPUT -n --line-numbers
  sudo netlab exec server iptables -D INPUT 5

Confirm:
  sudo netlab exec client curl -s http://10.10.2.10:8080/health
  sudo netlab exec server iptables -L INPUT -n -v --line-numbers
    (rule 3 now carries the packets, and the DROP still protects the rest)

  Prove the DROP is still doing its job:
  sudo netlab exec client ping -c2 10.10.2.10          # still blocked

An alternative, and often the better habit, is to rebuild the chain
atomically instead of surgically editing it:
  sudo netlab exec server iptables-save > /tmp/rules.v4
  # edit /tmp/rules.v4 into the order you want
  sudo netlab exec server iptables-restore < /tmp/rules.v4
iptables-restore replaces the entire table in one atomic operation, so
there is never a moment where the box is half-configured.
S
}

drill_debrief() { cat <<'D'
Two habits prevent this class of bug entirely:

  -A appends to the END of the chain. It is what you want when you are
     building a ruleset from scratch, top to bottom.
  -I inserts at position 1 (or at the number you give). It is what you want
     when you are adding an exception to an existing policy.

Reaching for -A when the chain already ends in a broad DROP is how the dead
rule is created. When someone says "I added the rule and it did not work",
they used -A.

The general ordering principle: most specific first, broadest last.
  1. loopback
  2. ESTABLISHED,RELATED
  3. specific allows (ports, sources)
  4. specific denies
  5. the default policy, or a final catch-all LOG + DROP

Add a logging rule just above the final drop while you are debugging:
  iptables -A INPUT -m limit --limit 5/min -j LOG --log-prefix "IPT-DROP: "
Then watch it:  sudo journalctl -kf | grep IPT-DROP
The --limit match matters -- an unlimited LOG rule on a busy host will fill
the disk.
D
}
