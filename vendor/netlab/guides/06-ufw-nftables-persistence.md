# 06 - ufw, nftables, and making firewall rules survive a reboot

Three things live in the same kernel subsystem and constantly confuse people:
`ufw`, raw `iptables`, and `nftables`. Here is how they relate and how to make
any of them permanent.

---

## What is actually running on your box

```bash
sudo iptables --version
# iptables v1.8.7 (nf_tables)   <- iptables commands, nftables backend
# iptables v1.8.7 (legacy)      <- the old x_tables backend

sudo update-alternatives --display iptables
sudo nft list ruleset | head -40
sudo ufw status verbose
systemctl is-active nftables ufw netfilter-persistent
```

On Ubuntu 22.04 and 24.04, `iptables` is `iptables-nft` by default: your
familiar commands are translated into nftables rules under the hood. You can
write iptables syntax and read the result with `nft list ruleset`. Mixing
`iptables-legacy` and `iptables-nft` on the same box, however, gives you two
independent rulesets that both apply - avoid it.

---

## ufw

`ufw` is a friendly front-end that generates iptables rules. It is a good
default for a single server, and it is not a good fit for a router.

```bash
sudo ufw status verbose
sudo ufw status numbered

sudo ufw default deny incoming
sudo ufw default allow outgoing

sudo ufw allow 22/tcp
sudo ufw allow OpenSSH                     # named application profile
sudo ufw allow from 10.0.0.0/8 to any port 22 proto tcp
sudo ufw allow 80,443/tcp                  # newer ufw accepts this
sudo ufw limit 22/tcp                      # built-in brute-force limiting

sudo ufw delete allow 80/tcp
sudo ufw delete 3                          # by number from 'status numbered'
sudo ufw insert 1 deny from 203.0.113.66

sudo ufw enable
sudo ufw disable
sudo ufw reset                             # back to defaults

sudo ufw app list
sudo ufw logging on
sudo ufw logging medium
```

### ufw and iptables together

`ufw` writes chains called `ufw-before-input`, `ufw-user-input`,
`ufw-after-input` and so on, hooked into `INPUT`:

```bash
sudo iptables -S | grep ufw | head -20
```

Consequences:

- Rules you add by hand with `iptables -A INPUT` land **after** the ufw jump,
  so ufw's default deny usually wins and your rule never fires.
- `ufw reload` and `ufw enable` rebuild the chains and **discard** your
  hand-written rules.
- To add raw rules that coexist with ufw, put them in
  `/etc/ufw/before.rules` (evaluated before the user rules) and reload.

**Pick one tool per machine.** ufw *or* hand-written iptables, not both.

```bash
# ufw config files
/etc/default/ufw            # IPV6=yes, DEFAULT_FORWARD_POLICY
/etc/ufw/before.rules       # raw iptables-restore syntax, runs first
/etc/ufw/after.rules
/etc/ufw/user.rules         # generated -- do not edit by hand
```

To make ufw route and NAT (turning it into a gateway), you need two edits:

```bash
# /etc/default/ufw
DEFAULT_FORWARD_POLICY="ACCEPT"

# /etc/ufw/before.rules -- add ABOVE the *filter line
*nat
:POSTROUTING ACCEPT [0:0]
-A POSTROUTING -s 10.10.0.0/16 -o ens18 -j MASQUERADE
COMMIT
```

plus `net.ipv4.ip_forward=1` in `/etc/sysctl.d/`, then `sudo ufw reload`.

---

## nftables

nftables is the modern replacement for iptables, ip6tables, arptables and
ebtables in one tool. Ubuntu ships it and `iptables-nft` already uses it.

```bash
sudo nft list ruleset
sudo nft list tables
sudo nft list table inet filter
sudo nft -f /etc/nftables.conf              # load a file
sudo nft flush ruleset                      # remove everything
```

A complete, readable host firewall:

