DRILL_TITLE="One service port is blocked, everything else is fine"
DRILL_MODULE="fw"
DRILL_LEVEL=1
DRILL_TIME="10 min"
DRILL_TOOLS="iptables -S, ss -ltnp, curl -v, nc"
DRILL_BRIEF="The monitoring system says the web server is down. But the host
pings fine, and the same server answers perfectly on port 9090. Only port 8080
hangs -- it does not refuse, it hangs."
DRILL_GOAL="Make http://10.10.2.10:8080/health work from the client again."

drill_break() {
  fw_flush_ns server
  nsx server iptables -A INPUT -p tcp --dport 8080 -j DROP
}

drill_verify() {
  t_http client "http://$SERVER_IP:$HTTP_PORT/health" || return 1
  t_http client "http://$SERVER_IP:$ALT_PORT/health"
}

drill_hint() { cat <<'H'
Prove the service is actually listening before you blame the application:
  sudo netlab exec server ss -ltnp
  sudo netlab exec server curl -s http://127.0.0.1:8080/health

If it answers on loopback but not from outside, the process is healthy and
something between the wire and the socket is eating the packets.

Note the symptom carefully. A HANG means the packet was silently discarded
(DROP). A "connection refused" would mean nothing was listening. The
difference tells you where to look.

  sudo netlab exec server iptables -S
  sudo netlab exec server iptables -L INPUT -n -v --line-numbers
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec server ss -ltnp
    LISTEN 0 5 0.0.0.0:8080  0.0.0.0:*  users:(("python3",pid=...))
    LISTEN 0 5 0.0.0.0:9090  0.0.0.0:*
    (the service is up and bound to all addresses)

  sudo netlab exec server curl -s http://127.0.0.1:8080/health
    netlab-ok                    <-- works locally, so it is not the app

  sudo netlab exec client curl -v --max-time 4 http://10.10.2.10:8080/health
    * Connection timed out       <-- hang, not refusal: something DROPs it

  sudo netlab exec server iptables -L INPUT -n -v --line-numbers
    num  pkts bytes target prot opt in out source    destination
    1       6   360 DROP   tcp  --  *  *  0.0.0.0/0 0.0.0.0/0  tcp dpt:8080

Fix -- delete the rule. Either by number:
  sudo netlab exec server iptables -D INPUT 1
or, safer in a script because it cannot delete the wrong line:
  sudo netlab exec server iptables -D INPUT -p tcp --dport 8080 -j DROP

Confirm:
  sudo netlab exec client curl -s http://10.10.2.10:8080/health
  sudo netlab exec server iptables -L INPUT -n -v

Deleting by line number is a classic production accident: the numbers shift
every time a rule is removed, so a loop that deletes 1, 2, 3 removes the
wrong rules. Delete by specification, or delete from the highest number
downwards.
S
}

drill_debrief() { cat <<'D'
The "is it the app, the host firewall, or the network?" question has a
fixed three-step answer, and doing it in this order saves hours:

  1. On the server:  ss -ltnp          is anything listening, and on which
                                       address? 127.0.0.1:8080 only serves
                                       localhost -- that alone explains many
                                       "firewall" tickets.
  2. On the server:  curl localhost    does the app answer itself?
  3. From the client: curl -v          hang or refused?

DROP versus REJECT, and why you care:
  DROP    silence. The client waits for its full TCP timeout, retries, and
          waits again. Users report "the site is slow" or "it hangs".
  REJECT  an immediate ICMP port-unreachable or TCP RST. The client fails
          in milliseconds with "Connection refused".

Use REJECT on internal networks so your own systems fail fast and honestly.
Use DROP on internet-facing interfaces where you do not want to confirm to a
scanner that the host exists.
D
}
