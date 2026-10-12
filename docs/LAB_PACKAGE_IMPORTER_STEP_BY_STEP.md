# Training Academy — Lab Package Importer

## Read this first

Adding a lab has two parts: **install its VM image on Proxmox**, then **import the installation receipt into Academy Administration**. The Academy upload button takes a small JSON receipt. It does not take an ISO, a VM disk, a PowerPoint file, or an ordinary software deployment ZIP.

If your lab currently exists as an installation bundle on a USB drive, first install that bundle in a Linux authoring VM. Test it there, export that VM's disk, and follow this guide. The exported disk becomes the reusable base for each learner's private VM.

The Academy platform does not need to be reinstalled when you add a lab.

**Choose your starting point:** if you have only a software deployment bundle, start at step 1. If you already have an `.academy-lab.tar` built with this Academy's package creator, start at step 7. If Proxmox has already installed it and given you an `.academy-import-receipt.json`, start at step 10.

| Where you work | What you do there |
| --- | --- |
| Linux authoring machine | Build the lab VM, export its disk, create the package |
| Proxmox server | Import the package and create a validated VM template |
| Administrator's browser | Upload the receipt and publish the lab |

In the examples below, `~/academy-source` means the folder containing the Academy's `scripts` and `examples` directories. Replace it with the actual extracted source or mounted media folder. Example lab name: **Linux Lab**. Example template VM ID: **9100**, which must be unused.

## 1. Collect the files and access you need

- The current Academy source package or provision media, including `scripts/create-lab-package.sh`, `scripts/install-lab-package.sh`, and `scripts/validate-site.py`.
- A Linux authoring host with Python 3, `qemu-img`, `tar`, and `sha256sum`.
- The completed Linux lab VM, with all dependencies installed locally.
- A USB drive or other approved transfer storage. Use a filesystem that supports files larger than 4 GB; FAT32 is unsuitable for large VM packages.
- Root access to Proxmox and an Academy administrator account.
- The deployed site's configuration file on Proxmox, normally `/root/academy-bootstrap/site.json`. Confirm the actual path before importing.

Keep the Academy source directory intact. The Proxmox installer calls `validate-site.py` beside it, so copying only `install-lab-package.sh` is insufficient.

## 2. Build and test the Linux lab VM

Create the authoring VM using a **legacy BIOS boot configuration** and a normal VirtIO-compatible Linux installation. The current importer creates a BIOS-based template; it does not import UEFI/OVMF settings or a separate EFI disk. A VM originally installed for UEFI must be made BIOS-bootable and tested before using this importer.

Install your lab's deployment bundle inside the VM. Include every required package, service, container image, exercise, and dataset. Disconnect its internet access and verify the lab still works.

For an Ubuntu authoring VM, install the Academy integration prerequisites while internet or your local package repository is available:

```bash
sudo apt-get update
sudo apt-get install -y openssh-server cloud-init qemu-guest-agent
sudo systemctl enable --now ssh
sudo systemctl enable qemu-guest-agent
sudo ssh-keygen -A
```

Enable the VM's QEMU guest-agent channel in the authoring hypervisor. In Proxmox, enable **Options → QEMU Guest Agent**. The service cannot communicate with the host without that channel.

Cloud-init must accept Proxmox's configuration drive. Do not hard-code the final learner VM's address or permanently disable cloud-init. The Academy supplies the `learner` account, SSH key, and isolated address when launching a session.

## 3. Add the Academy readiness command

Every lab image must contain a root-owned executable at:

```text
/usr/local/sbin/academy-lab
```

The importer runs `academy-lab ready` in a fresh test clone. Exit code **0** means ready; any other exit code means the lab is not ready. A successful check should verify the services needed by the lab, not simply return success before they start.

For a simple Linux practice VM with no guided exercises, this is a minimal starting point. Add checks for your own lab services before using it for a more complex environment:

```bash
sudo tee /usr/local/sbin/academy-lab >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  ready)
    systemctl is-active --quiet ssh
    test -s /etc/ssh/ssh_host_rsa_key.pub
    ;;
  *)
    echo 'This lab is an open practice workspace.' >&2
    exit 2
    ;;
esac
EOF
sudo chown root:root /usr/local/sbin/academy-lab
sudo chmod 0755 /usr/local/sbin/academy-lab
sudo /usr/local/sbin/academy-lab ready
echo $?
```

Expected result: `0`. Other Linux distributions may use a different SSH service name.

For guided exercises, implement these commands in the same executable:

```text
academy-lab start EXERCISE_ID
academy-lab check EXERCISE_ID
academy-lab hint EXERCISE_ID
academy-lab solution EXERCISE_ID
```

