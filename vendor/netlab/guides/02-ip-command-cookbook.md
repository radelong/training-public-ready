# 02 - The `ip` command cookbook, and making changes stick

`ifconfig`, `route` and `netstat` are deprecated and, on Ubuntu, often not even
installed. Everything below uses `iproute2` (`ip`, `ss`, `bridge`) plus netplan
for persistence.

Old command | Use this instead
---|---
`ifconfig` | `ip addr` / `ip link`
`ifconfig eth0 up` | `ip link set eth0 up`
`route -n` | `ip route show`
`route add default gw X` | `ip route add default via X`
`arp -n` | `ip neigh show`
`netstat -tulpn` | `ss -tulpn`
`netstat -rn` | `ip route show`

---

## Fast status: the `-br` flag

`-br` is "brief" and turns `ip` output into scannable columns. Use it first,
always.

```bash
ip -br addr          # every interface, state, addresses -- one line each
ip -br link          # state and MAC
ip -c -br addr       # -c adds colour
ip -4 -br addr       # IPv4 only
```

```
lo     UNKNOWN  127.0.0.1/8 ::1/128
ens18  UP       192.0.2.50/24 fe80::5054:ff:fe12:3456/64
docker0 DOWN    172.17.0.1/16
```

---

## Interfaces

```bash
ip link show                       # all interfaces, verbose
ip link show ens18
ip link set ens18 up
ip link set ens18 down
ip link set ens18 mtu 1400
ip link set ens18 address 02:11:22:33:44:55     # change MAC (must be down)
ip link set ens18 name wan0                     # rename (must be down)

ip -s link show ens18              # statistics: packets, errors, drops
ethtool ens18                      # speed, duplex, link detected
ethtool -S ens18                   # driver-level counters
ethtool -i ens18                   # which driver and firmware
```

`RX errors` or `TX dropped` climbing steadily is a hardware, driver or duplex
problem, not a configuration problem.

---

## Addresses

```bash
ip addr show dev ens18
ip addr add 10.10.1.10/24 dev ens18
ip addr add 10.10.1.11/24 dev ens18            # secondary address, fine
ip addr del 10.10.1.10/24 dev ens18
ip addr flush dev ens18                        # remove ALL addresses
```

The prefix is not optional. `ip addr add 10.10.1.10 dev ens18` gives you a /32
and nothing will work.

Adding an address automatically creates the **connected route** for its subnet.
Flushing addresses removes those routes with them - which is why `net-03` also
loses its default route.

---

## Routes

```bash
ip route show                                  # main table
ip route show table all                        # every table
ip route get 10.10.2.10                        # THE diagnostic command

ip route add default via 10.10.1.1
ip route add default via 10.10.1.1 dev ens18 metric 100
ip route add 10.10.2.0/24 via 10.10.1.1
ip route replace 10.10.2.0/24 via 10.10.1.1    # idempotent: use this in scripts
ip route del 10.10.2.0/24
ip route del default

ip route add blackhole 10.99.0.0/16            # drop silently
ip route add unreachable 10.99.0.0/16          # reply ICMP host unreachable
ip route add prohibit 10.99.0.0/16             # reply ICMP admin prohibited
```

`add` fails if the route exists; `replace` does not. In automation always use
`replace`.

Policy routing, when one table is not enough:

```bash
ip rule show
ip rule add from 10.10.1.0/24 table 100
ip route add default via 10.10.1.1 table 100
ip route show table 100
ip route get 10.10.2.10 from 10.10.1.10        # test a specific source
```

---

## Neighbours (ARP / NDP)

```bash
ip neigh show
ip neigh show dev ens18
ip neigh flush all
ip neigh flush dev ens18
ip neigh del 10.10.1.1 dev ens18
ip neigh replace 10.10.1.1 lladdr aa:bb:cc:dd:ee:ff dev ens18   # static

arping -I ens18 -c3 10.10.1.1        # who answers for this IP?
arping -D -I ens18 -c3 10.10.1.10    # duplicate address detection
```

---

## Network namespaces

This is what the lab is built from, and it is worth knowing for containers too.

```bash
ip netns list
ip netns add test
ip netns exec test ip addr
ip netns exec test bash                       # a shell in that namespace
ip netns del test

# connect a namespace to the host
ip link add veth0 type veth peer name veth1
ip link set veth1 netns test
ip addr add 10.0.0.1/24 dev veth0 && ip link set veth0 up
ip netns exec test ip addr add 10.0.0.2/24 dev veth1
ip netns exec test ip link set veth1 up
ip netns exec test ip link set lo up
```

