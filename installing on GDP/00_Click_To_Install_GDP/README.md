# GDP fresh Academy installer

Install Proxmox VE 9 on a dedicated server from `00_Proxmox_Installer/proxmox-ve_9.2-1.iso` first. That physical-disk installation is separate because it overwrites the disk selected in the Proxmox installer. Configure its LAN address and storage. If Proxmox itself runs in a VM, expose hardware virtualization to it.

For a GDP server on a separate LAN, copy the complete extracted `installing on GDP` folder to removable media. Mount that media on the new Proxmox server and run `bash Install-GDP-Academy.sh` from this folder in its local root console. The script verifies the packaged files and runs the same installer directly from the mounted drive. It asks for the site and network values on that server. Keep the drive mounted until installation finishes. See `START_HERE_GDP_FRESH_INSTALL.md` for the exact steps.

If a Windows administrator computer can reach the new Proxmox LAN, the optional `Install-GDP-Academy.cmd` launcher verifies and transfers the same package over SSH. It asks for the Proxmox LAN IP and SSH host-key verification. The LAN IP is not embedded in either launcher.

The new installation creates one Ubuntu 26.04 services VM for the frontend, API, database and embedded consoles. It restores Netlab (9008), Linux Lab (9105), and the Callback Lab sender/listener pair (9251/9252). It applies the bundled application update, then imports eleven classes with slides, quizzes and finals, two separate 80-question assessments, and six learning games. It creates fresh accounts and empty learner results. The video library's files and existing production users, passwords, attempts, results and bug reports are excluded. This installation is LAN-only; it does not configure Cloudflare.

The installer refuses a Proxmox node that already has VMs, containers, or bootstrap state. It also checks media and content hashes, selected bridges, isolated network ranges, and storage. It verifies the services VM SSH host key through the Proxmox guest agent before copying protected content. If a step fails after bootstrap starts, preserve `/root/gdp-install`, `/root/academy-media`, `/root/academy-bootstrap`, and all created VMs. Inspect the displayed error and Proxmox task log before repair; do not clear the guard or rerun blindly.

After installation, read `START_HERE_GDP_FRESH_INSTALL.md` for LAN DNS, certificate trust, initial administrator sign-in, acceptance tests and backup. Earlier numbered GDP update folders remain as historical recovery material; do not replay their version-gated installers over the consolidated current media.

Release status: the current media and installer are assembled and checksum-verified, but the complete installer still requires acceptance on an empty disposable Proxmox node before this package is marked complete.
