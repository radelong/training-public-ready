# Training platform source

A training portal with accounts, course authoring, learner progress, server-graded exercises, manual written-response grading and isolated lab-session management through Proxmox and Guacamole. This copy includes platform source and generic authored Netlab tooling. It excludes actual course PDFs, real exam banks/answer keys, learner records, administrator secrets, site-specific configuration, operational reports and deployment media.

The public website has separate Home (`/`), How training works (`/about`), and User agreement (`/terms`) pages. The sign-in form at `/login` contains the agreement checkbox. Direct `/labs`, `/classes`, `/sessions`, `/results`, `/account`, `/content`, and `/admin` requests require an authenticated session; the last two also require an administrator. Public pages answer `GET`, `HEAD`, and `OPTIONS` without granting cross-origin API access.

The public pages, sign-in screen, and Academy workspace support light and dark appearances. The switch saves the learner's choice in the browser. The embedded lab terminal retains its own high-contrast color scheme in both modes.

Use a separate Python 3.12 virtual environment. Install `backend/requirements.txt`, pytest 8.3.5 and PyYAML 6.0.2. Set `PYTHONPATH` to `backend` and `tests`, then run:

    python -m pytest tests/test_academy.py tests/test_proxmox.py tests/test_packaging.py tests/test_learning.py -q

Tests use synthetic users, passwords, sample exercises, temporary SQLite databases and a fake lab provider. These are not production credentials, actual exam content or proof of a real VM/SSH deployment.

`deploy/site.example.json` and `deploy/site.private.example.json` describe fictional, distinct 10.77/10.78 networks. Adapt them to your own explicitly chosen isolated deployment. The offline installers require separately obtained OS images, package repositories and container images. This source copy is not a populated installation medium. Live Proxmox, Guacamole, offline first boot and full VM console acceptance were not exercised by the public-copy review.

The platform's public source keeps every actual course-content bundle private. Generic tool-driven practice exercises and synthetic tests are distinct from that private curriculum. Only upload content you are entitled to distribute and restrict instructor material appropriately.

No new license has been assigned to first-party code. Third-party software is obtained separately under its own licenses; original notices supplied with dependencies must remain with them. Vendored Netlab files here are the locally authored shell/tooling source, without redistributed OS, package or image binaries.
