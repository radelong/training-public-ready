# 03 - Troubleshooting methodology

The difference between someone who fixes networks in five minutes and someone
who takes three hours is almost never knowledge of commands. It is having a
fixed order and sticking to it.

---

## The rule: bottom-up, and bisect

**Bottom-up.** Start at layer 1 and climb. Never debug DNS before you know the
interface is up.

**Bisect.** Every test should cut the remaining problem space roughly in half.
"Can I ping the gateway?" splits local-config faults from everything-else
faults in one command.

---

## The seven-step ladder

Work down this list. Stop at the first step that fails - that is where your
problem is.

```
1. Is the interface up?              ip -br link
2. Does it have the right address?   ip -br addr
3. Is there a route to the target?   ip route get <dst>
4. Can I reach the next hop?         ping <gateway>  +  ip neigh show
5. Does the packet leave / arrive?   tcpdump on both ends
6. Is the port open and listening?   ss -ltnp  (on the server)
7. Does the name resolve correctly?  getent hosts <name>
```

Steps 1-4 run on the client. Step 5 runs on both. Step 6 runs on the server.
Step 7 only matters if you got this far and IP-based access works.

---

## Read the error message - it names the layer

This table alone will save you more time than any tool.

| Message | What it means | Look at |
|---|---|---|
| `Network is unreachable` | no matching route at all | routing table, default route |
| `Destination Host Unreachable` | route exists, ARP failed | neighbour table, gateway address, layer 2 |
| `Connection refused` | host answered, nothing listening | the service, `ss -ltnp`, bind address |
| `Connection timed out` | silence | firewall DROP, asymmetric route, host down |
| `Connection reset by peer` | it was listening, then hung up | the application, TLS mismatch, a REJECT rule |
| `No route to host` | usually a local REJECT or ARP failure | firewall OUTPUT chain, neighbour table |
| `Packet filtered` | an explicit REJECT | a firewall on the path, or your own OUTPUT |
| `Temporary failure in name resolution` | DNS | `resolvectl status`, `/etc/resolv.conf` |
| `Name or service not known` | DNS returned NXDOMAIN | the name itself, search domains |
| `100% packet loss`, no message | silent drop | firewall DROP, or return path broken |

Note the crucial pair at the bottom. **A DROP produces silence and a timeout.
A REJECT produces an immediate error.** When a user says "it hangs" versus "it
fails straight away", they have already told you which rule they hit.

---

## The three-tcpdump method

This localises any fault to a single machine, quickly. Run these in three
terminals while generating traffic in a fourth.

```bash
# 1. on the SOURCE, outbound interface
tcpdump -ni eth0 host 10.10.2.10

# 2. on any DEVICE IN BETWEEN, both interfaces
tcpdump -ni lan0 host 10.10.2.10
tcpdump -ni dmz0 host 10.10.2.10

# 3. on the DESTINATION
tcpdump -ni eth0 host 10.10.1.10
```

Then read the result:

| Symptom | Conclusion |
|---|---|
| nothing leaves the source | source `OUTPUT` firewall chain, or source routing |
| leaves source, never arrives at the router | layer 2, wrong gateway, VLAN, cabling |
| arrives at router, never leaves it | `ip_forward=0`, `FORWARD` chain, routing |
| arrives at destination, no reply sent | destination `INPUT` chain, or no listener |
| reply sent, never gets back | return route, source `INPUT` chain, NAT, rp_filter |

That last row is the one people miss. Traffic problems are frequently
**asymmetric**: the request arrives perfectly and the answer takes a different
path home, or is dropped on the way back.

---

## Isolate the variable

Before changing anything, narrow it down with quick contrasts:

- **Same host, different port?** `curl :8080` fails, `curl :9090` works
  -> per-port firewall rule or a dead service, not the network.
- **Same port, different host?** works to server A, not to server B
  -> the problem is on B, not the client.
- **Same everything, different protocol?** ping fails, TCP works
  -> ICMP is filtered. Nothing is actually down. (Drill `fw-07`.)
