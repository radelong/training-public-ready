# Target acceptance checks

Perform these on the actual Ubuntu/Proxmox deployment before general learner use. Record the installed ISO/image digests, host specifications, configuration, results and any exceptions. Application unit/browser tests do not prove nested KVM, SSH console negotiation or firewall enforcement.

## Installation and offline operation

1. Verify the completed media manifest and provision ISO checksum before installation.
2. Disconnect WAN/internet access while retaining the local management LAN. Complete installation from the prepared bundle.
3. Confirm KVM is available in the outer Ubuntu VM and nested Proxmox VM. Start a simple guest on Proxmox with hardware acceleration enabled.
4. Confirm the services VM and prepared templates are Ubuntu 26.04; confirm the application images match the recorded image lock.
5. Confirm every service starts without an image pull or online package install. From the services VM, run `docker compose ps` in `/opt/training-academy` and inspect cloud-init/service logs.
6. Restart the services VM and the nested Proxmox VM. Verify database/results persist and services recover without internet access.
7. Validate local DNS and clock settings. Trust the local CA on a learner workstation and verify normal HTTPS certificate validation, without bypassing browser warnings.

## Account and learner separation

1. Create two learner accounts and sign in using separate browsers/profiles.
2. Confirm learners cannot access Administration, create users, change templates or release other users' seats.
3. Launch the same network lab for both accounts. Confirm different Proxmox VM IDs, disk volumes, SSH keys, IP addresses and host keys.
4. Repeatedly select Start/Open for one learner's existing lab. Confirm it reconnects to the same VM instead of cloning another.
5. Attempt the other learner's session API/console URL under the first learner's login. Expect refusal.
6. Sign out while a terminal is open. Confirm its connection is revoked within the gateway's two-second WebSocket authorization interval and cannot be reopened with the prior token.
7. Change a password while another login exists. Confirm the other login and its console stop working.

## Real console and netlab exercises

1. Activate the verified networking template. Launch a learner VM and confirm its terminal opens automatically **inside the portal page** when the VM becomes ready.
2. Verify `lsb_release -a`, `sudo netlab doctor` and `sudo netlab list` inside the guest. Resolve any missing Ubuntu 26.04 tool/dependency issue before acceptance.
3. Select and start `net-01-link-down`. Check before repair; expect Not yet.
4. Inside the embedded terminal, run `sudo netlab exec client ip link set eth0 up`. Select Check my work; expect Pass and a persisted result.
5. Work through all 28 Netlab exercises, including networking, firewall and Kubernetes tasks. For fault drills, prove the injected fault fails and the documented repair passes. Include NAT/MTU and INPUT/FORWARD rule-order cases; merely booting the VM does not validate these behaviors on Ubuntu 26.04.
6. Close the workspace and return during the session. Confirm VM files/state remain and the embedded terminal reconnects.

## VM isolation and lifecycle

1. With two learner VMs running, attempt direct SSH/TCP communication from learner A to learner B and from a learner to the services management/lab IP. Expect new learner-initiated connections to be blocked.
2. With administrative root inside a learner guest, change the guest's IP/MAC and attempt the same traffic. Confirm Proxmox MAC/IP filtering prevents bypass. Confirm the actual active node firewall implements these rules; configuration alone is insufficient evidence.
3. Confirm guacd can still reach its assigned VM and that the guest-agent checks work despite the network restrictions.
4. Create a file in learner A. Restore its clean VM. Confirm the file is gone, the generation/SSH credentials changed, its old console token is rejected, and learner B's VM is unaffected.
5. Confirm A's previously recorded results remain after reset.
6. End A's lab. Confirm its VM configuration/disk are deleted, its seat is available, its terminal closes and results remain. Relaunch; confirm a new session UUID.
7. Set a short expiry in a test configuration. Confirm console revocation at expiry and eventual VM deletion by the worker.
8. Occupy the configured seat count. Confirm additional launches get the capacity message and do not create unmanaged VMs.

## Linux Lab after the site supplies its content

1. Keep the Linux Lab entry inactive until the site's uploaded training image and exercises are installed in a new approved template.
2. Verify every required package, image, guide and exercise works with outbound internet disconnected.
3. Register the approved template with the restricted Proxmox account, then activate Linux Lab and launch it for two test learners.
4. Confirm separate VM disks, credentials and results; test reconnect, restore and end-lab behavior.
5. If the uploaded lab uses containers, confirm its image is local and that containers cannot reach the services host or another learner's VM.

## Failure and recovery

1. Stop the worker during a clone. Restart it and verify the marked clone is reconciled without creating an extra VM.
2. Start a second worker container. Confirm it cannot acquire the election lock while the first is active.
3. Temporarily interrupt Proxmox API access. Verify jobs fail visibly, reserved seats are retained and Retry works after access returns.
4. Create an unrelated VM at a reserved ID during a controlled test. Confirm the backend refuses to configure/delete it because its ownership marker differs. Resolve the conflict manually before retrying.
5. Interrupt a reset or end operation, restart the worker, and check that the old console remains revoked and eventual state/storage are correct.
6. Restore a database/config backup into a separate test services VM. Confirm accounts, results and encrypted credential recovery using the matching master key. Keep the original worker stopped during this isolated restoration test.

## Capacity trial

Begin with two concurrent learners. Measure clone/boot/console response, RAM usage, disk allocation and storage latency at 2, 4 and the intended seat count. Allow for the services VM, Proxmox overhead, linked-clone growth and mixed lab RAM settings. Reduce seat count or move Proxmox onto physical hardware if the nested arrangement does not meet the site's performance standard. This release does not contain a measured throughput guarantee.

The Netlab template contains an offline Kubernetes cluster and workload images. A clean clone has passed the first Deployment and Service exercise without internet access. The remaining Kubernetes exercises still require individual acceptance checks before general learner use. Other capability labs are outside this two-lab release.
