# GDP Academy installation troubleshooting guide

Use this guide while installing the Training Academy on a **new, empty, standalone Proxmox VE 9 or newer server**. Proxmox must already be installed. The installer is offline and uses the VM sizes in the Academy defaults.

This guide lists messages produced by the current installer and the safest next action. No guide can predict every hardware or network failure. If an error is not listed, save the first error and the private logs; do not guess at a repair.

## Read this before fixing anything

- **Before you type `yes`:** the installer has not changed Proxmox. Fix the reported preflight issue, then run `INSTALL.sh` again.
- **After you type `yes`:** the installer makes changes in a background systemd service. Closing the console does not stop it.
- **If state is `running`:** check the current step and log. Do not start a second installer, stop the service, reboot, or remove the USB.
- **If state is `failed`:** the installer does not support resuming or retrying a partial install. Preserve its evidence and use the matching safe checks below. Never delete state files, bridges, VMs, or checksum files to force a retry.
- Do not bypass SSH host-key checks, TLS checks, Proxmox firewall, or package checksums.
- Keep all errors and logs private. They can show your server name, LAN address, storage names, and setup details. Never include passwords, tokens, or private keys in a support message.

## 1. USB drive is not found or will not mount

The default USB label is `ACADEMY`. A different label also works: check its exact spelling with `lsblk -f` and use that exact value in `/dev/disk/by-label/<LABEL>`. Keep exFAT and the complete `GDP Installer` folder. Do not use FAT32: it cannot store the large package files.

Run these read-only checks in the Proxmox root shell:

```sh
lsblk -o NAME,PATH,LABEL,FSTYPE,SIZE,MOUNTPOINTS
blkid
findmnt /mnt/academy
```

| Message or symptom | Fix |
| --- | --- |
| `/dev/disk/by-label/ACADEMY` does not exist | Check `lsblk` for the USB partition and its label. Reconnect the USB and run the checks again. Do not guess a disk name. |
| `mount: ... wrong fs type` or `unknown filesystem type 'exfat'` | Confirm `FSTYPE` in `lsblk`. Use a correctly formatted exFAT USB. If the host cannot read exFAT, use the Windows transfer method in Guide 01 or have an administrator prepare supported media. Do not install random packages on Proxmox. |
| `mount point ... does not exist` | Run `mkdir -p /mnt/academy`, then repeat the mount command. |
| `already mounted` | Run `findmnt /mnt/academy`. If it shows this USB, continue. Do not unmount it while installation is running. |
| `INSTALL.sh: No such file or directory` | Run `ls -la /mnt/academy` and `ls -la '/mnt/academy/GDP Installer'`. Mount the correct USB partition or copy the complete folder. |

Mount the labelled USB read-only, then confirm the package is visible:

```sh
mkdir -p /mnt/academy
mount -t exfat -o ro /dev/disk/by-label/ACADEMY /mnt/academy
ls -la '/mnt/academy/GDP Installer'
```

If the partition has a different label, use the exact partition path shown by `lsblk` in place of `/dev/disk/by-label/ACADEMY`. Never substitute the Proxmox boot disk.

## 2. Package verification fails

On Windows, open PowerShell in the `GDP Installer` folder and run:

```powershell
.\VERIFY.ps1
```

Success says `ACADEMY USB PACKAGE VERIFIED: 59 files.`

| Message | Fix |
| --- | --- |
| `MANIFEST.sha256 is missing.` | Copy the complete `GDP Installer` folder again from the verified Desktop handoff. Do not copy only `INSTALL.sh`. |
| `Invalid manifest line`, `Package manifest is incomplete`, or `MANIFEST.sha256 is malformed or incomplete` | The package copy is incomplete or changed. Recopy the entire folder. Do not edit the manifest. |
| `Missing package file: ...` or `A package checksum failed` | Recopy the entire folder from the verified handoff to a known-good exFAT or NTFS drive, then verify again. If the error returns, replace the USB drive. |
| Windows PowerShell blocks the verification script | Do not change the computer-wide execution policy. Use the launcher's built-in verification or the Proxmox shell method; ask the PC administrator if policy blocks both. |

On Proxmox, the installer verifies all package checksums before it changes the node. If it says `A package checksum failed. Recopy the complete package before installing.`, stop and replace the USB copy. Never edit `MANIFEST.sha256` or use an unchecked package.

