DRILL_TITLE="Lab hosts lost internet access (missing MASQUERADE)"
DRILL_MODULE="net"
DRILL_LEVEL=3
DRILL_TIME="15 min"
DRILL_TOOLS="iptables -t nat, conntrack, tcpdump"
DRILL_BRIEF="Everything inside the lab still works: client to router, client to
server, HTTP between them. But nothing in the lab can reach the internet any
more. The VM itself has internet. This drill touches the REAL host firewall
(the nat table only) -- read the solution if you are nervous."
DRILL_GOAL="Restore outbound internet for the lab subnets by putting source NAT
back on the host. Verify with: netlab exec client ping -c2 1.1.1.1"

_wan() { host_default_iface; }

_host_online() {
  local w; w="$(_wan)"
  [ -n "$w" ] || return 1
  ping -c1 -W2 -q 1.1.1.1 >/dev/null 2>&1
}

drill_break() {
  topo_uplink_off
}

drill_reset() {
  topo_repair
  topo_uplink_on >/dev/null 2>&1
}

drill_verify() {
  local w; w="$(_wan)"
  if [ -z "$w" ]; then
    warn "This VM has no default route, so there is no internet to test."
    warn "Checking only that the NAT rule has been recreated."
    iptables -t nat -S POSTROUTING 2>/dev/null | grep -q "MASQUERADE" || return 1
    return 0
  fi
  iptables -t nat -C POSTROUTING -s "$LAB_SUPERNET" -o "$w" -j MASQUERADE 2>/dev/null || return 1
  if _host_online; then
    t_ping client 1.1.1.1 2 || return 1
  else
    warn "The VM itself cannot reach 1.1.1.1, so the end-to-end test is skipped."
  fi
  return 0
}

drill_hint() { cat <<'H'
The lab uses RFC1918 addresses (10.10.0.0/16). The internet has no route
back to them. Something on the host has to rewrite the source address of
outbound packets to the host address -- and remember the translation so
replies can be un-rewritten.

Prove the packets get to the host and die there:
  sudo netlab exec client ping -c3 1.1.1.1          # in one terminal
  sudo tcpdump -ni nl-up-h icmp                     # arriving at the host
  sudo tcpdump -ni <your-real-nic> icmp             # leaving? with what src?

Look at the table that does address rewriting, not the filter table:
  sudo iptables -t nat -S
  sudo iptables -t nat -L POSTROUTING -n -v

Find your real uplink interface with:
  ip route show default
H
}

drill_solution() { cat <<'S'
Diagnose:
  ip route show default
    default via 192.0.2.1 dev ens18 ...      <-- WAN interface is ens18

  sudo iptables -t nat -S POSTROUTING
    -P POSTROUTING ACCEPT                      <-- no MASQUERADE rule at all

  sudo tcpdump -ni ens18 icmp
    IP 10.10.1.10 > 1.1.1.1: ICMP echo request
    (a private source address is going out of the WAN -- it will never
     be answered, and most ISPs drop it outright)

Fix -- add source NAT on the way out, plus forwarding permission:
  WAN=$(ip route show default | awk '{print $5; exit}')
  sudo iptables -t nat -A POSTROUTING -s 10.10.0.0/16 -o "$WAN" -j MASQUERADE
  sudo iptables -I FORWARD 1 -s 10.10.0.0/16 -j ACCEPT
  sudo iptables -I FORWARD 1 -d 10.10.0.0/16 -j ACCEPT
  sudo sysctl -w net.ipv4.ip_forward=1

Confirm:
  sudo netlab exec client ping -c2 1.1.1.1
  sudo tcpdump -ni "$WAN" icmp
    IP <host-ip> > 1.1.1.1: ICMP echo request     <-- now correctly rewritten
  sudo conntrack -L -p icmp | head
    (shows the translation the kernel is remembering)

MASQUERADE vs SNAT:
  MASQUERADE   picks the outgoing interface address automatically. Use it
               when the WAN address is dynamic (DHCP, PPPoE). Slightly more
               expensive, and it drops conntrack entries when the link
               bounces.
  SNAT         --to-source 203.0.113.5, fixed. Use it when the address is
               static: it is faster and survives link flaps.

Persisting rules on Ubuntu:
  sudo apt install iptables-persistent      # saves on install
  sudo netfilter-persistent save            # save current rules
  # rules land in /etc/iptables/rules.v4
S
}

drill_debrief() { cat <<'D'
NAT lives in the nat table, not the filter table -- "iptables -L" shows you
nothing about it. Get in the habit of always naming the table: "-t nat",
"-t mangle", or the default "-t filter".

Two things must both be true for a Linux NAT gateway to work:
  1. net.ipv4.ip_forward = 1 (routing is enabled)
  2. a POSTROUTING MASQUERADE or SNAT rule for the internal subnet
plus, if your FORWARD policy is DROP, explicit FORWARD rules to permit the
traffic in both directions.

NAT only needs a rule for the FIRST packet of a flow. Conntrack handles the
rest, which is why the nat table is only traversed for NEW connections.
"sudo conntrack -L" (apt install conntrack) shows every translation the
kernel is currently tracking, and is the fastest way to prove NAT is or is
not happening.
D
}
