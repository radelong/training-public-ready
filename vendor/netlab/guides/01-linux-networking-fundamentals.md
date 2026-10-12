# 01 - Linux networking fundamentals

The mental model you need before any of the tooling makes sense.

---

## The layers, and which command belongs to which

| Layer | What it does | Failure looks like | Your tools |
|---|---|---|---|
| 1/2 Link | frames on a wire, MAC addresses | `state DOWN`, `NO-CARRIER` | `ip link`, `ethtool` |
| 2 Neighbour | IP to MAC (ARP / NDP) | `Host is unreachable`, `FAILED` neigh | `ip neigh`, `arping` |
| 3 Network | IP addressing and routing | `Network is unreachable` | `ip addr`, `ip route` |
| 4 Transport | TCP/UDP ports, sessions | `Connection refused`, timeout | `ss`, `nc`, `curl -v` |
| 7 Name | hostnames to addresses | works by IP, fails by name | `getent`, `dig`, `resolvectl` |

**Always diagnose bottom-up.** A layer-3 problem cannot be fixed at layer 7,
and checking DNS before checking whether the interface is up wastes everybody's
time. The whole of guide 03 is this idea, expanded.

---

## Addresses and prefixes

An IPv4 address is 32 bits. The prefix length says how many leading bits are
the *network* part; the rest identify a host on that network.

```
10.10.1.10/24
             ^^ 24 network bits, 8 host bits
network:   10.10.1.0
broadcast: 10.10.1.255
usable:    10.10.1.1 - 10.10.1.254
```

| Prefix | Addresses | Netmask | Typical use |
|---|---|---|---|
| /8 | 16,777,216 | 255.0.0.0 | huge private space |
| /16 | 65,536 | 255.255.0.0 | a site |
| /24 | 256 | 255.255.255.0 | a LAN segment |
| /27 | 32 | 255.255.255.224 | a small subnet |
| /30 | 4 | 255.255.255.252 | point-to-point link |
| /31 | 2 | 255.255.255.254 | modern point-to-point |
| /32 | 1 | 255.255.255.255 | a single host route |

`ipcalc 10.10.1.10/24` does the arithmetic for you.

**Both ends of a link must agree on the prefix.** If one side says /24 and the
other says /25, one of them thinks the other is off-subnet and traffic breaks
in one direction only. That is drill `net-03`.

Private ranges (RFC1918) - these never appear on the public internet, which is
why NAT exists:

```
10.0.0.0/8         10.0.0.0    - 10.255.255.255
172.16.0.0/12      172.16.0.0  - 172.31.255.255
192.168.0.0/16     192.168.0.0 - 192.168.255.255
100.64.0.0/10      carrier-grade NAT (also used by some clouds and k8s)
169.254.0.0/16     link-local. An address here means DHCP FAILED.
127.0.0.0/8        loopback
```

Seeing `169.254.x.x` on an interface is diagnostic: the host asked for DHCP and
got no answer.

---

## Routing: longest prefix wins

The kernel keeps a routing table. For each packet it finds **every** matching
route, then picks the one with the **longest prefix** (most specific). Metric
only breaks ties between routes of equal length.

```
$ ip route show
default via 10.10.1.1 dev eth0 proto dhcp metric 100
10.10.1.0/24 dev eth0 proto kernel scope link src 10.10.1.10
10.10.2.0/24 via 10.10.1.1 dev eth0
```

- `default` is `0.0.0.0/0` - the least specific route possible, the last resort.
- `proto kernel scope link` is the **connected route**, created automatically
  when you add an address. `scope link` means "reachable directly, no gateway".
- `src 10.10.1.10` is the source address the kernel will stamp on packets
  using this route.

Because /24 beats /0, a single stray route silently overrides your default
route. Real causes: a VPN client pushing `10.0.0.0/8`, Docker claiming
`172.17.0.0/16`, a failover script leaving a `/32` behind. That is drill
`net-08`.

**Never read the table by eye when you can ask the kernel:**

```bash
ip route get 10.10.2.10
# 10.10.2.10 via 10.10.1.1 dev eth0 src 10.10.1.10 uid 1000
```

This runs the real forwarding decision, honours policy routing rules and
multiple tables, and tells you the exact route, source address and interface.

---

## The neighbour table (ARP)

To put an IP packet on an Ethernet segment the kernel needs the destination's
MAC address. For an on-subnet destination that is the destination itself; for
anything else it is the **gateway's** MAC.

```
$ ip neigh show
10.10.1.1 dev eth0 lladdr 9a:3f:11:22:33:44 REACHABLE
10.10.1.55 dev eth0 FAILED
```

