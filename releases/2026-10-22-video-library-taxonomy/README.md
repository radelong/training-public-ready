# Video library drag-and-drop and taxonomy administration

Production update: `2026.10.22-video-taxonomy-1`

Administrators can drag videos to reorder them within a topic, use keyboard controls to reorder, move or rename a topic group, and rename a creator across its topics. The Academy stores creator/topic overrides by media-relative path; video media remains in read-only storage. Admin API routes require administrator authorization. Existing order data and Cloud Computing classification remain supported.

Production installation completed on 23 October 2026 UTC. The administrator video library at `https://60thtraining.com/videos` displayed drag handles, topic edit controls, and creator rename controls. Cloud Computing appears under **Eli the Computer Guy → Cloud Computing**. The catalogue contains 37 videos, including 15 in that topic. No production video order or taxonomy labels were changed during acceptance. Production API health returned `{"status":"ok","database":"ready"}`; API, worker, web, and database services were healthy.

The installed update archive SHA-256 is `41be631e161acfb4f976922e1993226c0c098fa4a4aef73a886b946a39bd5f24`. Local Academy and app-update tests passed 34 cases. Public-source Academy tests passed 25 cases; JavaScript syntax and `git diff --check` passed. The public test output includes one pre-existing AnyIO deprecation warning.

This is a focused update for a compatible existing installation, not fresh-install media. The update contains no video media, learner data, site credentials, or private course answer keys.
