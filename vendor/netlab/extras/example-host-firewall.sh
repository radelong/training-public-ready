#!/usr/bin/env bash
# A reasonable default-deny firewall for a single Ubuntu server.
# READ IT BEFORE RUNNING IT. Edit the SSH_PORT and ALLOW_* values first.
#
# Safe way to try this on a remote box:
#   sudo netlab snapshot save before-fw
#   sudo netlab deadman 15
#   sudo ./example-host-firewall.sh
#   ssh user@host 'echo still-alive'      # from a NEW session
#   sudo netlab deadman-cancel
set -euo pipefail

SSH_PORT=22
ALLOW_TCP="80,443"
ADMIN_NET="10.0.0.0/8"        # source allowed to reach SSH; use 0.0.0.0/0 to open it

iptables -F; iptables -X
iptables -t nat -F; iptables -t nat -X
iptables -t mangle -F; iptables -t mangle -X

iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT ACCEPT

# loopback and return traffic -- these MUST come before anything else
iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -m conntrack --ctstate INVALID -j DROP

# ICMP: rate-limit echo, but never blanket-drop (PMTU discovery needs type 3/4)
iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 5/s -j ACCEPT
iptables -A INPUT -p icmp --icmp-type destination-unreachable -j ACCEPT
iptables -A INPUT -p icmp --icmp-type time-exceeded -j ACCEPT

# services
iptables -A INPUT -p tcp --dport "$SSH_PORT" -s "$ADMIN_NET" \
         -m conntrack --ctstate NEW -j ACCEPT -m comment --comment "ssh from admin net"
iptables -A INPUT -p tcp -m multiport --dports "$ALLOW_TCP" \
         -m conntrack --ctstate NEW -j ACCEPT -m comment --comment "public web"

# see what you are dropping (rate-limited so it cannot fill the disk)
iptables -A INPUT -m limit --limit 5/min -j LOG --log-prefix "IPT-DROP-IN: "

echo "Applied. Review with:  sudo iptables -L -n -v --line-numbers"
echo "Persist with:          sudo apt install iptables-persistent && sudo netfilter-persistent save"
