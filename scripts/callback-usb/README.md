# Callback Lab USB repair for an installed GDP Academy

This is an add-on, not a fresh server installer. Finish the base GDP installation before using it. It restores missing Callback Sender/Listener templates 9251 and 9252, installs the version-gated Callback worker fix, tests disposable clones, and enables the existing Callback lab. It retains accounts, passwords, graded history, other labs, classes, games, videos, network configuration and existing lab CPU/RAM choices.

## What the failure meant

On the new server, template 9252 had a different SHA-256 and `zstd -t` reported `Data corruption detected`. Both original Desktop backups match their release hashes and pass complete decompression. The failed copy/read must be replaced; disabling checks cannot make a damaged backup restore successfully. The separate CRLF manifest issue and VEPA bridge-output false alarm are not evidence that the original Callback disks are damaged.

## The terminal startup fix

Ubuntu's `.hushlogin` hides its banner but does not prevent PAM from generating that banner first. The optional dynamic MOTD hooks delayed SSH channel startup on the tested Callback VMs. The included worker prepares each role with Ubuntu's `noupdate` option on only the optional dynamic MOTD session line. Authentication, account rules, session policy and SSH host-key checks are retained.

The updater accepts only the known base worker or this exact fixed worker. It backs up the old worker and changes one application file. The API and ready learner consoles remain running. The worker restarts under the existing database allocation mutex after queued/running lab actions have finished. If the installed source differs, the updater stops rather than overwriting another version.

## The exercise-start fix

The verified older template snapshots do not contain the newer `arm` guest-control action. The current worker previously called that missing action after configuring both roles, which stopped the first exercise with `Drill could not be started`. The included worker now performs the final Listener arming step through Python already installed in both supported templates. It verifies the Listener role and both allocated addresses, clears earlier heartbeat records, and records a new grading boundary only after both role setups succeed. This preserves the requirement for a new heartbeat after exercise setup and does not replace existing templates or learner results.

## Before starting

- The server already runs Proxmox VE 9 or newer and the GDP Academy services VM.
- The base install reports complete. Its settings remain at `/root/academy-bootstrap/site.json`.
- Sign in as an administrator and end any existing Callback session. Other ready lab sessions may stay running. Wait for queued/running lab actions to finish before the worker update.
- Allow 8 GiB RAM for two temporary test VMs plus 2 GiB host reserve. The installer refuses an insufficient budget.
- Keep at least 8 GiB available on the existing lab VM storage for recovery and acceptance.
- Templates 9251/9252 must be absent or recognizable, unlocked Callback templates. Existing unrelated VM IDs are never overwritten.
- Copy the entire **Callback Lab USB Repair** folder to the external drive. exFAT is recommended. Safely eject and reconnect the drive after copying, then verify the actual external-drive copy, not just the original folder. Reconnecting forces a fresh device read instead of relying on the copy operation's filesystem cache.

## Verify the drive copy before transporting it

On Windows, open PowerShell in this folder and run `./VERIFY.ps1`.

On Ubuntu, open Terminal in this folder and run:

```bash
python3 verify_package.py
```

Every file must pass. `MANIFEST.json` supports normal Windows and Linux line endings; file contents must still match their hashes. If a file fails, recopy it from the verified original. If repeated copies or reads fail, use another drive, cable or USB port.

## Install on the Proxmox server

1. Connect the verified external drive to the Proxmox server.
2. Open the Proxmox node's **Shell** as root from any learner/admin computer. No native desktop or VLC is needed.
3. If the drive is not already mounted, mount its correct partition read-only. For a drive labelled exactly `ACADEMY`, type these commands separately:

```bash
mkdir -p /mnt/academy
```

```bash
mount -o ro /dev/disk/by-label/ACADEMY /mnt/academy
```

4. Assuming the folder is directly inside the drive, type this single command:

```bash
bash "/mnt/academy/Callback Lab USB Repair/INSTALL.sh"
```

5. Read the preflight summary and type `yes`. It starts a background service and shows progress. Keep the USB mounted until completion, even if the shell is closed.
6. Wait for `CALLBACK REPAIR COMPLETE`. The private receipt and log are in `/root/academy-callback-repair/callback-usb-20261107-r4/`.
7. Sign into the Academy, open Callback, and confirm that Sender and Listener open distinct terminals and accept input. Check `hostname` and `ip -4 -brief address`; the two roles must differ. Start an exercise and confirm both role setup operations finish. Full live browser acceptance is separate from the installer's disposable-pair smoke check.

The normal Academy worker still provides the independent, authenticated terminals and normal per-learner isolation. The add-on does not create another Cloudflare tunnel, change certificates or change the Academy's concurrent-session limit.

## If it stops

- **Checksum/size/decompression failure:** no VM or catalog repair is started. Replace the named source file or USB transport. Never edit its expected hash.
- **Base installation not complete:** finish or recover that base install first. This add-on does not rewrite its saved state or install missing classes/games.
- **Callback session/job exists:** end only that session through the Academy, wait for cleanup, and retry.
- **VM ID occupied/locked or bridge differs:** preserve it. Do not delete or reconfigure an unknown VM or the LAN bridge. Review the private log and configuration with the administrator.
- **Insufficient acceptance RAM:** finish/end some disposable lab sessions normally or add host RAM; retry after enough memory is free.
- **Acceptance failed:** Callback stays disabled. Existing learner records and unrelated VMs remain. Inspect the logged stage and recorded test IDs; do not delete the repair state to force a retry.
- **Saved guest process still active:** wait. The recorded `guest_pid` is in `transaction.json`. Do not start a second repair while it is still executing.
- **Catalog changed during repair:** stop and review the administrator's change; the add-on refuses to overwrite it.
- **Different package bytes:** saved repair state is tied to the exact manifest. Use the original matching release; do not replace files mid-repair or delete the state.

Native guest-command failure details are retained in the private `last-guest-result.json` beside the transaction log. That file may contain private diagnostics; keep it on the server and do not publish it.

Read-only preflight can be repeated with:

```bash
bash "/mnt/academy/Callback Lab USB Repair/INSTALL.sh" --check
```

After the cause is corrected, repeat the normal installation command. Matching existing templates are accepted only after role checks; the add-on never restores over occupied IDs. A partial restore with an unrecognized/locked VM requires administrator inspection.

View progress after reconnecting:

```bash
tail -f /root/academy-callback-repair/callback-usb-20261107-r4/install.log
```

## Rollback

The add-on takes a private PostgreSQL backup in the services VM before changing the Callback entry. The receipt records the path. Backups remain on the server; they are not written to the USB or GitHub.

To restore the previous Callback catalog settings and the previous worker when this repair changed it, first end any Callback session and wait for queued/running lab actions to finish, then run:

```bash
bash "/mnt/academy/Callback Lab USB Repair/INSTALL.sh" --rollback
```

Rollback preserves templates, all learner results and other catalog entries. The original worker backup is `worker.before.py` in the private database-backup directory recorded by the receipt; only the exact worker installed by this repair can be restored automatically. If Callback did not previously exist, it is left disabled instead of deleting history. It refuses to overwrite subsequent administrator edits. A whole-database restore is not the normal rollback and could discard later learner work; do not run one without a separate recovery plan.

## Scope of proof

The installer verifies the worker update and shared offline-login preparation, both compressed backups, role-specific peer configuration, distinct hostnames, ECDSA host-key availability, a new synthetic HTTP heartbeat, and removal of its disposable clones before enabling Callback. It does not claim to prove a user's browser input, every exercise, or two simultaneous learners; record those separately in the release acceptance report.
