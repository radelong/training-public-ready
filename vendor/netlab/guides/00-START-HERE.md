# 00 - Start here: how this lab works

You are holding a self-contained practice environment for three things that
break constantly on real Ubuntu servers:

1. **Linux networking** - addresses, routes, ARP, DNS, MTU
2. **iptables** - filtering, NAT, rule ordering, custom chains
3. **Kubernetes** - deployments, services, probes, rollouts, network policy

Everything is a break/fix drill. The lab injects one specific, realistic fault,
briefs you like a support ticket, and then checks whether you actually fixed it.

---

## 1. Install it

Copy the `netlab-ubuntu` folder onto your Ubuntu VM, then:

```bash
tar xzf netlab-ubuntu.tar.gz
cd netlab-ubuntu
sudo bash install.sh
```

Add `--with-k8s` if you want Kubernetes installed at the same time (needs
internet, takes a few minutes):

```bash
sudo bash install.sh --with-k8s
```

Then confirm the machine has what it needs:

```bash
netlab doctor
```

---

## 2. Understand what gets built

`sudo netlab lab up` creates three **network namespaces**. A network namespace
is a completely separate copy of the Linux network stack: its own interfaces,
own routing table, own ARP cache, own iptables rules. Containers are built out
of them. For you, the important property is this:

> **Nothing you do inside a namespace can take your VM off the network.**

You can set `INPUT DROP`, delete every route, and blackhole the world, and your
SSH session is untouched. That is what makes this safe to practise on.

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

- **nl-client** - the "user workstation". Most faults are diagnosed from here.
- **nl-router** - forwards between the two subnets. Where FORWARD and NAT live.
- **nl-server** - runs two Python web servers on ports 8080 and 9090, serving
  `/health` (returns `netlab-ok`), `/` and `/big.bin` (6 MB, for the MTU drill).

Two things *do* touch your real host, both reversible with `sudo netlab lab down`:

- a veth interface `nl-up-h` with address `10.10.0.1`, so the host can reach the lab
- IP forwarding plus a `MASQUERADE` rule for `10.10.0.0/16`, so the lab can reach the internet

Drill `net-07-nat-missing` deliberately works on that host NAT rule. It is the
only network drill that touches the real firewall, and it only touches the
`nat` table.

---

## 3. Work a drill

```bash
sudo netlab lab up
sudo netlab list
sudo netlab start net-01-link-down
```

You get a symptom and a goal, like a ticket. Then you investigate using the
namespaces:

```bash
sudo netlab exec client ip -br addr        # run one command in a namespace
sudo netlab sh client                      # or get an interactive shell
```

When you think it is fixed:

```bash
sudo netlab check
```

If you are stuck:

```bash
sudo netlab hint        # a nudge, no spoilers
sudo netlab solution    # the full walkthrough
sudo netlab reset       # put everything back to known-good
```

Passing a drill prints a **debrief** explaining why the fix worked and what the
same fault looks like in production. Read those - they are the actual teaching
material, the fault is just the excuse.

---

## 4. The recommended order

**Networking** (do these first - iptables makes no sense until routing does):

| Drill | Teaches |
|---|---|
| `net-01-link-down` | interface admin state, triage order |
| `net-02-no-default-route` | routing tables, `ip route get` |
| `net-10-wrong-gateway` | reading failure messages precisely |
| `net-03-wrong-netmask` | prefix lengths, connected routes |
| `net-04-forwarding-off` | `ip_forward`, tcpdump in/out technique |
| `net-05-bogus-arp` | the neighbour table, layer 2 |
| `net-06-name-resolution` | nsswitch, hosts, systemd-resolved |
| `net-08-blackhole-route` | longest-prefix match |
| `net-07-nat-missing` | SNAT/MASQUERADE, conntrack |
| `net-09-mtu-blackhole` | PMTU black holes, MSS clamping |

**iptables**:

