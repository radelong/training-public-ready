# Academy application update 28, revision 3

This candidate adds required 80% module checks, ordered module progression, assessment recommendations and a game-exit warning. It keeps the VM seat limit unchanged. Revision 3 also lets learners and administrators reopen graded assessment results, updates their recommendations against the current catalog, and restores older saved course positions to the first unfinished required module.

Copy this complete folder to an Academy services VM running application update 27, then run `sudo bash install-guarded.sh`. The wrapper checks its files and the update 27 application baseline, refuses active lab sessions or jobs, creates and checks database, application, configuration and content backups, and runs the bundled installer. Preserve both printed backup paths. It stops if the installed baseline differs; investigate rather than forcing it.

This candidate has not been accepted on production. The GDP fresh installer also uses this update after creating its services VM; that full installation still requires an empty-node acceptance run. Module checks use existing questions. Game-specific progress fixes require checking the deployed game files and retaining their identities and learner progress.