## 3. Installer refuses to start on the Proxmox server

These errors happen before the installer accepts `yes`. They mean the server does not meet the installer's safety checks.

| Exact message or output | Fix |
| --- | --- |
| `Run this script as root on the Proxmox node.` | In the Proxmox web interface, open the target node's **Shell** and sign in as `root`. Do not run the installer inside Ubuntu or another VM. |
| `Required command is missing: ... This must be a Proxmox VE 9 node.` | Check `pveversion -v`. Use a supported Proxmox VE 9 or newer installation. Do not add missing system packages by guesswork. |
| `This installer requires Proxmox VE 9 or newer.` | Install Proxmox VE 9 or newer on the new server. Do not attempt an in-place upgrade as part of this Academy installer. |
| `This node belongs to a Proxmox cluster.` | Stop. This package is for a dedicated standalone node. Do not remove cluster configuration to pass the check. |
| `This node already has VMs or containers.` | Stop. Use an empty Proxmox node. Do not delete existing VMs or containers to continue. |
| `Hardware virtualization is not available. Enable VT-x or AMD-V in the firmware.` | Enable Intel VT-x or AMD-V/SVM in server firmware, boot Proxmox again, then check for the `vmx` or `svm` flag in `/proc/cpuinfo`. If neither appears, ask the server administrator to check the processor and firmware settings. |
| `Another copy of INSTALL.sh is already running on this node.` | Do not kill it. Check the status commands in section 7. If installation is running, watch that run. |

## 4. Website, LAN, bridge, storage, or capacity prompt fails

The installer detects the server's LAN, storage, routes, and available resources. It saves settings only after you type `yes`. If you type `change`, revise the selection. If you type `no` or press Ctrl+C at a prompt, it stops before making Proxmox changes.

| Exact message or prompt | Fix before continuing |
| --- | --- |
| `A website hostname is required.` | Enter a full website name, such as `academy.training.internal`. |
| `Enter a DNS name ... not an IP address, https://, or a port.` | Enter only the DNS hostname. Do not include `https://`, an IP address, or `:443`. |
| `Do not use .local; it is reserved for multicast DNS.` | Choose a different internal DNS suffix, such as `.internal` or `.lan`, then plan a LAN DNS A record for that name. |
| `Enter a reachable IPv4 DNS server address.` | Enter the address of the LAN DNS server that Proxmox and the Academy VM can reach. Check it with your network administrator. |
| `No Linux bridge with a LAN IPv4 address was found.` | In Proxmox, open **Node → System → Network**. Confirm the management bridge (normally `vmbr0`) has the server's LAN IPv4 address and the correct physical network port. Do not apply network changes over a remote session unless you have local or out-of-band console access. |
| `No active local LVM-thin or ZFS storage for VM disks was found.` | Run `pvesm status`. Enable or prepare an active local LVM-thin or ZFS storage that supports VM disks and linked clones. Do not select a backup-only or shared storage target. Ask the Proxmox administrator if no eligible storage exists. |
| `No active local directory storage with ISO content and at least 6 GiB free was found.` | Run `pvesm status`. Enable a local directory storage with ISO content and at least 6 GiB free. Do not delete storage data to make the check pass. |
| `Every built-in private services subnet overlaps the LAN or an existing route.` | The LAN or a host route overlaps every supported private subnet. Ask the network administrator to resolve the overlap before installing. Do not delete routes or edit the generated site file. |
| `The LAN ... overlaps the fixed learner subnet ...` or `An existing host route overlaps the fixed learner subnet ...` | Resolve the LAN or route overlap with the network administrator before continuing. This package uses an isolated learner network; do not bridge it onto the physical LAN. |
| `The selected Proxmox address is not assigned to the selected bridge.` | Choose the bridge that actually owns the Proxmox LAN address shown by `ip -4 -brief address`. Use **change** to select again. |
| `The learner bridge must have no ports and no host address.` | Do not attach a physical port or host IP to the isolated learner bridge. Ask the Proxmox administrator to remove an unintended bridge attachment before starting. |
| `No valid choice is available for: ...` | The installer found no safe option for that setting. Check `pvesm status`, **Node → System → Network**, and the listed resources. Fix the underlying Proxmox configuration, then start the installer again before typing `yes`. |
| `Not enough capacity for the two-VM labs ...` or `Available host resources do not meet the automatic defaults.` | Add suitable RAM/storage or choose a smaller safe concurrency when the installer offers it. Do not reduce the Academy VM sizes or remove the host reserve. Check `free -h`, `pvesm status`, and `df -h /root`. |
| `This node has ... CPU threads; the services VM needs ...` | Use a server with enough CPU threads for the displayed services VM requirement. This installer does not resize the Proxmox host. |
| `Type "yes" to save and continue, "change" to revise, or "no" to stop:` | Type `change` to correct a displayed selection. Type `no` to stop safely. Type `yes` only after confirming website name, LAN, storage, network, and capacity summary. |

