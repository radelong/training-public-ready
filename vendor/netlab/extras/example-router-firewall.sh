#!/usr/bin/env bash
# A NAT gateway / router ruleset. Set WAN and LAN to your real interfaces.
set -euo pipefail

WAN="${WAN:-ens18}"
LAN="${LAN:-ens19}"
LAN_NET="${LAN_NET:-10.10.0.0/16}"

sysctl -qw net.ipv4.ip_forward=1

iptables -F; iptables -X
iptables -t nat -F; iptables -t nat -X

iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT ACCEPT

iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -m conntrack --ctstate INVALID -j DROP
iptables -A INPUT -i "$LAN" -p tcp --dport 22 -j ACCEPT
iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 5/s -j ACCEPT
iptables -A INPUT -p icmp --icmp-type destination-unreachable -j ACCEPT

# forwarding: inside may start conversations, outside may only answer
iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A FORWARD -m conntrack --ctstate INVALID -j DROP
iptables -A FORWARD -i "$LAN" -o "$WAN" -s "$LAN_NET" -j ACCEPT

# source NAT on the way out
iptables -t nat -A POSTROUTING -s "$LAN_NET" -o "$WAN" -j MASQUERADE

# clamp TCP MSS if the uplink is a tunnel (PPPoE, WireGuard, IPsec)
# iptables -t mangle -A FORWARD -o "$WAN" -p tcp --syn -j TCPMSS --clamp-mss-to-pmtu

# port forward example: public 8080 -> internal 10.10.2.10:80
# NOTE the FORWARD rule matches the POST-DNAT address.
# iptables -t nat -A PREROUTING -i "$WAN" -p tcp --dport 8080 \
#          -j DNAT --to-destination 10.10.2.10:80
# iptables -A FORWARD -i "$WAN" -o "$LAN" -d 10.10.2.10 -p tcp --dport 80 \
#          -m conntrack --ctstate NEW -j ACCEPT

echo "Applied. Persist ip_forward in /etc/sysctl.d/99-router.conf and run 'sudo sysctl --system'."
