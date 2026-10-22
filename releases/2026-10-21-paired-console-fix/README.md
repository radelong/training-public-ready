# Callback Lab paired-console update

The production Academy now uses isolated Guacamole common-JS clients for the Sender and Listener. The prior full Guacamole iframe clients shared browser authentication state and could both open Sender or leave Listener at the Guacamole login screen. This update keeps the existing Academy login, per-VM session grants, same-origin authenticated WebSocket proxy, and one lab network.

The worker also suppresses Ubuntu 26.04 OSC 3008 prompt metadata for `learner` shells on newly cloned Callback VMs. It prevents machine ID, host, boot ID, and shell type fields from appearing as text in the terminal.

## Install

1. Copy `Academy_Paired_Console_Fix_20261021.tar.gz` to the Academy services VM.
2. Verify it with `sha256sum -c Academy_Paired_Console_Fix_20261021.tar.gz.sha256`.
3. Extract the archive, enter `academy-paired-console-update`, and run `sudo bash scripts/install-paired-console-fix.sh`.
4. In the Academy, reload the active Callback Lab workspace and select Reconnect on both terminals.
5. Run `hostname` in each terminal. Sender and Listener must show different hostnames and both terminals must accept input.

The installer verifies package hashes and accepted source versions, backs up API and worker files, installs the frontend terminal assets, restarts only API and worker containers, and checks API health. It does not reset or end sessions. If its health check fails, it restores the source backup and restarts those containers.

## Current production evidence

Installed 21 October 2026. API and worker containers restarted successfully. API health is `healthy`. The ready session remains intact: Sender `10.44.0.100`, Listener `10.44.0.108`. The deployed custom terminal page responds over the verified Academy HTTPS origin. The final in-browser check of each terminal's hostname and keyboard input is pending user confirmation.

This is an incremental update for an Academy with the Callback Lab already registered; it is not a complete offline installation image.