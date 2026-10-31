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
| Docker Troubleshooting Lab package (about 2 GiB) | `45_Docker_Troubleshooting_Lab/docker-troubleshooting-package-r7.academy-lab.tar.gz` | Builds template 9200, runs a disposable readiness clone, and writes an Academy import receipt. The four-lab catalog registers its 18 exercises after the template passes readiness. |
| Nine base classes, assessments, and all six learning games | `28_Fresh_Install_Content` | Imports protected teaching content after the new services VM starts. The fresh game archive is refreshed from the six current game assets and excludes learner data. |
| Docker: Beginner and Docker: Intermediate | `44_Docker_Replacement_Classes` | Imports the two additional protected Docker classes, with slides, module quizzes, pretests, finals and answer keys. |
| Academy application update 28, revision 3 | `33_Learning_Fixes_R3` | Applies module checks, assessment review and recommendation, and game-exit changes to the fresh services VM before content import. |

The Proxmox ISO checksum sidecar is included. The launcher verifies the Proxmox ISO, both Academy media sidecars, the extracted offline media manifest, protected course bundle, Docker class bundle and Docker lab package before it creates or imports Academy content.

The launcher targets a **dedicated, empty Proxmox VE 9 node**. It does not install Proxmox or erase a physical server. It installs the consolidated media and protected content, including eleven learner classes, two 80-question Academy assessments, six games and four labs. Older numbered folders are recovery references, not a replay chain for this installer. Full empty-node acceptance is still pending.
