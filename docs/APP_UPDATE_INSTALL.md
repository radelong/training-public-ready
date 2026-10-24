# Academy application update

This package updates the Academy application on an existing services VM. It does not install Proxmox, create a new services VM, or contain lab VM images. Use the full offline installation media for a new server.

## Install

1. Copy the verified `.tar.gz` update to the Academy services VM using approved removable media or the site's trusted file-transfer path.
2. Extract it into a new temporary folder:

   ```bash
   mkdir -p /var/tmp/academy-update
   tar -xzf Training_Academy_App_Update_<version>.tar.gz -C /var/tmp/academy-update
   ```

3. Run the bundled installer as root:

   ```bash
   sudo bash /var/tmp/academy-update/academy-update/scripts/install-app-update.sh \
     /var/tmp/academy-update/academy-update
   ```

The installer verifies every file before it changes the application. It stops if lab jobs are queued or running. It backs up the database, application, site configuration, and course content under `/root/academy-backups/`, then restarts only the Academy API, worker, and web services. It does not stop learner VMs or change lab templates.

## Verify

For update 27, sign in as an administrator and open **Administration → Exam retakes** for a selected account. Reset one exam, then confirm the learner can start a new attempt while prior graded results remain in **My results**. Reset all exams only when the learner needs every assessment reopened. A reset closes unfinished earlier attempts to edits. The opening class pretest reappears on the next class entry; skipping it closes that reset opportunity without changing saved module completion. The `exam_resets` table is created automatically when the updated API starts. The application installer verifies it before reporting success.

Wait for `Application update complete` and `Application schema and API health verified`. Open the Academy in a browser, sign in, and check the lab and class catalogs. Open **Video library** as an administrator. Drag a video by its grip or focus the grip and press Up or Down; verify order after refresh. Use **Move or rename this topic** to change the creator/topic for every video in the selected topic. Use **Rename creator everywhere** to rename a creator across all its topics. Verify that learner accounts cannot see or submit these controls. Existing order, creator, and topic overrides persist by media path. The Cloud Computing series starts under **Eli the Computer Guy → Cloud Computing**. Confirm existing sessions and results remain available before deleting the temporary extraction folder.

If an install step fails, the installer restores the prior application files and restarts the prior services. Keep the printed backup path and its `SHA256SUMS` file with the release record.

For the video library, administrators can drag or keyboard-reorder videos, edit the creator/topic for all videos in a topic group, and rename a creator across all topics. The update adds nullable taxonomy columns to the existing video order table; migration runs automatically at application startup. Verify drag order, a topic move, a creator rename, refresh persistence, and learner authorization after installation.

For classes with a combined pretest, verify a learner's first class entry shows **Class pretest** before any module slides. Confirm **Skip pretest and start class** opens the first module and reopening the class goes straight to its saved module. Start but do not submit a pretest, leave the class, and reopen it; the unfinished attempt must resume. Classes without a combined pretest must open directly to their module.

If this release includes the private class-pretest bundle, back up the database again before importing it. Copy `class-pretest-proposals.json` to a root-only directory on the services VM. Copy `scripts/import-class-pretests.py` from the extracted update into the API container, then run it once without `--apply`. Review every class title, module count and question count. The dry run must validate all records and report no database changes. Run it again with `--apply` only after the complete list matches the approved class set. The importer checks the exported class revision and published version, verifies other course content and slide assets, and publishes all class versions in one transaction. Existing enrollments retain their earlier versions.

## Release handling

Keep the `.tar.gz` and its SHA-256 sidecar together. Verify the sidecar before installation. Store prior completed releases as rollback points. Do not publish course answer keys, learner data, secrets, or VM images in the public source repository.
