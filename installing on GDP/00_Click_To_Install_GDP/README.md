# One-click GDP base installer

## Before you click

Install Proxmox VE 9 on the dedicated server using the included `00_Proxmox_Installer/proxmox-ve_9.2-1.iso`. This disk install is a separate step because it erases the selected target disk. Finish Proxmox network setup and keep the server on the LAN. The installer then requires an empty Proxmox node, nested KVM, and active VM/ISO storage.

Extract the full `installing on GDP` folder on a Windows administration computer that can reach Proxmox over SSH. Double-click the root `Install-GDP-Academy.cmd` file. Accept the SSH host key only after checking that it belongs to the intended Proxmox server, then enter the root password at the OpenSSH prompt. The password is not saved by the launcher.

The launcher runs the full GDP package verifier, including the base archive, Academy provisioning ISO, Proxmox installer ISO, and all sidecars. It copies the media to `/root/gdp-install`, opens the site-configuration prompts, validates the network and storage values, and asks for `INSTALL` before the first Proxmox changes. Keep this window open until bootstrap ends.

The default layout uses a private services bridge at `10.10.0.0/24` and an isolated learner bridge at `10.44.0.0/24`. The wizard checks both ranges against the LAN and checks that the selected management IP is assigned to the selected Proxmox bridge. Choose different private ranges if either default already exists at the site.

## Scope and version

This installer creates the base Academy services VM and two initial lab templates. The services VM hosts both frontend and backend components. Class restoration and the Linux Lab v3 template import remain separate acceptance steps in `START_HERE_GDP_LAN_INSTALL.md`.

The media currently installs the 11 October 2026 base. Later GDP folders are version-gated production updates and cannot be safely layered onto that base automatically. Do not treat this launcher as a current-production rebuild until a consolidated current-release media set is built and verified.

## Recovery

The bootstrap refuses populated Proxmox nodes and existing bootstrap state. If it stops after setup begins, preserve `/root/academy-bootstrap`, `/root/academy-media`, `/root/gdp-install`, and every VM it created. Read the base `04_Guides/INSTALL.md` recovery section and inspect Proxmox tasks plus `/var/log/cloud-init-output.log` before any repair. Never delete the guard directory or rerun the installer blindly.
