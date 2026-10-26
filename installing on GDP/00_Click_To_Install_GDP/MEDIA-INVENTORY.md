# GDP install media

This installation uses one Ubuntu 26.04 **services VM** for the Academy website frontend, API/backend, PostgreSQL, worker, HTTPS proxy, and browser terminal services. There are no separate frontend and backend operating-system images.

The package contains the operating-system media needed for a fresh dedicated Proxmox VE 9 host and Academy bootstrap:

| Media | Location | Role |
| --- | --- | --- |
| Proxmox VE 9.2-1 installer ISO | `00_Proxmox_Installer/proxmox-ve_9.2-1.iso` | Installs the hypervisor onto the dedicated host. This first operating-system install remains a separate step. |
| Academy provisioning ISO | `01_Base_Platform/Training_Academy_Final_2026-10-11/01_Deployment_Media/academy-provision.iso` | Offline guest provisioning assets attached to the Ubuntu services/template VMs. |
| Ubuntu Server 26.04 cloud disk image (`.img`, not ISO) | Inside `training-academy-offline-amd64.tar.gz` at `assets/ubuntu/ubuntu-26.04-server-cloudimg-amd64.img` | Base disk used by the services VM and initial lab templates. |
| Offline container images and Debian/Python packages | Inside `training-academy-offline-amd64.tar.gz` | Runs the website frontend/backend and guest setup without a package download. |

The Proxmox ISO checksum sidecar is included. The one-click launcher verifies the Proxmox ISO, both Academy media sidecars, and the extracted offline media manifest before it asks Proxmox to create anything.

The launcher targets a **dedicated, empty Proxmox VE 9 node**. It does not install Proxmox or erase a physical server. It installs the bundled 11 October 2026 base only; later dated folders are incremental releases whose source guards do not make them a safe automatic upgrade chain for this older base.
