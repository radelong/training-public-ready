# Lab startup estimate and getting-started guide

The signed-in Academy now displays a best-guess startup indicator while a lab is queued or its VM is being prepared. One-VM launches use a 90-second planning estimate; paired-VM launches use 180 seconds. The bar remains incomplete until the backend reports that the workspace is ready, and it reports longer-than-usual startup without implying a timeout.

The new **Using the labs** page contains an offline MP4 walkthrough, English captions, a readable transcript, and a four-step reference. The video shows the lab catalog, launch and preparation, embedded consoles, Hint and Solution, verification, reset, end, and saved results. It uses synthetic learner content and contains no live accounts or lab data.

The update changes only the Academy frontend and static tutorial assets. It does not change authentication, backend APIs, lab images, or session behavior.

Validation: the 13 startup-estimate tests and 3 guide-asset tests pass; JavaScript syntax checks and `git diff --check` pass. The signed-in production guide page rendered, and the live video endpoint returned HTTP 206 for a 1,024-byte range request.
