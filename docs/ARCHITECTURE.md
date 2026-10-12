# Architecture and storage

## Application components

| Component | Responsibility | Location |
| --- | --- | --- |
| Local frontend | Catalog, exercise briefs, controls, embedded terminal, results and administration | Served from the Ubuntu services VM |
| HTTPS reverse proxy | TLS termination and browser/WebSocket forwarding | Nginx container on services VM; only published application port is 443 |
| API and console gateway | Local authentication, authorization, VM requests, results and token-bound console traffic | FastAPI container on services VM |
| Worker | Reconciles and executes queued VM/exercise actions | Separate container on services VM |
| PostgreSQL | Local users, login sessions, lab definitions, jobs, exercise results and audit events | Named Docker volume on services VM |
| Guacamole web application | Browser terminal protocol and JSON-authenticated SSH connection definitions | Internal container on services VM |
| guacd | SSH connection to the assigned learner VM | Container with access to the learner subnet through services VM |
| Proxmox/KVM | Cloning, guest power, storage, guest-agent commands and VM firewall rules | Nested Proxmox VM, or a dedicated physical node |

The separate-Proxmox-VM option can place the services VM on an internal `192.0.2.10/24` bridge while exposing only HTTPS through the node's LAN IP. Its exact addresses and verification steps are in [Private services network on Proxmox](PRIVATE_NETWORK.md).

## What happens when a learner starts a lab

1. The API checks the learner's local login, CSRF token, lab availability, personal session limit and available seats.
2. A PostgreSQL transaction reserves a learner VM ID and IP address. Repeated requests for the same active lab return the existing session.
3. A durable job records the requested launch. The elected worker generates a unique SSH key, stores its private half encrypted with the local master key, and clones the approved template.
4. The clone carries `academy-session:<session UUID>` in its Proxmox description. The worker checks that marker before changing, executing against or deleting that VM.
5. The worker sets the learner's IP/key through cloud-init, configures external VM firewall rules, boots the guest and waits for its guest-agent lab readiness check.
6. The guest's SSH host key is obtained through the trusted Proxmox guest-agent channel. Guacamole uses that known-host entry rather than accepting an unknown host.
7. Connecting the terminal mints a short-lived Guacamole JSON authentication request server-side. The API returns an embedded console URL with a scoped connection token, not the Proxmox token or plaintext SSH private key.
8. The gateway checks the academy login, console grant, VM ownership, current VM generation and expiry. WebSocket authorization is rechecked every two seconds. HTTP tunnel reads/writes are bound to the same login/token and rechecked while streamed.

Provisioning runs serially in this first release. The worker holds a PostgreSQL advisory election lock, so multiple worker containers do not provision simultaneously. A crashed worker releases its lock; its successor requeues interrupted jobs. Existing marked clones can be reconciled. No distributed high-availability claim is made.

## Where each VM is saved

Proxmox owns the learner disks on the configured storage, normally `local-lvm`. With the default LVM layout, these are logical volumes such as `vm-5000-disk-0`, not ordinary files on the web server. Proxmox's VM configuration is under `/etc/pve/qemu-server/<VMID>.conf`. The application makes a linked clone from an immutable template: each learner has a private writable disk layer, while common base blocks remain in the template. Preserve the base template until its learner clones have ended. The selected storage must support linked clones.

In the requested nested layout, all those volumes physically sit inside the **Proxmox VM's virtual disk**, which is stored by libvirt on the outer Ubuntu VM at `/var/lib/libvirt/images/academy/academy-proxmox.qcow2`. That file, in turn, resides on the outer Ubuntu VM's disk on the physical virtualization host. This adds storage and I/O overhead. Use sufficiently fast local storage and measure concurrency on the actual host.

The services VM's root disk is also managed by Proxmox. Its application database is a Docker volume inside that services VM, normally under `/var/lib/docker/volumes/`. Container layers and loaded image archives do not store learner VM disks. A learner's files remain in its VM while that session exists; ending or restoring the VM deletes those working files. Recorded results remain in PostgreSQL.

The original netlab creates client/router/server network namespaces **inside each learner VM**. Those namespace addresses are not the management or learner-console subnet. Linux practice creates a Docker container inside that individual learner VM, with no container network, a memory/CPU/process limit and no host mounts. Learners may administer their disposable VM; they never receive Docker access to the services VM.

## Network boundaries

