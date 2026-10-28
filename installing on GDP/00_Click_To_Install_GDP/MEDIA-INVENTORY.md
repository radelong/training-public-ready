# GDP install media

This installation uses one Ubuntu 26.04 **services VM** for the Academy website frontend, API/backend, PostgreSQL, worker, HTTPS proxy, and browser terminal services. There are no separate frontend and backend operating-system images.

The package contains the operating-system media needed for a fresh dedicated Proxmox VE 9 host and Academy bootstrap:

| Media | Location | Role |
| --- | --- | --- |
| Proxmox VE 9.2-1 installer ISO | `00_Proxmox_Installer/proxmox-ve_9.2-1.iso` | Installs the hypervisor onto the dedicated host. This first operating-system install remains a separate step. |
| Current Academy provisioning ISO | `30_Current_Offline_Media_2026-10-26/academy-provision.iso` | Offline guest provisioning assets attached to the Ubuntu services VM. |
| Ubuntu Server 26.04 cloud disk image (`.img`, not ISO) | Inside `30_Current_Offline_Media_2026-10-26/training-academy-offline-amd64.tar.gz` at `assets/ubuntu/ubuntu-26.04-server-cloudimg-amd64.img` | Base disk used by the services VM. |
| Offline container images and Debian/Python packages | Inside the current offline archive | Runs the website frontend/backend and guest setup without a package download. |
| Four sealed lab-template backups | `29_Current_Lab_Templates/backups` | Restores Netlab, Linux Lab, and both Callback Lab roles. |
| Eight classes, assessments, and six learning games | `28_Fresh_Install_Content` | Imports protected teaching content after the new services VM starts. |
| Academy application update 28, revision 3 | `33_Learning_Fixes_R3` | Applies module checks, assessment review and recommendation, and game-exit changes to the fresh services VM before content import. |

The Proxmox ISO checksum sidecar is included. The one-click launcher verifies the Proxmox ISO, both Academy media sidecars, and the extracted offline media manifest before it asks Proxmox to create anything.

The launcher targets a **dedicated, empty Proxmox VE 9 node**. It does not install Proxmox or erase a physical server. It installs the consolidated current media and protected content. Older numbered folders are recovery references, not a replay chain for this installer. Full empty-node acceptance is still pending.
