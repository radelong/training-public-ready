# Operations and recovery

## Routine service checks

Run on the services VM:

```bash
cd /opt/training-academy
sudo docker compose ps
sudo docker compose logs --tail 100 api worker
```

The API health check covers database connectivity. Administration displays the worker's last scheduling heartbeat and assigned seats. During a long clone, its last scheduling heartbeat can be older while the job is still running; inspect the Proxmox task and worker logs before declaring it stopped. A second worker fails election and does not compete with the active worker.

The portal retains short action output and verification history. Proxmox keeps VM tasks and administrative logs. Nginx URL logging and API access logging are disabled so console tokens do not enter access logs. Set appropriate local retention for PostgreSQL audit/result rows and container logs through the site's operations policy.

## Backups

`backup.sh` briefly stops the API and worker, then writes a PostgreSQL custom-format dump, a content archive containing uploaded slide PDFs, a private archive of configuration/secrets and a checksum file. Its exit handler restarts the API and worker. The private archive includes the master encryption key, restricted Proxmox token, initial administrator credential file and local TLS CA/server keys. Protect that backup accordingly. Keep the database dump, content archive and configuration archive from the same recovery point together.

Also back up the services VM, its approved templates and site configuration through Proxmox. Backing up the application database does not include VM disks. Learner work is temporary unless the organization implements an explicit export/persistence feature.

## Restore database and configuration

Restore to an Ubuntu 26.04 services VM with the same management/lab connectivity. Load the matching service image bundle from trusted media. Stop the old services worker so only one deployment can act against the reserved VM range.

In the replacement `/opt/training-academy` directory, restore the private configuration archive while keeping its permissions. Also extract the matching content archive into the installation directory, preserving owner 10001:10001 and permissions on content. Start only PostgreSQL, then restore the dump:

```bash
cd /opt/training-academy
sudo docker compose up -d --pull never database
sudo docker compose exec -T database pg_restore -U academy -d academy \
  --clean --if-exists < /path/to/database-RECOVERY_POINT.dump
sudo docker compose up -d --pull never
```

Wait for PostgreSQL readiness before the restore command. Use a fresh deployment database, or verify that replacing the selected database is the intended recovery action. This overwrites the target database contents. Retain the exact matching `.env` master key; rotating it without re-encrypting the stored keys prevents existing VM credentials from being recovered.

Compare database live-session reservations with actual Proxmox VMs before letting learners reconnect. A VM created after the backup may have a different session marker even if its VM ID matches a restored reservation. The backend will refuse to alter it. Resolve discrepancies administratively and preserve needed data; do not remove the ownership check.

## Replacing expired certificates

The initial local server certificate is valid for one year. The local CA is valid for ten years. Renew with that CA or replace the server certificate/key with site-issued files covering the configured hostname and services IP. Place the files at `secrets/web.crt` and `secrets/web.key`, retain private permissions, and restart only the web container. Validate HTTPS from a learner workstation.

If the Proxmox certificate changes, update `secrets/pve-ca.pem` with the correct trusted issuing CA and recreate the API/worker containers so their TLS clients reopen it. Do not use `verify=False` or disable certificate checks.

## Updating an installation

Build and validate new images/media on the connected staging computer. Back up the existing deployment first. On the offline services VM, load the new service archive and use the matching compose file. Retain existing site settings and secrets. A change to a lab template affects later launches/resets; validate the template before activation.

The class-catalog release adds five new tables without altering existing tables. Use the supplied upgrade-services.sh with complete verified media; it backs up the deployment and validates the new schema and service health. It refuses an upgrade while lab jobs are pending. This is an additive migration for this release, not a general future-schema migration engine. Preserve rollback images and backups. `install-services.sh` deliberately refuses to replace an existing `.env`; it is an installation script, not an upgrade script.

## Known scope boundaries

This is a single-node deployment with serial provisioning. It does not implement multi-node placement/failover, enterprise directory integration, grading resistant to a guest administrator, desktop/RDP image builds, durable learner home directories, an outer Ubuntu OS installer, or complete organizational PMO/Kubernetes templates. Those features are separate additions; the delivered system supplies local authentication, embedded SSH labs and the template-backed lifecycle described in the architecture.
