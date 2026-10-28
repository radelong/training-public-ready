# Game progress bridge update

The live Academy received these two game assets on 28 October 2026. They keep the same game IDs and learner progress records. The update script checks the exact original and replacement SHA-256 values, backs up both originals, then updates both database records and files. It is specific to the IDs and exact source versions recorded in that script; do not apply it to a different Academy without first adapting and testing it.

The fresh GDP installer already includes the updated games in its six-game content archive. Do not run this script after a fresh installation. Browser load and isolated protocol checks passed; a real save and reopen remains to be verified.

On the existing Academy, backups are in `/opt/uscc-academy/content/.game-progress-r3-backup` and the pre-application-update database and content backups are retained under `/root/academy-backups/`. Restore files and matching game metadata together if rollback is required; do not replace the whole database merely to roll back these two games.