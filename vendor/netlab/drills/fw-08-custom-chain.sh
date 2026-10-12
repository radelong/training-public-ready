DRILL_TITLE="The rule is hidden in a custom chain"
DRILL_MODULE="fw"
DRILL_LEVEL=3
DRILL_TIME="20 min"
DRILL_TOOLS="iptables -S, custom chains, jump targets"
DRILL_BRIEF="The client cannot reach the web server through the router. The
router FORWARD chain looks completely innocent -- policy ACCEPT, and no DROP
rules anywhere in it. Yet the packets never make it to the DMZ."
DRILL_GOAL="Restore http://10.10.2.10:8080/health from the client without
deleting the LABSEC chain or its jump -- fix only what is wrong inside it."

drill_break() {
  fw_flush_ns router
  nsx router iptables -N LABSEC 2>/dev/null || true
  nsx router iptables -F LABSEC
  nsx router iptables -A LABSEC -p tcp --dport 22 -j DROP
  nsx router iptables -A LABSEC -d "$SERVER_IP" -p tcp --dport 8080 -j DROP
  nsx router iptables -A LABSEC -j RETURN
  nsx router iptables -A FORWARD -j LABSEC
}

drill_verify() {
  nsx router iptables -S 2>/dev/null | grep -q '^-N LABSEC' || {
    warn "The LABSEC chain is gone. Recreate the structure and fix only the bad rule."
    return 1
  }
  nsx router iptables -S FORWARD 2>/dev/null | grep -q -- '-j LABSEC' || {
    warn "The jump from FORWARD to LABSEC is gone. Keep it, fix the rule inside."
    return 1
  }
  t_http client "http://$SERVER_IP:$HTTP_PORT/health" || return 1
  t_ping client "$SERVER_IP"
}

drill_hint() { cat <<'H'
"iptables -L FORWARD" shows you rules in FORWARD. It does not follow jumps
into other chains for you. Use -S, which prints every chain and every rule
as the commands that would recreate them:

  sudo netlab exec router iptables -S

Look for a line starting with -N (a chain being created) and a rule whose
target is neither ACCEPT nor DROP nor REJECT -- that is a jump.

Then list that chain by name, with counters:
  sudo netlab exec router iptables -L LABSEC -n -v --line-numbers

Generate traffic and watch which rule number increments.
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec router iptables -L FORWARD -n -v --line-numbers
    Chain FORWARD (policy ACCEPT)
    num pkts bytes target  prot opt source    destination
    1     9   540 LABSEC   all  --  0.0.0.0/0 0.0.0.0/0
    (no DROP here -- but every packet is sent into LABSEC)

  sudo netlab exec router iptables -S
    -P FORWARD ACCEPT
    -N LABSEC
    -A FORWARD -j LABSEC
    -A LABSEC -p tcp -m tcp --dport 22 -j DROP
    -A LABSEC -d 10.10.2.10/32 -p tcp -m tcp --dport 8080 -j DROP   <-- here
    -A LABSEC -j RETURN

  sudo netlab exec router iptables -L LABSEC -n -v --line-numbers
    num pkts bytes target prot opt source    destination
    1     0     0 DROP   tcp  --  0.0.0.0/0 0.0.0.0/0   tcp dpt:22
    2     6   360 DROP   tcp  --  0.0.0.0/0 10.10.2.10  tcp dpt:8080
    3     0     0 RETURN all  --  0.0.0.0/0 0.0.0.0/0

  Rule 2 is the one with the packet counts.

Fix -- delete only that rule, leaving the chain and the jump intact:
  sudo netlab exec router iptables -D LABSEC -d 10.10.2.10 -p tcp \
       --dport 8080 -j DROP

Confirm:
  sudo netlab exec client curl -s http://10.10.2.10:8080/health
  sudo netlab exec router iptables -L LABSEC -n -v --line-numbers
    (rule for port 22 still there, still doing its job)

Useful custom-chain commands:
  iptables -N NAME          create a chain
  iptables -A FORWARD -j NAME   jump into it
  iptables -A NAME -j RETURN    fall back to the calling chain
  iptables -F NAME          flush its rules
  iptables -X NAME          delete it (must be empty and unreferenced first)
  iptables -E OLD NEW       rename it
S
}

drill_debrief() { cat <<'D'
Custom chains are how real rulesets stay readable: one chain per concern
(SSH-BRUTE, DOCKER-USER, K8S-SERVICES, VPN-IN), jumped into from the
built-in chains. They are also where rules hide from anyone who only ever
runs "iptables -L".

Make "iptables -S" your default listing command. It prints the whole
ruleset, every chain, in the exact syntax you would use to recreate it, so
you can copy a line and put -D in front of it to delete it. "iptables -L"
resolves names via DNS by default (always pass -n), truncates, and hides
structure.

The four targets that behave quite differently:
  ACCEPT  stop traversing THIS table, allow the packet
  DROP    stop everything, discard silently
  REJECT  stop everything, send an error back
  RETURN  stop traversing THIS chain, resume in the caller. In a built-in
          chain, RETURN means "apply the default policy".

Two you will meet on real hosts: LOG and the jump to another chain are
NON-terminating -- traversal continues to the next rule afterwards. That is
why "LOG then DROP" is always two separate rules.

On a real Ubuntu server, this is exactly how ufw, fail2ban, Docker and
kube-proxy all coexist in the same table: each owns its own chains. When
your hand-written rule mysteriously stops working, run "iptables -S" and
find out who else is in there.
D
}
