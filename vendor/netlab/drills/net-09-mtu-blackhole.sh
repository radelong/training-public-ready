DRILL_TITLE="MTU mismatch: small requests work, large transfers hang"
DRILL_MODULE="net"
DRILL_LEVEL=4
DRILL_TIME="20 min"
DRILL_TOOLS="ping -M do -s, ip link mtu, tcpdump, tracepath"
DRILL_BRIEF="Ping works. Small HTTP requests work instantly. But downloading a
large file from the server hangs after the first few kilobytes and eventually
times out. SSH connects, then freezes the moment output gets long. Classic."
DRILL_GOAL="Make this complete within a few seconds:
  netlab exec client curl -s -o /dev/null http://10.10.2.10:8080/big.bin"

drill_break() {
  nsx router ip link set dmz0 mtu 1400
}

drill_verify() {
  t_http client "http://$SERVER_IP:$HTTP_PORT/health" 4 || return 1
  t_bigfile client "http://$SERVER_IP:$HTTP_PORT/big.bin"
}

drill_hint() { cat <<'H'
Small things work, big things do not. That is the signature of a path MTU
problem, and it is almost never a firewall.

Find the largest packet that survives the path. -M do sets the do-not-
fragment bit, so the packet either arrives whole or dies:
  sudo netlab exec client ping -c2 -M do -s 1472 10.10.2.10   # 1500 total
  sudo netlab exec client ping -c2 -M do -s 1372 10.10.2.10   # 1400 total

Add 28 to the -s value to get the full frame size (20 IP + 8 ICMP).

Then compare the MTU of every interface along the path:
  sudo netlab exec client ip -br link show
  sudo netlab exec router ip -br link show
  sudo netlab exec server ip -br link show

And watch the download die:
  sudo netlab exec router tcpdump -ni dmz0 -c 20 tcp port 8080
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec client curl -s -o /dev/null --max-time 8 \
       http://10.10.2.10:8080/health          # instant, fine
  sudo netlab exec client curl -s -o /dev/null --max-time 8 \
       http://10.10.2.10:8080/big.bin         # hangs, then times out

  Binary-search the path MTU:
  sudo netlab exec client ping -c2 -M do -s 1472 10.10.2.10
    ping: local error: message too long / 100% loss
  sudo netlab exec client ping -c2 -M do -s 1372 10.10.2.10
    2 received                                <-- 1400 gets through

  Now find the narrow link:
  sudo netlab exec router ip -br link show
    lan0  UP  ... mtu 1500
    dmz0  UP  ... mtu 1400                    <-- here it is
  sudo netlab exec server ip -br link show
    eth0  UP  ... mtu 1500

  The server sends full 1500-byte segments toward the router. They arrive
  at a 1400-MTU interface and are dropped on ingress, and no ICMP is
  generated for that, so the sender never learns. The TCP connection
  establishes (small packets) and then stalls (large packets). This is a
  path MTU black hole.

Fix -- option A, make the MTU consistent (the correct fix here):
  sudo netlab exec router ip link set dmz0 mtu 1500

Fix -- option B, clamp TCP MSS on the router (what you do when you cannot
control the narrow link, e.g. behind a VPN or PPPoE):
  sudo netlab exec router iptables -t mangle -A FORWARD -p tcp --syn \
       -j TCPMSS --clamp-mss-to-pmtu

  This rewrites the MSS option in the SYN so both ends agree to send
  smaller segments. It only helps TCP -- UDP and ESP still need a real fix.

Confirm:
  sudo netlab exec client curl -s -o /dev/null -w '%{time_total}\n' \
       http://10.10.2.10:8080/big.bin
  sudo netlab exec client tracepath 10.10.2.10        # prints pmtu per hop
S
}

drill_debrief() { cat <<'D'
Remember the symptom pattern, because it recurs constantly with VPNs,
VXLAN/overlay networks, PPPoE and cloud tunnels:

  ping works                     small packets fit
  DNS works                      small packets fit
  short web pages work           small packets fit
  large downloads hang           large packets are silently dropped
  SSH connects then freezes      the first long output line is large

Numbers to know:
  1500   standard Ethernet MTU
  1492   PPPoE (8 bytes of overhead)
  1450   typical VXLAN / WireGuard payload
  1420   common IPsec figure
  9000   jumbo frames -- must be set on EVERY device in the path

Path MTU Discovery is supposed to fix this automatically: a router that
cannot forward a DF packet returns ICMP type 3 code 4 "fragmentation
needed". If a firewall blocks all ICMP, PMTUD breaks and you get exactly
this black hole. That is the single best reason never to blanket-drop ICMP:
  iptables -A INPUT -p icmp --icmp-type fragmentation-needed -j ACCEPT

"tracepath <host>" prints the discovered MTU per hop and needs no root.
D
}