| Drill | Teaches |
|---|---|
| `fw-07-icmp-blocked` | ping is not a health check |
| `fw-03-port-blocked` | DROP vs REJECT, `ss -ltnp` |
| `fw-01-no-conntrack` | stateful firewalling, the minimum ruleset |
| `fw-02-forward-drop` | INPUT vs FORWARD, `-i`/`-o` |
| `fw-04-rule-order` | first match wins, `-I` vs `-A`, counters |
| `fw-05-output-drop` | egress filtering, the three-tcpdump method |
| `fw-08-custom-chain` | jumps, `iptables -S`, RETURN |
| `fw-06-dnat-broken` | DNAT, packet flow through the tables |

**Kubernetes**:

| Drill | Teaches |
|---|---|
| `k8s-01-first-deployment` | Deployment / ReplicaSet / Pod / Service |
| `k8s-03-imagepullbackoff` | events, image tags |
| `k8s-02-crashloop` | `logs --previous`, exit codes |
| `k8s-04-pending-pod` | scheduling, requests vs limits |
| `k8s-05-service-selector` | labels, endpoints, the key question |
| `k8s-07-configmap-secret` | configuration injection |
| `k8s-06-readiness-probe` | readiness vs liveness vs startup |
| `k8s-08-rollout-rollback` | revisions, `rollout undo` |
| `k8s-09-networkpolicy` | policy semantics, default-deny |
| `k8s-10-nodeport-iptables` | how Services are really implemented |

---

## 5. Prove it stuck

Once you have passed a module, run it blind. The lab injects a random fault
from that module and does **not** tell you which:

```bash
sudo netlab challenge net
sudo netlab challenge fw
sudo netlab challenge k8s
```

Diagnose from the symptoms alone. `sudo netlab check` when you think you have
it, `sudo netlab reveal` if you give up.

```bash
sudo netlab progress     # scoreboard
```

---

## 6. The guides

| File | What is in it |
|---|---|
| `01-linux-networking-fundamentals.md` | the model: layers, addresses, routes, ARP |
| `02-ip-command-cookbook.md` | every `ip` command you actually need, plus netplan |
| `03-troubleshooting-methodology.md` | how to diagnose in a fixed, fast order |
| `04-iptables-fundamentals.md` | tables, chains, targets, packet flow, state |
| `05-iptables-cookbook.md` | copy-paste rules for real situations |
| `06-ufw-nftables-persistence.md` | ufw, nftables, and making rules survive reboot |
| `07-kubernetes-fundamentals.md` | the object model and what runs where |
| `08-kubectl-cookbook.md` | the commands, including the ones people forget |
| `09-k8s-troubleshooting.md` | a decision tree by pod status |
| `10-k8s-networking-and-iptables.md` | services, DNS, CNI, and kube-proxy's rules |
| `99-cheatsheet.md` | one-page quick reference for all three topics |

Read them in a pager with `netlab guide 04`, or open the files directly - they
are plain Markdown in `/opt/netlab/guides/`.

---

## 7. If you want to experiment on the real host

The drills keep you safe by staying in namespaces. When you decide to
experiment on your VM's actual firewall, use the safety net:

```bash
sudo netlab snapshot save before-experiment
sudo netlab deadman 15        # auto-restores your iptables in 15 minutes
#   ... experiment ...
sudo netlab deadman-cancel    # only when you are sure you are still connected
```

If you lock yourself out anyway, the snapshot is on disk:

```bash
sudo netlab snapshot restore before-experiment
```

This is not a lab habit, it is a production habit. Every experienced engineer
has locked themselves out of a remote box exactly once.

---

## 8. Reset anything

```bash
sudo netlab reset            # restore the lab to known-good
sudo netlab lab rebuild      # tear down and rebuild the topology
sudo netlab k8s reset        # wipe and re-seed the netlab namespace
sudo netlab lab down         # remove everything, host back to normal
```
