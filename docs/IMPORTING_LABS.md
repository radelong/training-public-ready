# Importing an offline VM lab

This workflow turns a Linux VM into a repeatable Academy lab without giving the
web application root access to Proxmox or asking an administrator to recreate
VM settings by hand. The large VM package stays on removable media. A root-only
installer on Proxmox validates the package, imports the disk, tests a disposable
clone and produces a small receipt. The Academy administration page imports the
receipt and verifies the resulting Proxmox template before publishing the lab.

## What the package contains

An Academy lab package contains only these items:

- `lab-package.json`: lab title, description, VM resources, exercises and the
  intended Proxmox template ID;
- `disk.qcow2` or `disk.raw`: the offline VM disk;
- `SHA256SUMS`: checksums for the descriptor and disk.

The package contains no Proxmox-host scripts. The installer never executes a
file from the package. This prevents a lab authoring VM from supplying commands
that run as root on the Proxmox server.

## 1. Prepare the lab VM

Use Ubuntu or another Linux distribution that supports cloud-init and the QEMU
guest agent. Build and test the VM on an isolated authoring host.

The finished VM must provide:

1. OpenSSH server and an enabled QEMU guest agent.
2. Cloud-init support. The Academy supplies the `learner` account, SSH key and
   private lab IP each time it creates a learner VM.
3. An RSA SSH host key. The Academy pins this key when opening the terminal.
4. A root-owned executable `/usr/local/sbin/academy-lab`.
5. `/usr/local/sbin/academy-lab ready` returning exit code zero only after the
   operating system and offline lab services are ready.
6. For guided exercises, the same command must accept `start`, `check`, `hint`
   and `solution` followed by the exercise ID in `lab-package.json`. A `check`
   command returns zero for a passed exercise and nonzero while work remains.
7. Every package, image, container image and dependency required by the lab.
   The learner network has no internet route.

Before export, shut down the VM cleanly. Remove temporary logs and secrets, then
run the distribution's cloud-init cleanup procedure so each clone receives a
fresh identity. Do not place instructor answer keys, production credentials or
private signing keys inside the image.

## 2. Export the disk

Export the powered-off VM as qcow2 or raw. For a KVM/libvirt VM, identify its
disk and use `qemu-img convert`. For example:

```bash
sudo qemu-img convert -p -O qcow2 /path/to/source-disk.qcow2 lab-disk.qcow2
qemu-img check lab-disk.qcow2
```

For VMware, VirtualBox or another format, use `qemu-img convert -O qcow2` after
the VM is fully shut down. Never convert a disk while the VM is running.

## 3. Describe the lab

Copy `examples/lab-package.example.json` and edit it. Use a new template VM ID
that is outside the Academy learner VM range. The fields are:

| Field | Purpose |
| --- | --- |
| `id` | Stable lowercase ID, such as `linux-fundamentals` |
| `title` | Name shown in the Academy catalog |
| `description` | Learner-facing description |
| `kind` | `linux`, `netlab` or `custom` |
| `template_id` | Unused Proxmox VM ID for the template |
| `cores` / `memory` | Resources assigned to every learner clone |
| `drills` | Optional exercises implemented by `academy-lab` |

Every exercise needs `id`, `title`, `brief`, `goal`, `tools`, `time` and `level`.
Use an empty `drills` list for an open practice workspace.

## 4. Build the package

On the Linux authoring host, use the Academy source or provision media:

```bash
sudo apt-get install -y qemu-utils
bash scripts/create-lab-package.sh \
  /path/to/lab-disk.qcow2 \
  /path/to/my-lab.json \
  /path/to/output/my-lab
```

The command validates the descriptor and disk, calculates checksums and creates
both a package directory and `my-lab.academy-lab.tar`. Copy the tar file to a
USB drive. A directory may be used instead when the USB filesystem supports the
VM disk's size and sparse-file behavior.

## 5. Install the package on Proxmox

Attach the USB drive to the Proxmox server and mount it. The exact mount command
depends on the USB filesystem and local policy. Copy or mount the Academy media
so `scripts/install-lab-package.sh` and the site's `site.json` are available.

Run:

```bash
bash scripts/install-lab-package.sh \
  /media/usb/my-lab.academy-lab.tar \
  /root/academy-bootstrap/site.json
```

The installer:

1. rejects unsafe archive paths, links and unexpected disk formats;
2. verifies every checksum before changing Proxmox;
3. refuses an occupied template ID, the services VM ID and learner VM IDs;
4. imports the disk into the site's configured lab storage;
5. configures cloud-init, VirtIO networking, QEMU guest agent and serial console;
6. converts the VM to a template;
7. creates a disposable clone and runs `academy-lab ready` through QEMU guest
   agent without requiring network access;
8. deletes the test clone and grants the Academy clone-only template role;
9. writes `*.academy-import-receipt.json` beside the package.

If any step fails, the installer removes the incomplete test/template VM and
does not produce a receipt. Read the error, fix the authoring VM or descriptor,
choose the same still-unused template ID, rebuild the package and retry.

## 6. Add it to the Academy

1. Copy the small `academy-import-receipt.json` file to the administrator's
   workstation or another approved transfer medium.
2. Sign in to the Academy as an administrator.
3. Open **Administration** or **Content manager**, choose **Add lab**, then use
   **Import installed lab package**.
4. Select the receipt. Leave **Activate immediately** clear for the first import.
5. Select **Import package receipt**. The Academy verifies that the Proxmox VM
   exists, is a template and is available to its restricted account. It then
   imports the title, description, resources and exercises.
6. In Administration, confirm the new inactive entry and resource values.

The web application never receives the disk image and cannot run package code.
It receives only the receipt and will reject a receipt whose template is absent.

## 7. Acceptance test and activation

Before activation, test one disposable clone from Proxmox or in a staging
Academy. Confirm all of the following:

- the VM boots without internet access;
- QEMU guest agent and `academy-lab ready` succeed;
- the embedded SSH terminal opens as `learner`;
- each exercise starts, reports useful hints and passes after the documented fix;
- the learner VM cannot reach the management LAN, Proxmox API or another learner;
- restore and end delete only the learner clone;
- no authoring credentials or answer keys are present.

When these checks pass, open Administration, enter the verified template ID,
select **Active**, and save the lab. The lab appears immediately in Lab catalog.

## Updating an existing lab

Build a new image with a new unused template VM ID. Import and test it as above.
Deactivate the existing Academy lab, import the new receipt using the same lab
ID, perform acceptance checks and reactivate it. Existing learner results remain
associated with the stable lab ID. Keep the previous template until active
sessions using it have ended and rollback is no longer needed.

## USB and ISO strategy

Keep the Academy installer ISO and lab packages as separate files on the same
approved USB or storage set. A new lab package does not require rebuilding the
entire multi-gigabyte Academy ISO. This makes lab updates faster and avoids
reissuing the platform installer for content-only changes. Store these together:

- the verified Academy ISO and its `.sha256` file;
- each `.academy-lab.tar` and its package `SHA256SUMS`;
- a protected copy of the matching Academy source and site backup;
- this guide.

If policy requires a single ISO, place the completed package under a
`lab-packages/` directory in the Academy source tree before running
`scripts/prepare-media.sh`. The normal media manifest will checksum it. Large lab
images increase ISO build time, copy time and required destination storage, so
the separate verified package is the recommended operating model.

