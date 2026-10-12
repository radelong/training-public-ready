# netlab

A deployable break/fix lab for **Linux networking**, **iptables** and
**Kubernetes**, designed to run inside an Ubuntu VM.

It injects one realistic fault at a time, briefs you like a support ticket,
lets you investigate with real tools, and then verifies whether you actually
fixed it. Every drill ships with a hint, a full solution, and a debrief
explaining what the same fault looks like in production.

---

## Install

Copy this folder to your Ubuntu VM (22.04 or 24.04), then:

```bash
tar xzf netlab-ubuntu.tar.gz
cd netlab-ubuntu
sudo bash install.sh
```

(Running it as `sudo bash install.sh` rather than `sudo ./install.sh` means it
works even if the execute bit was lost in transit from Windows.)

Add Kubernetes at the same time (needs internet, a few minutes):

```bash
sudo bash install.sh --with-k8s
```

Check the machine has everything:

```bash
netlab doctor
```

---

## First ten minutes

```bash
netlab guide 00                              # read this first
sudo netlab lab up                           # build the topology
sudo netlab status                           # see it working
sudo netlab list                             # 28 drills
sudo netlab start net-01-link-down           # your first ticket
```

Investigate:

```bash
sudo netlab exec client ip -br addr          # one command in a namespace
sudo netlab sh client                        # or an interactive shell
```

Then:

```bash
sudo netlab check                            # did you fix it?
sudo netlab hint                             # stuck?
sudo netlab solution                         # full walkthrough
sudo netlab reset                            # back to known-good
```

Kubernetes half:

```bash
sudo netlab k8s up
sudo netlab start k8s-01-first-deployment
```

Prove it stuck:

```bash
sudo netlab challenge net                    # random, undisclosed fault
sudo netlab progress                         # scoreboard
```

---

## Is this safe to run?

Yes. The network drills all happen inside **network namespaces** - separate
copies of the Linux network stack with their own interfaces, routes, ARP caches
and iptables rules. You can set `INPUT DROP`, delete every route and blackhole
the world without touching your VM's real connectivity or your SSH session.

Two things do touch the host, both removed by `sudo netlab lab down`:

- a veth interface `nl-up-h` at `10.10.0.1`, so the host can reach the lab
- IP forwarding plus one `MASQUERADE` rule for `10.10.0.0/16`

One drill (`net-07-nat-missing`) deliberately works on that host NAT rule, and
says so in its brief. It only touches the `nat` table.

For when you *do* want to experiment on the real firewall, the package includes
a safety net:

```bash
sudo netlab snapshot save before-experiment
sudo netlab deadman 15          # auto-restores your iptables in 15 minutes
sudo netlab deadman-cancel      # once you have confirmed you are still connected
```

---

## What is in the box

```
netlab-ubuntu/
  install.sh            installer (also --deps-only, --with-k8s, --uninstall)
  bin/netlab            the CLI
  lib/
    common.sh           shared config, helpers, test primitives
    topology.sh         builds/destroys the namespace topology
    k8s.sh              k3s install, seeding, verification helpers
    usage.txt           command reference
  drills/               28 break/fix exercises (10 net, 8 fw, 10 k8s)
  guides/               12 lab manuals -- see below
  k8s/manifests/        broken-on-purpose YAML + a solutions/ directory
```

### Guides

| File | Covers |
|---|---|
| `00-START-HERE.md` | orientation, topology, recommended order |
| `01-linux-networking-fundamentals.md` | layers, addressing, routing, ARP, DNS, MTU |
| `02-ip-command-cookbook.md` | every `ip`/`ss`/`tcpdump` command, plus netplan |
| `03-troubleshooting-methodology.md` | the fixed diagnostic order, error-message table |
| `04-iptables-fundamentals.md` | tables, chains, targets, packet flow, conntrack |
| `05-iptables-cookbook.md` | copy-paste rules: host, router, NAT, rate limiting |
| `06-ufw-nftables-persistence.md` | ufw, nftables, persistence, Docker interference |
| `07-kubernetes-fundamentals.md` | the object model and what runs where |
| `08-kubectl-cookbook.md` | the commands, including the ones people forget |
| `09-k8s-troubleshooting.md` | decision tree by pod status |
| `10-k8s-networking-and-iptables.md` | Services, DNS, CNI, kube-proxy's real rules |
| `99-cheatsheet.md` | one-page reference for all three topics |

Read them with `netlab guide 04`, or open the Markdown in
`/opt/netlab/guides/`.

---

## The topology

```
     nl-client                nl-router                  nl-server
   +------------+        +----------------+          +------------+
   |    eth0    |--------| lan0      dmz0 |----------|    eth0    |
   | 10.10.1.10 |        | 10.10.1.1      |          | 10.10.2.10 |
   +------------+        |      10.10.2.1 |          |   :8080    |
                         |      up0       |          |   :9090    |
                         |   10.10.0.2    |          +------------+
                         +-------|--------+
                                 |
                          nl-up-h 10.10.0.1
                             [ your VM ]
```

The server serves `/health` (returns `netlab-ok`), `/` and `/big.bin` (6 MB,
used by the MTU drill).

---

## Drills

**Networking (10)** - link state, default routes, prefix lengths, IP
forwarding, ARP poisoning, name resolution, source NAT, longest-prefix match,
PMTU black holes, wrong gateways.

**iptables (8)** - stateful firewalling, INPUT vs FORWARD, per-port blocking,
rule ordering, egress filtering, DNAT, ICMP, custom chains.

**Kubernetes (10)** - deployments and services, CrashLoopBackOff,
ImagePullBackOff, unschedulable pods, selector mismatches, readiness probes,
ConfigMaps and Secrets, rollout and rollback, NetworkPolicy, and tracing a
NodePort down into the actual iptables rules kube-proxy writes.

`sudo netlab list` shows them all with your progress.

---

## Requirements

- Ubuntu 22.04 or 24.04 (any Debian derivative should work)
- root / sudo
- ~1 GB disk, 2 GB RAM (4 GB recommended with Kubernetes)
- internet access for `install.sh` and `netlab k8s up`; the networking and
  iptables drills then work fully offline

WSL2 runs most drills, but namespaces and k3s behave better in a real VM
(VirtualBox, VMware, Proxmox, Hyper-V, or any cloud instance).

---

## Uninstall

```bash
sudo netlab lab down          # remove the topology
sudo bash install.sh --uninstall  # remove netlab entirely
sudo /usr/local/bin/k3s-uninstall.sh   # remove Kubernetes, if installed
```
