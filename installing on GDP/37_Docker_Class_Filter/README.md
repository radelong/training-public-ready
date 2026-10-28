# Docker class filter

The consolidated fresh installer applies this frontend-only patch after application update 28 revision 3. It adds a Docker filter for classes whose title starts with Docker while retaining their Programming category. Existing learners and results are unchanged. The patch checks the installed frontend baseline and keeps rollback copies on the services VM.

For an existing compatible Academy, verify the package checksums and run `sudo python3 install-filter.py` on the services VM. Do not run it over an unverified or different frontend baseline.
