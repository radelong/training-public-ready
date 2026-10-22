# Source release review

Reviewed on 2026-10-12. Privacy scope: source, configuration, fixtures, documentation, and new Git history. Original application data, identities, live hosting configuration, submitted files, photographs, course PDFs/exam banks/instructor keys, runtime secrets and old Git history are omitted. Generic training exercises and synthetic test credentials remain as clearly identified examples.

35 application/provider/packaging/learning tests passed with synthetic data. Example site configurations and invalid configurations are covered. No live Proxmox/Guacamole/VM, nested KVM, offline image or console deployment was performed.

Secret detection: Gitleaks 8.30.1 scans run against the exact source package and all new commits, with values redacted. Additional owner/organization/chat ID, path, phone, SSN and private-key cross-checks cover every retained text file; no unresolved findings remain in the release scope. Retained files are hashed, and their inventory is in the private review report. Binary/document artifacts are excluded, so no private EXIF or document metadata is distributed.

Required MIT notices for any bundled third-party source are preserved. Application dependencies are separately fetched under their own licenses. No new first-party license has been assigned. This source review does not constitute a live deployment or a guarantee of unknown-vulnerability absence. Original applications remain unchanged.

Revision 2: every retained line is covered by a file/line inventory and owner-identifier/credential checks. User-specific names, domains, email addresses, original deployment DNS and LAN examples are omitted. Literal fixture credentials are explicitly synthetic and generic. Clean single-commit history excludes prior draft versions. Current Recipe build/TypeScript, Training 35 tests and dashboard 17 tests pass. Original backups and production remain unchanged.

Revision 3 (22 October 2026): Added the self-contained Learning games feature to the sanitized public source. The authenticated API, administrator-only upload, persistent game file storage, per-game restrictive CSP, sandboxed embedded player, and protected page route are covered by integration tests. The Academy, learning and Proxmox suites pass 35 tests; JavaScript syntax checks and `git diff --check` pass. No production accounts, learner data, user-uploaded HTML, secrets, or runtime configuration are included. Browser play in the live production site was verified separately; this public-source test run does not simulate a browser.
