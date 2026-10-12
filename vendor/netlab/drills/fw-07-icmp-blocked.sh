DRILL_TITLE="Ping fails but the service is perfectly healthy"
DRILL_MODULE="fw"
DRILL_LEVEL=1
DRILL_TIME="10 min"
DRILL_TOOLS="iptables icmp matches, curl, ss"
DRILL_BRIEF="Monitoring has paged you: the server is unreachable, ping gets 100%
loss. Users, however, are not complaining, and the web application is serving
traffic normally. Someone hardened the server overnight."
DRILL_GOAL="Make the server answer ping again, without breaking HTTP."

drill_break() {
  fw_flush_ns server
  nsx server iptables -A INPUT -p icmp -j DROP
}

drill_verify() {
  t_ping client "$SERVER_IP" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health" || return 1
  t_http client "http://$SERVER_IP:$ALT_PORT/health"
}

drill_hint() { cat <<'H'
Before you touch anything, decide whether there is actually an outage. Test
the thing users care about:
  sudo netlab exec client curl -s http://10.10.2.10:8080/health
  sudo netlab exec client curl -s http://10.10.2.10:9090/health

If those work, the service is fine and only ICMP is affected.

  sudo netlab exec server iptables -L INPUT -n -v --line-numbers

Blanket-dropping ICMP is a bad idea for reasons beyond ping. Think about
what ICMP type 3 code 4 does for TCP, and what you learned in
net-09-mtu-blackhole.
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec client curl -s http://10.10.2.10:8080/health
    netlab-ok                          <-- no user-facing outage at all

  sudo netlab exec server iptables -L INPUT -n -v --line-numbers
    num pkts bytes target prot opt source    destination
    1     6   504 DROP   icmp --  0.0.0.0/0 0.0.0.0/0

Fix -- remove the blanket drop:
  sudo netlab exec server iptables -D INPUT -p icmp -j DROP

If policy requires ICMP to be restricted rather than open, replace it with a
selective ruleset instead of a blanket drop:
  sudo netlab exec server iptables -A INPUT -p icmp --icmp-type echo-request \
       -m limit --limit 5/second -j ACCEPT
  sudo netlab exec server iptables -A INPUT -p icmp --icmp-type echo-reply -j ACCEPT
  sudo netlab exec server iptables -A INPUT -p icmp --icmp-type destination-unreachable -j ACCEPT
  sudo netlab exec server iptables -A INPUT -p icmp --icmp-type time-exceeded -j ACCEPT
  sudo netlab exec server iptables -A INPUT -p icmp -j DROP

Confirm:
  sudo netlab exec client ping -c2 10.10.2.10
  sudo netlab exec client curl -s http://10.10.2.10:8080/health
S
}

drill_debrief() { cat <<'D'
Two lessons, and the second one is the important one.

First: ping is not a health check. It tells you a host answers ICMP echo,
nothing more. A box can ping perfectly while its disk is full and its
application is dead, and it can serve millions of requests while dropping
every ping. Monitor the service, on its real port, with a real request.

Second: never blanket-drop ICMP. Specific types are load-bearing parts of
IP, not optional extras:

  type 3 code 4  fragmentation-needed. Drop this and Path MTU Discovery
                 breaks, giving you exactly the black hole from
                 net-09-mtu-blackhole: small packets fine, large ones hang.
                 This is the big one.
  type 3         destination-unreachable generally: lets connections fail
                 fast instead of hanging for 2 minutes.
  type 11        time-exceeded: traceroute and loop detection.
  type 8 / 0     echo request/reply: ping. Rate-limit rather than drop.

The defensible hardening posture is rate-limiting echo-request, not
discarding ICMP wholesale. Note also that ICMPv6 is far more essential --
dropping it breaks neighbour discovery and the address never comes up at
all. For IPv6 use ip6tables and permit ND (types 133-136) explicitly.
D
}
