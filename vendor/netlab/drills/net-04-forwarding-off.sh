DRILL_TITLE="Router is not forwarding packets"
DRILL_MODULE="net"
DRILL_LEVEL=2
DRILL_TIME="10 min"
DRILL_TOOLS="sysctl, tcpdump, ip route"
DRILL_BRIEF="After a reboot the client can ping the router (10.10.1.1) and the
server can ping the router (10.10.2.1), but the client cannot reach the server.
Both hosts have correct addresses and default routes. Nothing is firewalled."
DRILL_GOAL="Make the client able to reach 10.10.2.10 again."

drill_break() {
  nsx router sysctl -qw net.ipv4.ip_forward=0
}

drill_verify() {
  nsx router cat /proc/sys/net/ipv4/ip_forward 2>/dev/null | grep -qx 1 || return 1
  t_ping client "$SERVER_IP" || return 1
  t_http client "http://$SERVER_IP:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
Both ends are healthy, so stop looking at them and look at the box in the
middle. A Linux machine is a host by default, not a router.

Prove where the packets die. In one terminal:
  sudo netlab exec router tcpdump -ni lan0 icmp
In another:
  sudo netlab exec client ping -c3 10.10.2.10

If you see the echo requests arrive on lan0 but nothing appears on dmz0,
the router received them and chose not to pass them along.

  sudo netlab exec router tcpdump -ni dmz0 icmp

One kernel setting decides that.
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec router sysctl net.ipv4.ip_forward
    net.ipv4.ip_forward = 0        <-- the router is refusing to route

  Confirm with tcpdump that traffic arrives and is never re-emitted:
    sudo netlab exec router tcpdump -ni lan0 icmp     # requests appear
    sudo netlab exec router tcpdump -ni dmz0 icmp     # nothing appears

Fix (runtime):
  sudo netlab exec router sysctl -w net.ipv4.ip_forward=1

Confirm:
  sudo netlab exec client ping -c2 10.10.2.10
  sudo netlab exec client curl -s http://10.10.2.10:8080/health

Persistent on a real Ubuntu router -- create /etc/sysctl.d/99-router.conf:
  net.ipv4.ip_forward = 1
  net.ipv6.conf.all.forwarding = 1
then:
  sudo sysctl --system        # reload every sysctl.d file
  sysctl net.ipv4.ip_forward  # verify

Note that "sysctl -w" alone does NOT survive a reboot. That is exactly how
this fault appears in the real world: it worked until someone rebooted.
S
}

drill_debrief() { cat <<'D'
ip_forward is the single switch that turns a Linux host into a router. It
is off by default, and setting it with "sysctl -w" is temporary. Anything
that must survive reboot belongs in /etc/sysctl.d/.

Two related knobs you will meet:
  net.ipv4.conf.all.rp_filter    reverse path filtering. Set to 1 it drops
                                 packets arriving on an interface the
                                 kernel would not use to reply. It is the
                                 usual cause of asymmetric-routing drops.
  net.ipv6.conf.all.forwarding   the IPv6 equivalent; forgetting it gives
                                 you a router that forwards v4 only.

Diagnostic habit worth building: tcpdump on the ingress interface, then on
the egress interface. Where the packet stops appearing is where the problem
lives. That single technique resolves most "it goes in but never comes out"
tickets.
D
}