```
#!/usr/sbin/nft -f
flush ruleset

table inet filter {
  chain input {
    type filter hook input priority 0; policy drop;

    iif lo accept
    ct state established,related accept
    ct state invalid drop

    ip protocol icmp icmp type { echo-request, destination-unreachable, time-exceeded } accept
    ip6 nexthdr icmpv6 accept

    tcp dport { 22, 80, 443 } ct state new accept

    limit rate 5/minute log prefix "NFT-DROP: "
  }

  chain forward { type filter hook forward priority 0; policy drop; }
  chain output  { type filter hook output  priority 0; policy accept; }
}

table inet nat {
  chain prerouting  { type nat hook prerouting  priority -100; }
  chain postrouting {
    type nat hook postrouting priority 100;
    ip saddr 10.10.0.0/16 oifname "ens18" masquerade
  }
}
```

```bash
sudo cp firewall.nft /etc/nftables.conf
sudo systemctl enable --now nftables
sudo systemctl status nftables
```

What is genuinely better about it:

- One tool for IPv4 and IPv6 (`table inet`) - no more forgetting ip6tables.
- Native sets and maps: `tcp dport { 22, 80, 443 }` is one rule, not three, and
  is a hash lookup rather than a linear scan.
- Atomic rule replacement is built in.
- Counters are opt-in, so the fast path is faster.

Translate what you already know:

```bash
iptables-translate -A INPUT -p tcp --dport 22 -j ACCEPT
# nft add rule ip filter INPUT tcp dport 22 counter accept

iptables-restore-translate -f /etc/iptables/rules.v4 > /etc/nftables.conf
```

---

## Making rules persistent

### iptables

```bash
sudo apt install iptables-persistent
sudo netfilter-persistent save
sudo netfilter-persistent reload
# /etc/iptables/rules.v4  and  /etc/iptables/rules.v6
```

Without this package, everything you set with `iptables` is gone at reboot.
That is a favourite production trap: the fix works, nobody persists it, the box
reboots months later and the outage looks unrelated to anything.

### nftables

```bash
sudo nft list ruleset | sudo tee /etc/nftables.conf
sudo systemctl enable nftables
```

### ufw

Persistent automatically once `ufw enable` has been run.

### Verify after any reboot

```bash
sudo iptables -S | head
sudo nft list ruleset | head
sudo ufw status
sysctl net.ipv4.ip_forward
```

---

## Docker will fight you

Docker manipulates iptables directly and inserts its own chains:

```bash
sudo iptables -S | grep -i docker
# -N DOCKER
# -N DOCKER-USER
# -N DOCKER-ISOLATION-STAGE-1
# -A FORWARD -j DOCKER-USER
```

Three things to know:

1. **Published container ports bypass ufw.** `docker run -p 80:80` inserts a
   DNAT rule in `PREROUTING`, which is evaluated before the filter table, so
   `ufw deny 80` does not block it. This surprises people badly.
2. **Put your rules in `DOCKER-USER`.** It is jumped to first from FORWARD and
   Docker never rewrites it:
   ```bash
   sudo iptables -I DOCKER-USER 1 -i ens18 ! -s 10.0.0.0/8 -j DROP
   ```
3. Bind published ports to a specific address when you do not want them public:
   `docker run -p 127.0.0.1:8080:80 ...`

The same lesson applies to Kubernetes: kube-proxy owns the `KUBE-*` chains and
rewrites them constantly. Never hand-edit them; express policy through
NetworkPolicy objects instead (guide 10).

---

## Who else is writing to your firewall

On a mature server, run this before you conclude anything:

```bash
sudo iptables -S | grep -E '^-N'      # every custom chain = someone's tool
```

Typical owners:

| Chain prefix | Owner |
|---|---|
| `ufw-*` | ufw |
| `f2b-*` | fail2ban |
| `DOCKER*` | Docker |
| `KUBE-*` | kube-proxy |
| `CNI-*` | a CNI plugin (Calico, Flannel) |
| `cali-*` | Calico |
| `LIBVIRT_*` | libvirt / KVM |
| `tailscale*` | Tailscale |

When your hand-written rule mysteriously stops working, one of these rebuilt
the chain underneath you.