`ip netns exec <ns>` bind-mounts `/etc/netns/<ns>/*` over `/etc/*`, which is how
each namespace in this lab gets its own `resolv.conf` and `hosts`.

---

## Sockets

```bash
ss -ltnp                # listening TCP + process
ss -lunp                # listening UDP + process
ss -tnp                 # established TCP
ss -tn state established '( dport = :443 )'
ss -tn dst 10.10.2.10
ss -s                   # summary
ss -tnp | grep :8080
```

---

## Capturing traffic

```bash
tcpdump -ni ens18                              # never resolve names: -n
tcpdump -ni ens18 icmp
tcpdump -ni ens18 host 10.10.2.10
tcpdump -ni ens18 tcp port 8080
tcpdump -ni ens18 'tcp[tcpflags] & tcp-syn != 0'   # SYNs only
tcpdump -ni ens18 -c 20                        # stop after 20 packets
tcpdump -ni ens18 -w /tmp/cap.pcap             # write for Wireshark
tcpdump -nr /tmp/cap.pcap                      # read it back
tcpdump -ni any port 8080                      # all interfaces at once
```

Always pass `-n`. Without it tcpdump does reverse DNS on every address, which is
slow and, when DNS is the thing that is broken, hangs.

The single most valuable technique: capture on the **ingress** interface, then
on the **egress** interface. Wherever the packet stops appearing is where the
problem lives.

---

## Making it permanent: netplan

Runtime `ip` commands vanish on reboot. Ubuntu uses **netplan**, which writes
YAML in `/etc/netplan/` and renders it to systemd-networkd or NetworkManager.

```bash
ls /etc/netplan/
sudo cp /etc/netplan/50-cloud-init.yaml /etc/netplan/50-cloud-init.yaml.bak
sudo nano /etc/netplan/50-cloud-init.yaml
```

Static address:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens18:
      dhcp4: false
      addresses:
        - 10.10.1.10/24
      routes:
        - to: default
          via: 10.10.1.1
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
        search: [lab.local]
      mtu: 1500
```

DHCP with a couple of overrides:

```yaml
network:
  version: 2
  ethernets:
    ens18:
      dhcp4: true
      dhcp4-overrides:
        use-dns: false
        route-metric: 100
      nameservers:
        addresses: [1.1.1.1]
```

Extra static routes:

```yaml
      routes:
        - to: 10.10.2.0/24
          via: 10.10.1.1
        - to: default
          via: 10.10.1.1
          metric: 100
```

Apply it - and note which command to use where:

```bash
sudo netplan generate     # render config, do not apply. Catches syntax errors.
sudo netplan try          # apply with an AUTOMATIC ROLLBACK after 120 seconds
sudo netplan apply        # apply permanently
```

**On a remote machine, always `netplan try` first.** If your change breaks your
own SSH session, you say nothing, it times out, and the old config comes back.
`netplan apply` gives you no such mercy.

YAML gotchas that cost people hours:

- Indentation is two spaces, never tabs.
- File permissions should be `600` - netplan warns loudly otherwise.
- Files are read in lexical order and merged; `99-custom.yaml` overrides
  `50-cloud-init.yaml`.
- On a cloud image, cloud-init may rewrite `50-cloud-init.yaml` on every boot.
  Disable it with:
  `echo 'network: {config: disabled}' | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg`

---

## Making sysctls permanent

```bash
sudo tee /etc/sysctl.d/99-router.conf <<'EOF'
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
net.ipv4.conf.all.rp_filter = 2
EOF
sudo sysctl --system
sysctl net.ipv4.ip_forward
```

---

## A 60-second health check

```bash
ip -br addr                       # addresses present and interfaces up?
ip route show                     # default route present?
ip route get 1.1.1.1              # what will the kernel actually do?
ping -c2 $(ip route show default | awk '{print $3}')   # gateway alive?
ping -c2 1.1.1.1                  # internet by IP?
getent hosts example.com          # name resolution?
ss -ltnp                          # expected services listening?
sudo iptables -S | head -30       # any firewall surprises?
```

Run those seven in order and you will have localised almost any connectivity
fault before you have finished reading the ticket.