Before `yes`, check free space and storage:

```sh
free -h
df -h /root
pvesm status
ip -4 -brief address
ip route
```

The installer needs **40 GiB free under `/root`**. The Windows transfer method also needs space for the complete package plus that reserve. If space is low, add storage or ask the administrator to identify safe-to-remove files. Never delete installer state, Proxmox data, backups, or unknown files to free space.

## 5. Windows copy or SSH connection fails

The Windows launcher verifies the package, copies it to `/root/gdp-install`, then starts the same installer. No Academy installation begins until the copy finishes and you confirm the site settings.

| Message or symptom | Fix |
| --- | --- |
| `ssh.exe` or `scp.exe` is not found | Install the Windows **OpenSSH Client** optional feature, or use the direct Proxmox USB method in Guide 01. Do not download SSH tools from an untrusted site. |
| `Enter a valid IPv4 address.` | On Proxmox, run `ip -4 -brief address`. Enter the server's LAN IPv4 address only. |
| `Connection timed out` or `Connection refused` | Confirm the PC and server are on a reachable LAN, the IP is correct, and the Proxmox SSH service is running. In the Proxmox shell, check `systemctl status ssh --no-pager` and `ss -lntp`; look for port 22. Use the direct shell method if SSH is unavailable. |
| `Permission denied` | Enter the Proxmox `root` password only at the SSH prompt. Verify that the same password works in the Proxmox console. Do not enable passwordless SSH or weaken root-login policy to work around this. |
| `Host key verification failed` or the fingerprint differs | Stop. Compare the PC's SSH fingerprint with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the Proxmox console. Accept only an exact match for the intended new server. If it does not match, confirm the IP and server identity with the administrator. |
| `Connection failed, free disk space is insufficient, or /root/gdp-install already exists.` | Check `df -h /root`, `ls -ld /root/gdp-install`, `/root/academy-install`, and `/root/academy-bootstrap`. If an install state or bootstrap directory exists, do not rename or remove anything; follow sections 7 and 8. If no install started, preserve the partial copy as described below, free safe space, then recopy. |
| `Copy failed. No installation was started.` | Keep the original USB package. Reconnect SSH and check whether `/root/gdp-install` exists. If no install state, bootstrap directory, or active service exists, preserve the partial copy under a new name, then rerun the Windows launcher. |
| `Setup stopped or SSH disconnected.` | Reconnect. On Proxmox, run `bash /root/gdp-install/INSTALL.sh`. It shows progress or the saved error; it does not retry a failed install. |

Only if the copy failed **before** installation, and all three checks below show no setup has started, preserve the incomplete directory rather than deleting it:

```sh
test ! -e /root/academy-install && echo 'No install state'
test ! -e /root/academy-bootstrap && echo 'No bootstrap state'
systemctl is-active academy-install.service
```

If the service command says `inactive` or `unknown` and both directories are absent, use a unique name and retry the copy:

```sh
mv /root/gdp-install "/root/gdp-install-copy-failed-$(date -u +%Y%m%dT%H%M%SZ)"
```

If any check shows state exists, stop. Do not rename, delete, or overwrite installer files.

## 6. Configuration prompt stops before installation

Messages starting with `Stopped:` or `Configuration error:` are raised before the installer accepts `yes`. Correct the setting listed in section 4 and run the launcher again. If the prompt says `Stopped. Nothing was changed.`, this is a safe cancellation.

If input appears frozen, make sure you opened an interactive Proxmox shell. The installer cannot accept prompts through a non-interactive command. Reopen **Node → Shell** and start it there.

## 7. Watch progress or recover a disconnected console

The installer runs as `academy-install.service`. Closing the browser, SSH window, or progress viewer does not stop it. Keep the USB connected and mounted until completion.

