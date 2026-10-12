# Installation guide

For the installed Proxmox VM at `192.0.2.10` with the academy services VM on a separate `192.0.2.10/24` network, follow [Private services network on Proxmox](PRIVATE_NETWORK.md). The nested-Proxmox creation steps below are for the original outer-Ubuntu layout and are not used for that installation.

## 1. Prepare the site

Use an amd64 physical virtualization host that permits nested virtualization through **both** the outer Ubuntu VM and its nested Proxmox VM. The package checks CPU virtualization flags and `/dev/kvm`; a failed preflight stops deployment. The outer hypervisor must also allow the bridged networking behavior required by nested guests, including multiple guest MAC addresses. Depending on that hypervisor this may require MAC spoofing, forged-transmit or promiscuous-mode settings.

The example reserves a Proxmox VM with 12 virtual CPUs, 48 GB RAM and a 350 GB virtual disk. Allocate at least 56–64 GB RAM to the outer Ubuntu VM and sufficient disk space for the nested disk plus installation media. The services VM uses 4 CPUs, 8 GB RAM and 50 GB disk. Netlab learners use 4 GB RAM each; the inactive Linux placeholder is configured for 2 GB. Learner VMs use linked clones on thin storage, so disk use grows with each learner's changes while the base image is shared. These are planning settings, not measured performance claims. Begin with two concurrent learners and increase only after the acceptance test.

Provide:

- Ubuntu 26.04 amd64 installed as the outer VM. This outer VM installation is performed through the existing physical host/hypervisor using the official Ubuntu ISO.
- A management LAN address for Proxmox and a different address for the services VM.
- An existing Linux bridge in the outer Ubuntu VM, connected to the management LAN. The example calls it `br0`.
- A local DNS record for `academy.example.invalid`, or an equivalent workstation hosts-file entry pointing to the services management address.
- Local time synchronization or correctly set clocks. Tokens and session expiry depend on time. No public time server is required.

Copy `deploy/site.example.json` to `site.json` and edit it. The example uses management subnet `192.0.2.10/24` and an isolated learner subnet `192.0.2.10/24`. These are examples, not discovered site settings. Learner addresses `.100` onward and VM IDs `5000` onward are reserved exclusively for the academy. Template preparation temporarily uses `.20` and `.21`; services use `.10`. The lab bridge must have no physical ports and no host IP address.

Validate the file:

```bash
python3 scripts/validate-site.py site.json
```

If the outer VM has only a standard Ethernet interface, create its LAN bridge with Ubuntu netplan before running the installer. Move the outer VM's management address, route and DNS configuration from the Ethernet interface to the bridge; do not assign the same address to both. Interface names and addressing differ by site, so this package intentionally does not rewrite the outer VM's existing management network. Keep its hypervisor console open while applying that change. The required bridge state is checked before a nested VM is created.

## 2. Build removable installation media once

Use a connected amd64 Ubuntu staging computer with Docker Engine and the Docker Compose plugin, Python 3, curl and tar installed. Docker must be operational before the preparation script starts. Allow at least 30 GB free staging storage. This is the only step that accesses internet repositories.

