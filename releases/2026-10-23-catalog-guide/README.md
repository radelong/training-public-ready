# Lab catalog tutorial update

The How to use the labs video and workflow steps now appear at the top of the Lab catalog. The separate Using the labs navigation tab is removed. Older `/lab-guide` and `/labs?view=guide` links open the catalog. Captions, transcript, player controls, and startup status remain.

This static-only update targets the captured production frontend. It changes `index.html` and `academy.js` only. It does not restart services or change accounts, database, authentication, labs, VMs, or console grants.

## Install

1. Copy and extract this folder on the Academy services VM.
2. Run `sha256sum -c SHA256SUMS.txt`.
3. Run `sudo bash install-update.sh`.
4. Reload the Academy. The video should be above the catalog heading and lab cards.

The installer refuses an unexpected baseline and prints a rollback backup path. Use `rollback-update.sh` with that path to restore.