After you type `yes`, the installer writes one step at a time to the log. The main steps are package recheck, bridge and service-VM setup, guest bootstrap, application install, template restore, Docker-template build, content import, HTTPS check, and receipt. Large media checks and the first VM boot can be quiet for several minutes. A quiet log is not a failure if the service is active.

During first boot, the log prints `Waiting for VM 9000 to finish verified offline provisioning.` about once a minute. The installer allows up to **60 minutes** for this verified bootstrap. Keep watching while the service is active. If it prints `VM 9000 provisioning failed` or `VM 9000 bootstrap did not complete`, stop following the normal progress path and use section 8.

Use the same launcher you used to begin installation:

```sh
# Direct USB method
bash '/mnt/academy/GDP Installer/INSTALL.sh'

# Windows copy method
bash /root/gdp-install/INSTALL.sh
```

If the command says `An Academy installation is already running. Showing its progress.`, it is attaching to the current run. Ctrl+C stops only the viewer, not the install. Run the same command again to watch it.

Check state and service without changing anything:

```sh
cat /root/academy-install/state
cat /root/academy-install/step
systemctl is-active academy-install.service
tail -n 80 /root/academy-install/install.log
```

| State | Meaning and action |
| --- | --- |
| `starting` or `running`; service `active` or `activating` | Installation is working. Read the current `step` and wait. Media verification and VM first boot can take a long time, especially on HDDs. Do not reboot or run another installer. |
| `complete` | Installation finished. Read `/root/academy-install/receipt.txt` and follow section 9. |
| `failed` | The install stopped. Save the first error and follow section 8. Do not retry. |
| `configured`; service inactive | The background service may not have started. Review the log and last console message. If there is no `/root/academy-bootstrap` directory and no VM was created, the installer may be started again with `bash .../INSTALL.sh`. If anything changed or you are unsure, stop and ask the installer maintainer before proceeding. |
| `starting` or `running`; service `failed` or `inactive` | The installer stopped unexpectedly. Save the log and follow section 8. Do not force a restart. |
| `cat: ... No such file` | The installer may not have reached that phase. Check that the correct USB/package path is mounted and start the launcher once. If `/root/academy-bootstrap` exists, do not start a new installation. |

For a service failure, collect the last private log lines:

```sh
systemctl status academy-install.service --no-pager
journalctl -u academy-install.service -n 80 --no-pager
tail -n 120 /root/academy-install/install.log
```

## 8. Installer says `failed`

First save the exact step and error. Do not stop or start services, edit the site file, delete VMs, delete bridges, or run internal helper scripts.

```sh
cat /root/academy-install/state
cat /root/academy-install/step
tail -n 120 /root/academy-install/install.log
qm list
pvesm status
```

Then match the failed step.

### Proxmox VM and bootstrap errors

| Failed step or exact message | Safe diagnosis and next action |
| --- | --- |
| `Creating bridges, Proxmox service account and the services VM` | Save `journalctl -u academy-install.service -n 120 --no-pager`, `qm list`, `pvesm status`, and the install log. Do not remove the created account, token, firewall, bridges, or partial VM. A Proxmox task failure needs a maintainer to inspect the exact task before repair. |
| VM provisioning failed | The installer prints the VM ID. Check its state with `qm status 9000` and guest-agent access with `qm agent 9000 ping`. If guest-agent works, inspect cloud-init with `qm guest exec 9000 -- cloud-init status --long` and `qm guest exec 9000 -- /bin/cat /var/log/cloud-init-output.log`. Save the first cloud-init error. Do not rerun cloud-init or delete the VM. |

| Failed step or exact message | Safe diagnosis and next action |
| --- | --- |
| VM bootstrap timed out | This is a timeout, not proof that the VM is safe to recreate. Check `qm status 9000`, then the guest-agent and cloud-init commands above. If still provisioning, preserve the VM and wait for a maintainer to assess it. |
| `Could not read the services VM SSH host key through the guest agent.` | Check `qm status 9000`, `qm agent 9000 ping`, and `qm guest exec 9000 -- cloud-init status --long`. Do not turn off host-key validation or add a guessed SSH key. Preserve the VM and log. |
| `The services VM did not accept SSH with the pinned host key.` | Verify the guest IP in the install summary, guest-agent state, cloud-init completion, and SSH service status: `qm guest exec 9000 -- systemctl status ssh --no-pager`. Do not delete `known_hosts` or disable strict SSH checks. |
| `Passwordless sudo is not available in the services VM.` | The packaged guest bootstrap did not finish as expected. Save the log and inspect `qm guest exec 9000 -- cloud-init status --long`. Do not type or store a new password in the automation. |