- **By IP vs by name?** IP works, name does not -> resolution. (Drill `net-06`.)
- **Small vs large transfer?** small works, large hangs -> MTU. (Drill `net-09`.)
- **From the server itself?** `curl localhost` works, remote does not
  -> firewall, or the service is bound to 127.0.0.1 only.

That last check is worth doing early. `ss -ltnp` showing `127.0.0.1:8080`
explains an enormous number of "the firewall is broken" tickets.

---

## Firewall triage, in order

```bash
sudo iptables -S                            # the WHOLE ruleset, all chains
sudo iptables -L -n -v --line-numbers       # with packet counters
sudo iptables -t nat -L -n -v               # NAT is a separate table!
sudo nft list ruleset                       # if the box uses nftables natively
sudo ufw status verbose                     # if ufw is in play
```

**Use the counters as a debugger.** Run your failing test, then list the rules
again and see which counter incremented. That tells you exactly which rule is
handling your traffic. A rule with zero packets is a rule that is never reached.

Add a temporary logging rule while you work:

```bash
sudo iptables -I INPUT 1 -m limit --limit 5/min -j LOG --log-prefix "IPT-IN: "
sudo journalctl -kf | grep IPT-IN
# ... and remove it when done
sudo iptables -D INPUT 1
```

The `--limit` is not optional. An unlimited LOG rule on a busy host fills the
disk.

---

## Kubernetes triage, in order

```bash
kubectl get pods -A | grep -v Running        # anything unhealthy anywhere?
kubectl -n <ns> get events --sort-by=.lastTimestamp | tail -20
kubectl -n <ns> describe pod <pod>           # Events section at the bottom
kubectl -n <ns> logs <pod> --previous        # for a restarting container
kubectl -n <ns> get endpointslices           # does the Service have backends?
```

The single highest-value question in Kubernetes networking is **"does the
Service have endpoints?"** It splits the problem cleanly:

- **No endpoints** -> the problem is before the network: label selector, or
  pods that are not Ready. Stop looking at DNS and CNI.
- **Has endpoints** -> the problem is after: DNS, NetworkPolicy, ports, or the
  application itself.

Guide 09 expands this into a full decision tree by pod status.

---

## Change discipline

1. **Change one thing at a time.** Two simultaneous changes and you no longer
   know which one did what - including which one broke something new.
2. **Write down what you changed**, as you go, in a scratch file. During an
   incident you will not remember.
3. **Know how to undo it before you do it.**
   ```bash
   sudo iptables-save > /tmp/rules-before.v4
   sudo cp /etc/netplan/50-cloud-init.yaml /tmp/
   sudo netlab snapshot save before-change
   ```
4. **Arm a dead-man switch on a remote box.**
   ```bash
   sudo netlab deadman 15          # restores iptables in 15 minutes
   # ... make your change, verify you are still connected ...
   sudo netlab deadman-cancel
   ```
   Or by hand, without netlab:
   ```bash
   sudo bash -c 'iptables-save > /root/fw.bak; \
     echo "iptables-restore < /root/fw.bak" | at now + 10 minutes'
   ```
5. **Verify with the same test the user reported**, not with a test you know
   will pass.
6. **Then make it persistent** - netplan, `/etc/sysctl.d/`,
   `netfilter-persistent save`. A fix that dies at reboot is not a fix, it is a
   scheduled outage.

---

## Things that waste the most time

- Debugging DNS when the interface is down.
- Trusting `ping`. It tests ICMP to one host and nothing else. A box can ping
  perfectly with a full disk and a dead application.
- Forgetting `-t nat`. `iptables -L` shows you nothing about NAT, and NAT is
  where half of connectivity problems live.
- Forgetting that changing a NAT rule does nothing to **existing** connections
  until you flush conntrack (`conntrack -F`).
- Not checking `OUTPUT`. Everyone checks `INPUT`.
- Reading the routing table by eye instead of running `ip route get`.
- Fixing it at runtime and never writing it into netplan or sysctl.d.
- Assuming the last change caused it, without checking. Often true. Not always.