Download a current official **Proxmox VE 9+ ISO** and obtain its SHA-256 from the [official download page](https://www.proxmox.com/en/downloads/proxmox-virtual-environment/iso). Supply that ISO and hash:

```bash
bash scripts/prepare-media.sh /path/to/proxmox-ve.iso THE_64_CHARACTER_OFFICIAL_SHA256
```

If you already have the official Ubuntu 26.04 amd64 server cloud image, copy it to the staging computer and supply its path as a third argument:

```bash
bash scripts/prepare-media.sh /path/to/proxmox-ve.iso THE_64_CHARACTER_OFFICIAL_SHA256 /path/to/ubuntu-26.04-server-cloudimg-amd64.img
```

The builder verifies the Proxmox ISO, obtains the official Ubuntu cloud-image checksum list, and verifies either the supplied local image or a freshly downloaded image. It gathers Ubuntu package dependency closure into a local apt repository, downloads Python wheels, builds the application and Linux practice image without network access during those builds, and exports all service container images. Image identities and digests are recorded in `assets/image-lock.json`. The manifest records checksums for the resulting application and dependency files.

Before releasing media, the builder starts an isolated PostgreSQL/Guacamole test stack. It checks concurrent session requests, real Guacamole JSON authentication, token ownership and revocation. It also runs all six Linux exercises, verifies they fail before repair and pass after repair. Any failure stops the build before a complete manifest is produced. The checks use no real Proxmox VMs.

The resulting files are:

| File | Purpose |
| --- | --- |
| `release/training-academy-offline-amd64.tar.gz` | Complete application and dependency bundle |
| `release/academy-provision.iso` | Read-only installation media attached to Ubuntu guests |
| `release/academy-provision.iso.sha256` | Provision ISO integrity check |

Copy all three files and `site.json` onto a 32 GB or larger removable drive. Use exFAT, ext4 or a similarly suitable filesystem; FAT32 cannot hold a file larger than 4 GB. Keep the original source release separate from prepared media, and keep media containing site credentials under local administrative control.

The builder requires a valid official Ubuntu 26.04 image and package repository. If the release or a required image/package is unavailable, it fails rather than substituting another Ubuntu release. Only amd64 is included in this release.

## 3. Create the nested Proxmox VM on Ubuntu

On the offline outer Ubuntu 26.04 VM, mount the drive, extract the archive into a path without spaces, and verify it. Example:

```bash
sudo mkdir -p /opt/academy-media
sudo tar -xzf /media/usb/training-academy-offline-amd64.tar.gz -C /opt/academy-media
python3 /opt/academy-media/scripts/verify-media.py /opt/academy-media
sudo bash /opt/academy-media/scripts/create-nested-proxmox.sh /opt/academy-media /media/usb/site.json
```

The installer obtains KVM, libvirt and VM creation tools from the file-based repository on the media. It creates a **new** disk under `/var/lib/libvirt/images/academy/`, copies the Proxmox ISO into libvirt-readable storage and launches the nested VM with host CPU passthrough. It refuses an existing VM name or disk. It does not repartition the outer Ubuntu disk.

If KVM's nested setting was disabled before its module was loaded, the installer writes the nested setting and asks for an outer-VM reboot. It does not unload an active KVM module. Reboot the outer VM, then rerun. If the physical host has not exposed the CPU features to Ubuntu, correct that at the physical hypervisor first.

Open the nested VM's VNC console to complete the official Proxmox installer. It listens only on the outer Ubuntu VM's loopback address. Find the display:

```bash
sudo virsh --connect qemu:///system vncdisplay academy-proxmox
```

A display of `127.0.0.1:0` means TCP port 5900. Access it with an existing VNC viewer locally, or through an SSH tunnel from an administrator workstation:

```bash
ssh -L 5900:127.0.0.1:5900 administrator@OUTER_UBUNTU_IP
```

Connect the viewer to `127.0.0.1:5900`. Use the actual display port if it differs. A VNC viewer or Ubuntu GUI console access is an administrator prerequisite; the portal itself cannot supply the initial installer console before it has been installed.

In the stock Proxmox installer, select the newly created blank virtual disk and enter the hostname, IP, gateway and local DNS specified in `site.json`. Choose the normal local-LVM layout if using the example `local-lvm` storage. Set a strong Proxmox root password. Proxmox installs its own Debian-based operating system; it is not installed as Ubuntu software.

After installation completes, eject the installer ISO from the outer Ubuntu VM before booting the installed disk:

```bash
sudo bash /opt/academy-media/scripts/finish-nested-proxmox.sh /opt/academy-media /media/usb/site.json
```

This checks the nested VM's ownership description and detects its CD-ROM target before ejecting only that virtual installation medium. Confirm in the Proxmox console that `/dev/kvm` exists and `vmx` or `svm` appears in `/proc/cpuinfo`. The nested Proxmox VM must be able to start KVM guests before continuing.

## 4. Bootstrap Proxmox and its Ubuntu guests

Transfer the complete archive, provision ISO, checksum sidecar and site file onto the Proxmox node. A removable drive can be attached through the existing hypervisor, or an administrator can copy the files over the local management LAN. Internet access is not required. Extract the archive into a path without spaces.

```bash
mkdir -p /root/academy-media
tar -xzf /path/to/training-academy-offline-amd64.tar.gz -C /root/academy-media
bash /root/academy-media/scripts/bootstrap-proxmox.sh \
  /root/academy-media /path/to/site.json /path/to/academy-provision.iso
```

Use a dedicated, empty Proxmox node. The script refuses a populated node and refuses to repeat an existing partial bootstrap automatically. It creates:

- An isolated `vmbr1` bridge with no physical ports.
- A provisioning user/API token scoped to the reserved learner VM IDs, approved templates, selected storage and learner bridge. It receives no authority over the services VM or unrelated VM IDs.
- An Ubuntu 26.04 networking template and an Ubuntu 26.04 Linux/Docker template.
- The Ubuntu 26.04 services VM, with one management NIC and one learner-network NIC.

Guest installation uses cloud-init and the attached read-only provision ISO. The Netlab template installs the lab files, local packages and console support. A generic Linux base template is also built but is not the site's future Linux training content and must remain inactive until that content is supplied. Preparation cleans cloud-init identity, removes bootstrap SSH authorization and host keys, detaches installer/custom cloud-init data, and converts each stopped guest into a template. New learners receive a new SSH key and newly generated guest host keys.

The services guest installs Docker and loads all service images from the ISO, creates local credentials and TLS certificates, and starts the application. The script waits for guest completion markers; a failed first boot stops the process with the VM preserved for diagnosis. Inspect `/var/log/cloud-init-output.log` inside that guest if needed.

Bootstrap state and the restricted API token are in `/root/academy-bootstrap/` on Proxmox. Keep that directory private. The services site file also contains this restricted token. It is not part of the general installation media.

## 5. Open the portal and activate labs

From the Proxmox root console, retrieve the initial academy credential through the guest agent (use the actual services VM ID):

```bash
qm guest exec 9000 -- /bin/cat /opt/training-academy/secrets/initial-admin.txt
```

The returned JSON contains the credential in `out-data`. Alternatively, SSH from Proxmox using the root-controlled bootstrap key:

```bash
ssh -i /root/academy-bootstrap/bootstrap-key learner@SERVICES_MANAGEMENT_IP
```

This SSH account is an administrator on the services VM, not an academy learner account. After SSH sign-in, retrieve:

```bash
sudo cat /opt/training-academy/secrets/initial-admin.txt
```

Copy `/opt/training-academy/secrets/local-ca.crt` to the approved learner workstations and import it into their trusted certificate stores. Configure local DNS or hosts entries to resolve the site's academy hostname to its management IP. The generated server certificate covers the hostname and services management IP. Only TCP 443 is published by the application stack. Proxmox TCP 8006 remains on the management network for administration and backend access.

Open `https://academy.example.invalid` using the actual configured hostname. Sign in with the generated local administrator account and change its password through My account. Administration shows only Kubernetes Networking Lab (Netlab) and Linux Lab. Activate the Netlab template after its ready networking/firewall exercises pass offline checks. Keep Linux Lab inactive until the site's own Linux training template is uploaded and validated. Activation confirms a VM is marked as a Proxmox template. Complete the acceptance checks before adding general learner accounts.

Learners start labs from the catalog. Starting a lab queues a linked clone and boots a private Ubuntu VM; the terminal is then embedded in the workspace through Guacamole. Linux learners start an exercise and enter its container with `docker exec -it academy-linux bash`. Restoring a VM replaces its disk from the template. Ending the lab destroys its VM and frees its seat. Results remain in PostgreSQL.

The Netlab template includes offline K3s and the workload images for its 28 exercises. Validate the deployment with internet disconnected. No other capability entries appear in this two-lab catalog. No external courses are embedded or linked.

## 6. Installing services onto an existing Ubuntu services VM

The normal bootstrap creates this VM automatically. For a manually prepared Ubuntu 26.04 VM on the same Proxmox node, give it the management and learner NICs, copy the complete bundle and the credential-bearing site JSON from `/root/academy-bootstrap/site.json`, then run:

```bash
sudo bash MEDIA/scripts/install-services.sh MEDIA CREDENTIAL_BEARING_SITE.json
```

The installer requires the configured Proxmox CA and API token. It refuses to replace an existing `/opt/training-academy/.env`. It installs packages using only the local repository and starts images with `--pull never`.

## 7. Recovery and maintenance

For a learner VM error, inspect its node task log. The portal exposes Retry preparation and End lab once the current job finishes. The worker can reconcile an existing clone using its ownership marker. If the marker differs, it refuses to modify the VM. Resolve the reservation conflict administratively; do not override that check.

After a failed node bootstrap, inspect the created VMs and root-controlled state. Do not rerun the bootstrap by deleting its guard directory. Continue the failed guest operation manually using its cloud-init log, or rebuild the dedicated training node after preserving needed data. The bootstrap is an initial installation workflow, not a general-purpose rerunnable node repair tool.

Back up the database and configuration together:

```bash
sudo /opt/training-academy/backup.sh /path/to/backup-directory
```

Also use Proxmox backups for the services VM and approved templates. The database/config backup does not include learner VM disks or template disks. Restore procedures are in `OPERATIONS.md`.

Refresh images and packages on a connected staging computer, build and validate new media, then transfer it through the site's approved process. Keep the database master key and existing `.env` during application updates. This release has no schema migration engine; a future schema change must include a migration before upgrade. Renew the local server certificate before its one-year expiry, or replace it with a site-issued certificate using the same hostname/SANs.


## Class content and existing-installation upgrades

Use Administration → Manage classes and upload slides, or Content manager in the navigation. Upload locally exported PDF slides, arrange modules, link approved labs, enter exam questions and answer keys, then publish a reviewed version. See `ADDING_TRAINING.md` for the complete workflow.

For an existing deployment, extract the newly verified media in the services VM and run `sudo bash scripts/upgrade-services.sh EXTRACTED-MEDIA`. The script preserves site settings, lab activation, templates, enrollments and results; it saves application, database, private configuration and uploaded-content recovery files before the short service interruption. Learner VMs are retained, but an open terminal may need Reconnect after the upgrade.