### Services VM certificate and HTTPS errors

| Failed step or exact message | Safe diagnosis and next action |
| --- | --- |
| `The Academy CA file is not a PEM certificate.` | The guest did not return the expected public CA. Preserve `/root/academy-install/academy-ca.crt.tmp` and logs. Do not create a replacement certificate manually. |
| HTTPS health check failed | Check `qm status 9000`, then inspect container health and logs inside the services VM using the command below. Confirm the installer did not report a checksum, schema, or content-import error first. Do not use `curl -k` or disable TLS verification. |
| `command failed at line ...` | This is the shell's final wrapper message. The useful error is usually earlier in `install.log`. Save at least 80 lines before it and the printed step name. |

Read-only services checks from the Proxmox host (the services VM ID is shown in the install summary; it is normally `9000`):

```sh
qm status 9000
qm agent 9000 ping
qm guest exec 9000 -- /bin/bash -lc 'cd /opt/training-academy && docker compose ps'
qm guest exec 9000 -- /bin/bash -c \
  'cd /opt/training-academy && docker compose logs --tail 40 api'
qm guest exec 9000 -- /bin/bash -c \
  'cd /opt/training-academy && docker compose logs --tail 40 worker'
qm guest exec 9000 -- /bin/bash -c \
  'cd /opt/training-academy && docker compose logs --tail 40 web'
qm guest exec 9000 -- /bin/bash -c \
  'cd /opt/training-academy && docker compose logs --tail 40 guacamole'
qm guest exec 9000 -- /bin/bash -c \
  'cd /opt/training-academy && docker compose logs --tail 40 guacd'
```

`qm guest exec` returns JSON. Read `out-data`; if it reports truncated output, run one container-log command at a time. Keep the output private.

**There is no supported in-place retry after state becomes `failed`.** The current installer preserves partial resources and refuses to run over them. A maintainer must review the saved error, identify the responsible layer, and provide a reviewed recovery or clean-reinstall plan for the isolated new server. Never clear `/root/academy-install`, `/root/academy-bootstrap`, `/root/academy-media`, Proxmox VMs, firewall rules, or bridges to make the installer start again.

## 9. Installation completed, but the website does not open

First check the receipt and health locally:

```sh
cat /root/academy-install/receipt.txt
qm status 9000
qm guest exec 9000 -- /bin/bash -lc 'cd /opt/training-academy && docker compose ps'
```

| Symptom | Fix |
| --- | --- |
| Browser says the hostname cannot be found | Add the LAN DNS A record shown in the receipt: website hostname to the Proxmox LAN IP. Then on an Ubuntu learner PC run `getent ahosts YOUR_HOSTNAME` and confirm it returns the Proxmox LAN IP from the receipt. Do not use public DNS or Cloudflare tunnel for this LAN-only install. |
| Browser reports a certificate warning | On Ubuntu, follow Guide 01 to compare the SSH fingerprint and SHA-256, install the CA with `sudo update-ca-certificates`, and restart the browser. If Firefox still warns, import the CA under its Authorities settings. Confirm the hostname matches the receipt. Never click through the warning. |
| DNS resolves, but the connection times out | On Ubuntu, run `nc -vz YOUR_HOSTNAME 443` if netcat is installed. Check Proxmox's LAN bridge, services VM status, and permitted LAN subnet in the installer summary. Do not open Proxmox port 8006 to learners. |
| Website returns `502` or `503` | Check `docker compose ps`, then read only the unhealthy service logs using the commands in section 8. Preserve the logs and do not recreate containers or restore a database without a maintainer's plan. |
| Sign-in page appears but initial login fails | Retrieve the one-time login from the services VM as shown in Guide 01. Change the password after first sign-in. Never paste the password into a log or support message. |

## 10. If you need help

Send the maintainer these details privately: launch method; whether you typed `yes`; exact `state` and `step`; first error and last 80 lines of `install.log`; output of `qm list` and `pvesm status`.

Redact passwords, tokens, private keys, and learner data. Keep full logs and the failed VM on the server until the maintainer provides a written recovery plan.