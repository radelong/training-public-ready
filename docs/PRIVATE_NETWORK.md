# Example private services network on Proxmox

This fictional layout matches deploy/site.private.example.json. It uses distinct management, private-services and learner networks; no original installation addresses, DNS server or hostname are included. Choose your own isolated deployment values before installation.

```text
Example LAN 10.77.1.0/24
  workstations --HTTPS 443--> 10.77.1.10 (Proxmox vmbr0)
                                  | port forward
                                  v
                           10.77.2.20 (services VM)
                           10.77.2.1  (Proxmox vmbr2 gateway)
Separate learner bridge: vmbr1 / 10.78.0.0/24
```

The services VM uses 10.77.2.20/24 with gateway 10.77.2.1. Proxmox uses 10.77.1.10 on the example LAN and forwards academy TCP/443 to the private services address. Outbound services traffic is masqueraded. The example configuration uses the public resolver 1.1.1.1; replace it with the resolver you choose for your isolated environment.

Configure academy.example.invalid as an illustrative hostname pointing to the Proxmox LAN address 10.77.1.10, rather than the private services address. The reserved .invalid example is not a working public domain. Generate a local TLS certificate for your chosen hostname and import the local CA on learner workstations. Proxmox administrative access stays on TCP/8006; the isolated learner bridge has no physical port.

Prepare a separate site.json from the example, then follow INSTALL.md and ACCEPTANCE.md. Whether a nested Proxmox host is required depends on your chosen deployment; do not create one on an already prepared host. No live Proxmox deployment was performed as part of this source privacy review.
