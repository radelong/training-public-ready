# Install the Training Academy

**Public source copy:** This directory omits the protected media and content required to run the installer. Read `SOURCE_ONLY.md`. Use the controlled GDP USB package for installation.

This package installs the website, backend, database, browser terminals, eleven classes with quizzes and exams, two Academy assessments, six games and four labs. Users and results start fresh. The video library is excluded; the built-in lab tutorial is included.

## Install from a USB drive

1. **Prepare the drive.** Use a **32 GB or larger exFAT USB drive** labelled **ACADEMY**. Formatting erases a drive, so save its existing files first. Copy the entire **GDP Installer** folder onto it. FAT32 cannot hold the large files. Copying only the launcher will not work.
2. **Plug it into the Proxmox server.** Proxmox VE 9 must already be installed. Use a dedicated, empty, standalone node with no VMs or containers. Open **Proxmox web interface → your node → Shell** and sign in as root.
3. **Paste this whole block into the shell:**

   ```sh
   mkdir -p /mnt/academy
   mount -t exfat -o ro /dev/disk/by-label/ACADEMY /mnt/academy
   bash '/mnt/academy/GDP Installer/INSTALL.sh'
   ```

   If the drive is already mounted there, run the last line. For any other mount error, check the drive label and connection before continuing. Proxmox has no desktop file manager, so its direct-server method uses this command instead of double-clicking a file.
4. **Enter the website name and confirm.** For example: `academy.training.internal`. Do not enter an IP address, `https://`, or a name ending in `.local`. The installer reads Proxmox's network and storage and checks available resources. It keeps the Academy's VM sizes and does not ask you to allocate RAM or size the lab VMs. It asks about a setting only if it cannot choose safely. Review the summary, then type **yes**.
5. **Leave the USB connected until completion.** Everything from this point installs automatically. The installation continues if you close the progress window. To check it again, run the last command from step 3. A successful finish displays **Academy installation complete** and a receipt. Then complete the first-sign-in steps below.

## First sign-in

1. **Add one LAN DNS A record.** Map the website name to the Proxmox IP shown in the completion receipt. Make this change on the DNS server/router your learner computers use. The installer has no credentials for that device, so it cannot make the DNS change itself. No public DNS or Cloudflare tunnel is needed. Learner computers must be on the permitted LAN subnet shown in the summary.
2. **Trust the Academy certificate on learner computers.** On a Windows administrator PC, copy the public CA certificate:

   ```powershell
   scp root@PROXMOX_LAN_IP:/root/academy-install/academy-ca.crt .
   ```

   Replace `PROXMOX_LAN_IP` with the IP from the receipt. If SSH asks you to accept a fingerprint, first compare it with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` in the Proxmox root shell. The SHA256 values must match.

   Compare `Get-FileHash .\academy-ca.crt` on Windows with `sha256sum /root/academy-install/academy-ca.crt` on Proxmox. Then open PowerShell **as administrator** in the downloaded certificate's folder and run:

   ```powershell
   Import-Certificate -FilePath .\academy-ca.crt -CertStoreLocation Cert:\LocalMachine\Root
   ```

   Repeat certificate trust on other learner computers, or have your IT administrator distribute that same CA. Copy only the `.crt` file, never a `.key` file. Do not bypass browser certificate warnings.
3. **Read the initial login in the Proxmox root shell:**

   ```sh
   qm guest exec 9000 -- /bin/cat /opt/training-academy/secrets/initial-admin.txt
   ```

   The username and password appear in the output's `out-data` field. Open the website from the receipt, sign in, and change the administrator password in **Administration**. Create learner accounts there. Keep the login details private.
4. **Check the new site before admitting learners.** Open classes and games. Launch and end each lab; confirm both Callback panes show different hosts and accept input. Check exercise feedback and grading, and verify two learners receive separate environments. You can adjust lab VM settings in Administration.
5. **Remove the USB safely** after installation has completed:

   ```sh
   umount /mnt/academy
   ```

The DNS record and workstation certificate trust are the two external setup tasks. The package automatically installs and configures the Academy itself.

## Optional: double-click from Windows instead

Leave the USB in a Windows PC on the new server's LAN and double-click **INSTALL-WINDOWS.cmd**. Windows OpenSSH Client must be installed. Enter the Proxmox IPv4 address, compare the SSH fingerprint as above, and enter the root password only when OpenSSH asks. Up to three password prompts are normal; the password is not saved.

The launcher verifies and copies the complete package, then starts the same installer. Keep the PC awake through copying and confirmation. After confirming, installation runs on the server even if the progress connection closes. Complete the same DNS, certificate and first-login steps above. The protected copy remains under `/root/gdp-install` on Proxmox.

## If setup stops

In the Proxmox root shell, check:

```sh
cat /root/academy-install/state /root/academy-install/step
```

`complete` means installation finished. `starting` or `running` means it is still working. `failed` means it stopped. The full log is `/root/academy-install/install.log`, and the completion receipt is `/root/academy-install/receipt.txt`.

Running INSTALL.sh again shows the saved status; it never retries a partial installation. Preserve the log, `/root/academy-media`, `/root/academy-bootstrap`, and the created VMs. Do not delete VMs or networking to force another run. Obtain help with the exact error before changing the failed installation; share logs only privately because they can contain deployment details.

If the Windows copy failed before installation started, preserve the incomplete `/root/gdp-install` directory under another unused name before copying again. Do this only if `/root/academy-bootstrap` and `/root/academy-install` do not exist and no installation service is running. The preserved copy still uses disk space.

## Hardware and defaults

The installer checks suitability automatically. Plan for at least 32 GB RAM, 250 GB free LVM-thin or ZFS VM storage, and 40 GiB free under `/root`. The Windows method additionally needs enough space for the whole package. ZFS ARC reservations can require more physical RAM. A minimum-size server normally supports about two simultaneous labs; the existing ten-lab default is reduced when measured resources cannot safely support it. Two labs per learner remain the default.

VM defaults match the Academy: services 4 vCPUs / 8 GiB / 50 GiB; Netlab and Linux 2 vCPUs / 4 GiB each; Callback 2 vCPUs / 4 GiB per VM; Docker 2 vCPUs / 8 GiB. Lab disks come from the included templates. This package does not resize the Proxmox host. SSD storage improves installation and lab startup speed.

`VERIFY.ps1` checks the package on Windows. Both launch methods verify its hashes before installing. Keep the package as recovery media; do not share its protected course assets or answers publicly.


## Installation troubleshooting

[INSTALLATION-TROUBLESHOOTING-GUIDE.md](./INSTALLATION-TROUBLESHOOTING-GUIDE.md) gives step-by-step diagnostics, likely installer messages, safe corrective actions, and stop points for partial failures. A printable PDF is alongside it. These guides are documentation only; this public source folder does not contain the protected offline install media.
