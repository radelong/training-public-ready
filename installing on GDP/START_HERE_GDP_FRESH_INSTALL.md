# Install the Training Academy on a new GDP server

This package is a candidate for installing the Training Academy on a **dedicated, empty Proxmox VE 9 node**. It includes one Ubuntu 26.04 services VM for the frontend and backend, ten learner classes, two 80-question assessments, all six learning games, and four lab experiences: Netlab, Linux Lab, the paired Callback Lab, and the 18-exercise Docker Troubleshooting Lab. It creates one new administrator and starts with no learner accounts, results, attempts or bug reports. It excludes video files and Cloudflare configuration. The candidate still needs an empty-node installation and acceptance test. The installer applies current application updates 41, 42 and 43 in order; other numbered update folders are historical recovery material and must not be replayed over this consolidated install.

**Release gate:** the installer has not passed a complete empty-node acceptance run yet. Keep this package in testing until the acceptance record is added. Never point it at the current production Proxmox node.

## 1. Prepare the server

1. Copy the complete extracted `installing on GDP` folder to an exFAT or NTFS drive with at least 64 GB capacity. Keep every folder and file together; do not copy only an installer script. FAT32 cannot store the multi-gigabyte files. The new GDP server does not need access to the current Academy LAN.
2. Boot the **new server** from `00_Proxmox_Installer/proxmox-ve_9.2-1.iso`. In the Proxmox installer, choose the intended target disk. This OS step overwrites that disk, so confirm the server and disk before continuing. Set the Proxmox administrator password, LAN IP, gateway, DNS and hostname in that installer.
3. Sign in to Proxmox at `https://PROXMOX_LAN_IP:8006` from an administrator workstation. Confirm that the node has no VMs or containers, has active VM disk storage and directory storage for ISOs, and has working hardware virtualization. If Proxmox itself runs as a VM, expose Intel VT-x or AMD-V through its outer hypervisor.
4. For a small pilot, plan around 12 CPU cores, 48 GiB RAM and at least 350 GiB usable storage. This is a planning baseline, not a capacity guarantee; keep SSD-backed storage for VM templates and learner clones where available.
5. Decide the Academy LAN hostname after you know the new LAN. Add a local DNS A record pointing that name to the **Proxmox LAN IP**. If local DNS is not ready, add a temporary hosts-file entry on each test device for that hostname and IP. Use the hostname in the browser because the local TLS certificate is issued for it. The Academy's separate services VM uses a private IP that learner workstations should not use.

## 2. Run the installer

1. At the **new Proxmox root console**, insert the drive. Run `lsblk -f` and identify the removable-media partition by its size and filesystem. Confirm its device name before mounting it. Do not select a Proxmox system disk. Mount the chosen partition read-only, for example `mkdir -p /mnt/gdp && mount -o ro /dev/sdX1 /mnt/gdp`, replacing `/dev/sdX1` with the partition you identified.
2. Change to the `installing on GDP` directory on that drive. For example, if it is at the drive root, run `cd '/mnt/gdp/installing on GDP'`. Run `bash ./Install-GDP-Academy.sh`. The script verifies all fresh-install files, including both ISO media files, the offline Ubuntu image and dependencies, four sealed lab backups, Docker lab image, protected class material and six game files. Keep the drive mounted until it finishes.
3. Answer the Academy site prompts. Enter the Academy hostname, LAN CIDR and DNS resolver, active Proxmox VM disk and ISO storage IDs, private services subnet and isolated learner bridge. The included lab images require `10.44.0.0/24` for the learner network. The private services subnet must differ from both that network and the LAN. Defaults are suggestions, not proof that an IP or bridge is free. The wizard reads the new Proxmox LAN address as a default; it does not use the current Academy address.
4. Leave the console open. The installer creates the Ubuntu 26.04 services VM, restores the four sealed templates, builds Docker template 9200 and verifies a disposable clone, applies the base application update and current application updates 41, 42 and 43 in order, imports ten learner classes, the assessments, six games and four lab catalog entries. It stops on a failed checksum, unsafe network choice, missing service or unexpected existing VM. Do not rerun after a partial failure; preserve its output and inspect the recovery state first.

If a Windows administrator computer is later available on the **new GDP LAN**, you may instead double-click `Install-GDP-Academy.cmd` there. Enter the new Proxmox IP, compare the SSH host-key fingerprint with its local console before accepting it, and enter the root password in OpenSSH. The Windows launcher transfers the same files and invokes the same Proxmox installer; it does not save the root password.

The frontend, API, database and embedded terminal service run together in the services VM. The Ubuntu guest disk image and offline dependencies are inside `30_Current_Offline_Media_2026-10-26`; separate frontend and backend ISOs are not required.

## 3. Sign in on the LAN

1. In the Proxmox root shell, display the initial administrator credential **only on your own console**:

   ```bash
   qm guest exec 9000 -- /bin/cat /opt/training-academy/secrets/initial-admin.txt
   ```

   Keep that password private. Change it through Academy Administration after first sign-in.
2. Save the generated Academy local CA certificate from the services VM to the Proxmox host:

   ```bash
   qm guest exec 9000 -- /bin/cat /opt/training-academy/secrets/local-ca.crt | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r.get("exitcode")==0 and not r.get("out-truncated"); print(r["out-data"],end="")' > /root/academy-local-ca.crt
   ```

   Copy `/root/academy-local-ca.crt` to approved learner devices and add it to their trusted root certificate store. The certificate is public; do not copy the private `.key` file. Open `https://YOUR_ACADEMY_HOSTNAME` after DNS and trust are in place. Do not bypass a browser certificate warning.
3. Sign in as the new administrator and create learner accounts. Proxmox management remains at `https://PROXMOX_LAN_IP:8006` for administrators only.

## 4. Accept the new installation

Before giving learners access, confirm all ten classes open their slides and score module quizzes and finals; Academy Overall and Graduation each draw from 80 questions; and all six games open. Verify Netlab (28 exercises), Linux Lab (23), Callback Lab (10), and Docker Troubleshooting Lab (18). Launch each lab, verify the embedded terminal (both Sender and Listener for Callback), complete one guided exercise, then end it and confirm its VM is cleaned up. Use two test learners to check session isolation. Confirm My Results starts empty for a new learner and the Video Library contains no media files. Restart the services VM once and recheck site health and content.

On the Proxmox root shell, keep a backup after acceptance:

```bash
qm list
qm guest exec 9000 -- /bin/bash -lc '/opt/training-academy/backup.sh'
```

Back up VM 9000 and templates 9008, 9105, 9200, 9251 and 9252 through Proxmox as well. The application backup alone does not contain the lab-template disks.

## Recovery if installation stops

Preserve `/root/gdp-install`, `/root/academy-media`, `/root/academy-bootstrap`, `/root/gdp-site.json` and every VM that was created. Keep `/root/academy-bootstrap/docker-lab-package/` and its generated import receipt. Read the first reported error and Proxmox task log; inspect VM 9000's `/var/log/cloud-init-output.log` if services failed. The installer deliberately refuses an existing bootstrap, VM or container. Repair from the recorded state or reinstall on a newly emptied **disposable** node. Never remove the guard or rerun against production to force progress.
