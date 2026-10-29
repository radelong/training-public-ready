# GDP fresh-installer content update — 2026-10-29

The separately maintained private GDP installer now includes:

- Ten classes: the eight existing classes plus Docker: Beginner and Docker: Intermediate.
- Four labs: Netlab (28 exercises), Linux Lab (23), Callback Lab (10), and Docker Troubleshooting Lab (18).
- Two 80-question Academy assessments and all six learning games.
- The latest Blast Radius, Dead Drive, and SOC Nightshift saved-progress fixes, plus the shared game-launch fix.
- Current administrator course controls, applied as application updates 41, 42, and 43.

Fresh installs create a new administrator and empty learner history. Video files, existing users, passwords, attempts, results, and bug reports stay out of the package.

The package and its Desktop handoff passed the 79-entry fresh manifest, 556-entry complete GDP manifest, and 24-file base-package checks. Content inspection confirmed all class, lab, assessment, and game counts.

The package remains a candidate. It still needs a full install and learner acceptance on a dedicated empty Proxmox VE 9 node. Production was not changed by this package refresh.

This public repository deliberately omits the protected teaching assets and installation media. The release note documents the private kit; it does not make the public checkout independently installable.