The exercise IDs must match the descriptor in step 5. `check` returns 0 only when the learner has met the goal. Hints and solutions print useful learner-facing text. Start/check operations must apply to this learner's VM only.

## 4. Clean, shut down, and export the disk

Remove authoring credentials, temporary files, personal data, and production secrets. Preserve the lab's intended training files. Clean cloud-init state so each clone can initialize itself, then shut down:

```bash
sudo cloud-init clean --logs --machine-id
sudo shutdown -h now
```

Do not start the authoring VM again before exporting. On the authoring host, convert the powered-off VM disk to a self-contained qcow2 file:

```bash
mkdir -p ~/academy-lab-build
sudo qemu-img convert -p -O qcow2 \
  /path/to/powered-off-vm-disk \
  ~/academy-lab-build/linux-lab.qcow2
sudo qemu-img check ~/academy-lab-build/linux-lab.qcow2
```

Replace `/path/to/powered-off-vm-disk` with the actual disk path. `qemu-img convert` flattens supported source formats and backing chains into the new output. Never export a disk while its VM is running.

## 5. Describe the lab

Copy the descriptor example:

```bash
cp ~/academy-source/examples/lab-package.example.json \
  ~/academy-lab-build/linux-lab.json
nano ~/academy-lab-build/linux-lab.json
```

For an open Linux workspace that fills the existing **Linux Lab** placeholder, use:

```json
{
  "id": "linux",
  "title": "Linux Lab",
  "description": "Practice Linux administration in a private offline VM.",
  "kind": "linux",
  "template_id": 9100,
  "cores": 2,
  "memory": 4096,
  "drills": []
}
```

Using `id: "linux"` updates the existing inactive Linux entry. A different ID creates another catalog entry. Leave Netlab's ID and template unchanged.

Check the proposed template ID on Proxmox:

```bash
qm list
test ! -e /etc/pve/qemu-server/9100.conf && echo 'Template ID is unused'
```

Choose another unused ID if 9100 exists. Avoid the services VM and the site's reserved learner VM range. Do not overwrite an existing VM to make an ID available.

Resources are assigned to each learner clone: `memory` is in MB, `cores` is the vCPU count. For guided labs, replace `drills: []` with the exercise records from the provided example. Each record needs `id`, `title`, `brief`, `goal`, `tools`, `time`, and `level`.

## 6. Build the portable lab package

On the Linux authoring host:

```bash
cd ~/academy-source
bash scripts/create-lab-package.sh \
  ~/academy-lab-build/linux-lab.qcow2 \
  ~/academy-lab-build/linux-lab.json \
  ~/academy-lab-build/linux-lab-package
```

The output path must not already exist. The command validates the descriptor, copies the disk, calculates checksums, and creates:

```text
linux-lab-package.academy-lab.tar
```

It also keeps a package directory containing `lab-package.json`, `disk.qcow2`, and `SHA256SUMS`. Verify it:

```bash
cd ~/academy-lab-build/linux-lab-package
sha256sum -c SHA256SUMS
```

Both checks should report `OK`. Copy the `.academy-lab.tar` file to the USB drive. Safely eject the drive after copying finishes.

## 7. Copy the package to Proxmox

Connect the USB to the Proxmox system. If Proxmox itself is a VM, make the USB or its files available inside that VM using your outer hypervisor's approved transfer method.

Identify the correct device before mounting:

```bash
lsblk -f
mkdir -p /media/academy-usb
```

Mount the actual USB partition at `/media/academy-usb`; the device name and mount options depend on its filesystem. Do not assume a particular `/dev/sdX` name and do not format the drive.

Copy the package into a writable staging directory on the HDD-backed bulk storage:

```bash
mkdir -p /root/academy-lab-packages
cp /media/academy-usb/linux-lab-package.academy-lab.tar \
  /root/academy-lab-packages/
df -h /root/academy-lab-packages /var/tmp
```

Importing a tar package temporarily extracts its disk under `/var/tmp`. Allow room for that extracted package as well as any copied tar. The site's `pve_storage` setting determines the final template and clone storage; your live deployment uses `academy-fast` for lab VM disks. Bulk package files can remain on HDD storage.

## 8. Install and validate the template

On Proxmox, as root, change to the extracted Academy source/media directory. Confirm that the scripts and deployed configuration exist:

```bash
ls scripts/install-lab-package.sh scripts/validate-site.py
ls /root/academy-bootstrap/site.json
```

Then run:

```bash
bash scripts/install-lab-package.sh \
  /root/academy-lab-packages/linux-lab-package.academy-lab.tar \
  /root/academy-bootstrap/site.json
```