The services VM has two NICs: a management-LAN address for browser/backend access and `192.0.2.10` on the isolated learner bridge. Learner VMs have one NIC on that bridge, no default gateway, an assigned IP and a Proxmox firewall policy that drops new inbound/outbound traffic except SSH arriving from the services VM. Stateful return traffic is handled by Proxmox. MAC/IP filtering is enabled to limit spoofing from a guest with root access. The node firewall must actually be running for those rules to protect the bridge; the acceptance test proves this from two real guests.

Browser requests go to the portal over HTTPS. Console traffic remains inside the page and follows browser → Nginx → authenticated gateway → Guacamole/guacd → assigned learner VM. No learner connects directly to the Proxmox API. The worker executes fixed, catalog-selected exercise actions through the QEMU guest agent; the API never runs arbitrary learner-supplied commands on the services host.

PostgreSQL and the Guacamole web container use an internal Docker network and publish no host ports. The API/worker require a separate management-capable Docker network for the local Proxmox API. guacd requires a separate network for SSH to learner VMs. Local routing/firewall policy should keep the installation in the site's designated training networks. Internet independence means the stack needs no external service; physical network separation and enterprise boundary enforcement remain site network responsibilities.

## Expiry, resets and failure behavior

A session lasts the configured number of hours and is released by the worker after expiry. An API job already in progress is allowed to finish before release is queued. Console access stops at expiry regardless of cleanup progress. Error VMs keep their seat reservation until they are ended or their expired session is cleaned up; capacity is not silently reused while a possibly existing VM remains.

Restoring a clean VM deletes the old clone and creates a new baseline copy at the reserved VM ID. Its generation and SSH credentials change, which invalidates old console grants. Reconnecting during an ordinary active session retains the existing VM. Ending deletes the owned VM and clears its credentials, but retains results and audit records.

Timeouts preserve the VM for reconciliation. A missing/foreign ownership marker causes a refusal, not forced cleanup. Provider errors are recorded as failed jobs with a short operator-facing message. Inspect the detailed Proxmox task/guest logs through administrative access.

## Completing the two local labs

Administrators can add inactive lab records and exercise JSON through Content manager or Administration. A prepared Proxmox template is still required: adding a catalog entry does not build a VM. The template must provide SSH, cloud-init, the QEMU guest agent and the academy guest integration contract. Register the validated template with `scripts/register-template.sh` before activation so the restricted provisioning account can audit and clone it.

Netlab includes 28 networking, firewall and Kubernetes exercises. The package contains the pinned K3s runtime and required workload images. A clean offline clone passed a networking and Kubernetes drill; the complete exercise sequence remains a site acceptance task.

Class catalog stores draft and immutable published course versions in PostgreSQL. Local PDF slides reside in the services VM content directory and are served only to authenticated, authorized users. Published modules can link to existing private labs. Objective exams are graded on the server; written responses require an administrator rubric and manual review. Learner responses, progress and results stay local. Required module completion is learner-confirmed, not proof of viewing every slide or passing a lab. Backups include both PostgreSQL and the PDF content directory.

For the later Linux Lab upload, inventory its approved dependencies and files, then create an offline Ubuntu template that follows the academy guest integration contract. The generic Linux base VM built during bootstrap is not the uploaded training environment. Register the final template with the restricted provisioning user before activating the Linux Lab entry. Other capability labs are outside this two-lab catalog; organization-specific artifacts from PROTON were not available in this workspace.

## Technical references

- [Proxmox installation model](https://www.proxmox.com/en/products/proxmox-virtual-environment/get-started): official ISO installs a complete Debian-based system.
- [Proxmox requirements](https://www.proxmox.com/en/products/proxmox-virtual-environment/requirements): virtualization and nested-testing requirements.
- [Proxmox API source](https://git.proxmox.com/?p=qemu-server.git;a=tree;f=src/PVE/API2;hb=HEAD): clone, cloud-init, power and guest-agent endpoints.
- [Proxmox HTTP API server](https://git.proxmox.com/?p=pve-http-server.git;a=tree;f=src/PVE/APIServer;hb=HEAD): JSON POST/PUT handling and query parameters for DELETE.
- [Guacamole JSON authentication](https://guacamole.apache.org/doc/gug/json-auth.html): encrypted HMAC/AES connection definitions and expiry.
- [Guacamole SSH configuration](https://guacamole.apache.org/doc/gug/configuring-guacamole.html#ssh): private-key and known-host verification.
- [Ubuntu 26.04 cloud images](https://cloud-images.ubuntu.com/releases/26.04/release/): official guest images and checksums.
