# 05 - iptables cookbook

Copy-paste recipes for real situations. Try them inside the lab namespaces
first:

```bash
sudo netlab exec router iptables -S
sudo netlab sh router          # then just run iptables normally
```

---

## Inspect

```bash
sudo iptables -S                            # everything, as commands
sudo iptables -S INPUT                      # one chain
sudo iptables -L -n -v --line-numbers       # counters + numbers
sudo iptables -t nat -S
sudo iptables -t mangle -S
sudo iptables -Z                            # zero counters, then re-test
sudo iptables-save                          # full dump, all tables
```

Find which rule is eating your traffic:

```bash
sudo iptables -Z                            # zero
# ... reproduce the problem ...
sudo iptables -L -n -v --line-numbers | awk '$1+0 > 0'
```

---

## Basic allow / deny

```bash
# allow a port
iptables -A INPUT -p tcp --dport 443 -m conntrack --ctstate NEW -j ACCEPT

# allow several ports at once
iptables -A INPUT -p tcp -m multiport --dports 80,443,8080 -j ACCEPT

# allow a port range
iptables -A INPUT -p tcp --dport 30000:32767 -j ACCEPT

# allow from one network only
iptables -A INPUT -p tcp --dport 22 -s 10.0.0.0/8 -j ACCEPT

# allow from several sources
iptables -A INPUT -p tcp --dport 22 -m iprange --src-range 10.0.0.5-10.0.0.20 -j ACCEPT

# block a host entirely
iptables -I INPUT 1 -s 203.0.113.66 -j DROP

# block everything except one network (note the negation)
iptables -A INPUT -p tcp --dport 5432 ! -s 10.0.0.0/8 -j REJECT

# allow an interface wholesale
iptables -A INPUT -i wg0 -j ACCEPT

# comment your rules -- do this
iptables -A INPUT -p tcp --dport 9090 -m comment --comment "metrics scraper" -j ACCEPT
```

---

## The standard host firewall

```bash
#!/usr/bin/env bash
set -e

iptables -F; iptables -X
iptables -t nat -F; iptables -t nat -X
iptables -t mangle -F; iptables -t mangle -X

iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT ACCEPT

iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -m conntrack --ctstate INVALID -j DROP

iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 5/s -j ACCEPT
iptables -A INPUT -p icmp --icmp-type destination-unreachable -j ACCEPT
iptables -A INPUT -p icmp --icmp-type time-exceeded -j ACCEPT

iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW -j ACCEPT
iptables -A INPUT -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW -j ACCEPT

iptables -A INPUT -m limit --limit 5/min -j LOG --log-prefix "IPT-DROP-IN: "
```

---

## Router / gateway

```bash
WAN=ens18
LAN=ens19
LAN_NET=10.10.0.0/16

sysctl -w net.ipv4.ip_forward=1

iptables -P FORWARD DROP
iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A FORWARD -m conntrack --ctstate INVALID -j DROP

# inside may reach outside; outside may only answer
iptables -A FORWARD -i "$LAN" -o "$WAN" -s "$LAN_NET" -j ACCEPT

# source NAT on the way out
iptables -t nat -A POSTROUTING -s "$LAN_NET" -o "$WAN" -j MASQUERADE
```

`MASQUERADE` picks the outgoing interface's address automatically - use it when
the WAN address is dynamic. `SNAT --to-source 203.0.113.5` is faster and
survives link flaps - use it when the address is static.

```bash
iptables -t nat -A POSTROUTING -s "$LAN_NET" -o "$WAN" -j SNAT --to-source 203.0.113.5
```

---

## Port forwarding (DNAT)

Publish an internal service on a public port:

```bash
WAN=ens18
iptables -t nat -A PREROUTING -i "$WAN" -p tcp --dport 8080 \
         -j DNAT --to-destination 10.10.2.10:80

# FORWARD sees the POST-DNAT address -- this is the rule people get wrong
iptables -A FORWARD -i "$WAN" -o ens19 -p tcp -d 10.10.2.10 --dport 80 \
         -m conntrack --ctstate NEW -j ACCEPT
```

Three things must all be true: the DNAT rule, a FORWARD permit matching the
**internal** address, and a return path (the target must route replies back
through this router).

If the target does *not* route back through the router, add hairpin SNAT so it
replies to the router instead of directly:

```bash
iptables -t nat -A POSTROUTING -p tcp -d 10.10.2.10 --dport 80 \
         -s 10.10.0.0/16 -j MASQUERADE
```

Redirect a local port (useful for transparent proxies):

```bash
iptables -t nat -A PREROUTING -i ens19 -p tcp --dport 80 -j REDIRECT --to-port 3128
```

After changing any NAT rule:

```bash
sudo conntrack -F        # existing flows still use the OLD translation
```

---

## Rate limiting and brute-force protection