Use the real site configuration path if it differs. Do not substitute the generic example configuration: it may select the wrong storage, bridge, or VM range.

The installer verifies the package and disk, creates the template, boots a disposable clone, and checks the QEMU guest agent and `academy-lab ready`. It allows approximately ten minutes for readiness. It removes the test clone after success and grants the Academy permission to clone the template.

Successful output includes:

```text
LAB_PACKAGE_INSTALLED
Template VM: 9100
Academy receipt: /root/academy-lab-packages/linux-lab-package.academy-lab.tar.academy-import-receipt.json
```

If it fails, do not activate the lab. The installer attempts to remove the incomplete VMs it created. Check the reported error and confirm cleanup in Proxmox before retrying.

## 9. Copy the receipt to your workstation

The receipt is a small `.json` file; it is the file you upload to the Academy. Copy it to the USB drive or your approved workstation transfer location. For a writable mounted USB:

```bash
cp /root/academy-lab-packages/linux-lab-package.academy-lab.tar.academy-import-receipt.json \
  /media/academy-usb/
```

If copying as a non-root user, root must grant that user access to this specific receipt. Do not change permissions on the entire Proxmox home directory.

## 10. Import the receipt in Administration

1. Open the Academy and sign in as an administrator.
2. Open **Administration** or **Content manager**.
3. Choose **Add lab**.
4. Find **Import installed lab package**.
5. Select the `.academy-import-receipt.json` file from step 9.
6. Leave **Activate immediately** unchecked for the first import.
7. Choose **Import package receipt**.
8. Confirm that **Linux Lab** now references template **9100**, with the expected cores, memory, description, and exercises.

The Academy checks that the referenced Proxmox VM exists and is a template. A receipt alone cannot create the VM; step 8 must succeed first.

## 11. Test before releasing it to learners

The installer checks that a clone boots and reports ready. It does not prove that every exercise, terminal interaction, or application works.

Prefer a staging Academy for a first browser test. If testing in the live Academy, use a maintenance window with no learners launching this lab: briefly activate the new entry, save it, and start a session using a dedicated test account. This is necessary because inactive labs cannot be launched from the learner catalog.

Verify:

1. A private VM starts and reaches Ready without internet access.
2. The embedded terminal accepts commands and restores focus after clicking away.
3. The intended lab files, applications, and local services are available.
4. Guided exercises can start, provide hints/solutions, and pass a work check.
5. The clone cannot reach the management LAN or another learner's VM.
6. Ending the test session removes its learner VM and leaves template 9100 intact.

If anything fails, deactivate the entry and correct the image before learners use it. After the test passes, leave **Active** selected and save. Learners can then launch it from **Lab catalog**.

## 12. Update or roll back later

For a new lab version, build a new disk and use a new unused template VM ID, such as 9101. Keep the stable lab ID `linux`. Deactivate the lab, import the new receipt, test, and reactivate. Do not remove the previous template while sessions still depend on it.

For rollback, deactivate the lab, select the previous validated template ID and its matching resource settings, save, test, then reactivate. Preserve the previous image, descriptor, receipt, and checksums with your backup.

## Common problems

| Message or symptom | What to check |
| --- | --- |
| Upload refuses an ISO, ZIP, or tar | Upload the installation receipt JSON, not the VM package. |
| `qemu-img` missing | Install `qemu-utils` on the authoring host while package sources are available. |
| Output path already exists | Choose a new output directory; do not mix packages. |
| Template ID already exists | Use an unused VM ID and rebuild the package descriptor. |
| Checksum mismatch | Re-copy or rebuild the package; do not bypass validation. |
| VM does not boot | Check BIOS compatibility, bootloader, VirtIO drivers, and self-contained disk export. |
| Readiness check times out | Check guest-agent channel/service and `academy-lab ready` in a fresh clone. |
| Template imported but terminal fails | Check cloud-init, SSH service, RSA host key, and the `learner` account/key. |
| Lab requires internet | Add the missing packages/images/data in the authoring VM and rebuild. |
| Not enough disk space | Check both HDD extraction space and free capacity in configured lab VM storage. |
| Receipt upload says template is missing | Confirm the Proxmox installation succeeded and the Academy targets the same Proxmox node. |
| Inactive lab cannot start | Test in staging or briefly activate during a controlled maintenance test. |

## Keep these files in your backup

Store the lab `.academy-lab.tar`, its original descriptor, its receipt, the matching Academy source/media, the deployed site configuration, and this guide. Protect the backup according to the lab's content. Cloudflare access is optional; this entire import and lab workflow can run offline on the local network.