| State | Meaning |
|---|---|
| `REACHABLE` | confirmed recently |
| `STALE` | cached, unconfirmed; will be revalidated when next used |
| `DELAY` / `PROBE` | revalidation in progress |
| `FAILED` | ARP was sent, nobody answered |
| `PERMANENT` | pinned by hand; never expires, never self-corrects |

`FAILED` on your gateway plus `Destination Host Unreachable` from ping means the
next hop does not exist. That is drills `net-05` and `net-10`.

```bash
ip neigh flush all                 # clear the cache
arping -I eth0 -c3 10.10.1.1       # who really owns this IP?
```

`arping` returning replies from **two different MACs** is how you find a
duplicate IP address.

---

## Name resolution

Three separate mechanisms, consulted in an order you control:

```
/etc/nsswitch.conf     hosts: files dns      <- the ORDER
/etc/hosts             static overrides, win over DNS by default
/etc/resolv.conf       on modern Ubuntu, a stub pointing at 127.0.0.53
```

On Ubuntu 18.04+ `systemd-resolved` sits in the middle, so `/etc/resolv.conf`
usually says `nameserver 127.0.0.53` and tells you nothing useful. The real
configuration is:

```bash
resolvectl status                  # actual upstream servers, per link
resolvectl query web.example.com   # resolve the way the system does
resolvectl flush-caches            # clear a poisoned cache
```

Two commands that answer different questions:

```bash
getent hosts web.lab.local    # what the APPLICATION sees (nsswitch: hosts+DNS)
dig +short web.lab.local      # what DNS says, ignoring /etc/hosts
```

When those two disagree, something local is overriding DNS. That is drill
`net-06`.

---

## Ports and sockets

```bash
ss -ltnp        # listening TCP, numeric, with process
ss -lunp        # listening UDP
ss -tnp         # established TCP connections
ss -s           # summary counts
```

Read the **Local Address** column carefully:

| Bound to | Reachable from |
|---|---|
| `127.0.0.1:8080` | this host only. A very common "firewall" false alarm. |
| `0.0.0.0:8080` | every IPv4 address on the host |
| `[::]:8080` | every IPv6 address, and usually IPv4 too via v4-mapped |
| `10.10.2.10:8080` | that one address only |

Failure signatures at this layer:

- `Connection refused` - the host answered, nothing is listening. TCP RST.
- `Connection timed out` - silence. Firewall DROP, or the host is gone.
- `Connection reset by peer` - it was listening, then killed the connection.

---

## MTU and fragmentation

MTU is the largest frame an interface will carry, normally 1500 bytes on
Ethernet. If a packet is too big for the next link:

- without the DF bit, the router fragments it
- with the DF bit (which TCP always sets), the router **drops it** and returns
  ICMP type 3 code 4, `fragmentation needed`

That ICMP message is how Path MTU Discovery works. If a firewall blocks it, the
sender never learns and you get a **black hole**: small packets fine, large
packets vanish. Symptoms: ping works, DNS works, short pages load, big
downloads hang, SSH connects then freezes on the first long output.

```bash
ping -M do -s 1472 10.10.2.10    # 1472 + 28 = 1500 bytes total
tracepath 10.10.2.10             # prints the discovered MTU per hop
ip link set eth0 mtu 1400
```

Common MTUs: 1500 Ethernet, 1492 PPPoE, 1450 VXLAN/WireGuard, 1420 IPsec,
9000 jumbo (must be set on *every* device in the path). That is drill `net-09`.

---

## The three sysctls that matter most

```bash
net.ipv4.ip_forward = 1              # turns a host into a router. Off by default.
net.ipv4.conf.all.rp_filter = 1      # reverse path filter: drop packets arriving
                                     # on an interface you would not reply through.
                                     # The usual cause of asymmetric-routing drops.
net.ipv6.conf.all.forwarding = 1     # the IPv6 equivalent. Forgetting it gives you
                                     # a router that forwards IPv4 only.
```

`sysctl -w` is temporary. Anything that must survive a reboot goes in
`/etc/sysctl.d/99-something.conf` followed by `sudo sysctl --system`. Drill
`net-04` is exactly the "it worked until we rebooted" version of this.

---

## What to remember

- Diagnose bottom-up: link, then neighbour, then route, then port, then name.
- `ip route get <dst>` answers the routing question definitively.
- Longest prefix wins, so a stray specific route beats your correct default.
- `Network is unreachable`, `Host is unreachable` and a silent timeout are
  three different faults in three different places.
- Small works / big hangs means MTU, essentially always.
- `sysctl -w` does not survive a reboot.