```bash
# simple rate limit
iptables -A INPUT -p tcp --dport 80 -m limit --limit 100/s --limit-burst 200 -j ACCEPT

# SSH brute force: 4 new connections per source per minute, then drop
iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW \
         -m recent --set --name SSH
iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW \
         -m recent --update --seconds 60 --hitcount 5 --name SSH \
         -j LOG --log-prefix "SSH-BRUTE: "
iptables -A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW \
         -m recent --update --seconds 60 --hitcount 5 --name SSH -j DROP

# limit concurrent connections per source
iptables -A INPUT -p tcp --dport 443 -m connlimit --connlimit-above 50 -j REJECT

# SYN flood mitigation
iptables -A INPUT -p tcp --syn -m limit --limit 25/s --limit-burst 50 -j ACCEPT
iptables -A INPUT -p tcp --syn -j DROP
```

For anything serious, use `fail2ban` rather than hand-rolling this - it manages
its own chains and handles unbanning.

---

## Logging

```bash
# log then drop -- always two rules, LOG does not terminate
iptables -A INPUT -m limit --limit 5/min -j LOG --log-prefix "IPT-DROP: " --log-level 4
iptables -A INPUT -j DROP

# log a specific flow while debugging
iptables -I INPUT 1 -s 10.10.1.10 -j LOG --log-prefix "DEBUG-CLIENT: "

# watch
sudo journalctl -kf | grep IPT-
sudo dmesg -w | grep IPT-
```

Always rate-limit LOG rules. Remove debug rules when you finish.

---

## MSS clamping (VPN / PPPoE / tunnels)

When you cannot control the narrow link, make TCP negotiate smaller segments:

```bash
iptables -t mangle -A FORWARD -p tcp --syn -j TCPMSS --clamp-mss-to-pmtu

# or a fixed value when PMTU discovery itself is unreliable
iptables -t mangle -A FORWARD -o wg0 -p tcp --syn -j TCPMSS --set-mss 1360
```

This only helps TCP. UDP and ESP still need a real MTU fix.

---

## Custom chains for structure

```bash
iptables -N WEB
iptables -A WEB -p tcp --dport 80 -j ACCEPT
iptables -A WEB -p tcp --dport 443 -j ACCEPT
iptables -A WEB -j RETURN
iptables -A INPUT -i ens18 -j WEB

iptables -N BLOCKLIST
iptables -A BLOCKLIST -s 203.0.113.0/24 -j DROP
iptables -A BLOCKLIST -s 198.51.100.0/24 -j DROP
iptables -I INPUT 1 -j BLOCKLIST
```

For large blocklists use `ipset`, which is O(1) instead of one rule per entry:

```bash
sudo apt install ipset
sudo ipset create badguys hash:net
sudo ipset add badguys 203.0.113.0/24
sudo iptables -I INPUT 1 -m set --match-set badguys src -j DROP
sudo ipset list badguys
```

---

## Save, restore, persist

```bash
sudo iptables-save > /etc/iptables/rules.v4
sudo iptables-restore < /etc/iptables/rules.v4      # ATOMIC full replace
sudo iptables-restore -n < extra.v4                 # -n = do not flush first
```

`iptables-restore` replaces the entire table in one atomic operation, so there
is never a moment where the box is half-configured. **Editing a saved file and
restoring it is safer than surgically editing a live chain**, and it is how you
should make any non-trivial change.

Persist across reboots on Ubuntu:

```bash
sudo apt install iptables-persistent      # prompts to save current rules
sudo netfilter-persistent save            # save now
sudo netfilter-persistent reload
# files: /etc/iptables/rules.v4 and rules.v6
```

---

## Emergency reset

Flush everything and allow all traffic - the "I have locked myself out" button,
for use on the console:

```bash
iptables -P INPUT ACCEPT
iptables -P FORWARD ACCEPT
iptables -P OUTPUT ACCEPT
iptables -t nat -F
iptables -t mangle -F
iptables -F
iptables -X
```

Set the policies **first**. If you flush the rules while the policy is DROP, you
disconnect yourself instantly.

---

## IPv6

`iptables` handles IPv4 only. IPv6 needs `ip6tables`, with the same syntax.

```bash
sudo ip6tables -S
sudo ip6tables -P INPUT DROP
sudo ip6tables -A INPUT -i lo -j ACCEPT
sudo ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# ICMPv6 is MANDATORY -- without these the address never even comes up
sudo ip6tables -A INPUT -p ipv6-icmp -j ACCEPT
```

A firewall that secures IPv4 and leaves IPv6 wide open is a real and common
finding. Check both, every time.

---

## Quick reference of things people forget

```bash
iptables -t nat -L -n -v            # NAT is a SEPARATE table
conntrack -F                        # after any NAT change
iptables -S                         # shows custom chains; -L hides structure
iptables -I not -A                  # when adding an exception above a DROP
-n                                  # always, or DNS lookups will hang you
-m comment --comment "why"          # your future self is a different person
ip6tables                           # IPv4 rules do nothing for IPv6
```
