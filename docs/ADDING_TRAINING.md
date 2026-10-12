# Adding training to the Academy

The Academy now includes a learner Class catalog and an administrator Content
manager. Everything is stored on the local services VM and works without the
internet. The existing Lab catalog still contains Netlab and the inactive Linux
Lab placeholder; additional entries appear only when an administrator adds them.

## Create a slideshow class

1. Sign in with an administrator account and open Content manager.
2. Select Create class and enter the title and description.
3. Select Add module. Enter a module title and lesson instructions.
4. Upload a PDF exported from your slide deck. Each PDF may be up to 50 MB.
   Repeat for additional modules and use Move up / Move down to arrange them.
5. Optionally attach an existing lab to a module. A module may contain slides,
   a lab, or both. Activate required linked labs before publishing.
6. Add final exam questions, configure the exam, then Save draft.
7. Use Preview draft to review the modules and administrator answer keys.
8. Select Save and publish when the class is ready for learners.

The slide PDF appears inside the class webpage using the browser's local PDF
viewer. Learners can use its page controls, zoom, download and print features.
No online rendering service is used. PDF preserves slide layout but does not
retain PowerPoint animations or narration. Export to PDF before uploading;
PowerPoint-to-PDF conversion is not included in this release. The Academy
remembers the learner's current module and completed modules, rather than the
PDF viewer's exact page position.

## Build a final exam

Add questions directly in the editor or download the question CSV template and
fill it using a spreadsheet editor. Save it as UTF-8 CSV and import it. Import
appends questions to the current draft; question IDs must be unique. Review the
imported questions and save the draft before leaving the editor.

Supported question types are multiple_choice, true_false and written. The CSV
uses option_a through option_d with an A–D correct_answer for multiple choice;
True or False for true_false; and a rubric for written questions. Direct editing
supports up to eight choices per question. A class may have up to 200 questions.
Points are weighted: the percentage is total awarded points divided by total
possible points. Defaults are an 80% passing score and three attempts. Both can
be changed before publication.

Use the separate **Answer key and grading** section to review correct answers and point values. Each objective question requires an explanation of the correct answer before publication. Optional explanations for individual choices explain why a selected answer is right or wrong. Written responses use instructor rubrics and manual grading.

You may upload questions with their keys in the question CSV, or download this exam's separate answer-key CSV, edit it, and upload it back. Match question IDs exactly; the separate key must contain one row for every question. It accepts A–H for multiple choice and True/False for true/false. The question CSV supports general explanation and explanation_a through explanation_d; the separate answer-key template supports explanation_a through explanation_h. Review all imported material and save the draft.

Multiple-choice and true/false questions are automatically graded on the server against the saved key. Keys, rubrics and explanations are hidden while an attempt is in progress. After submission, both passing and failing learners see correct/incorrect results, the correct objective answers, and instructor-authored explanations. Written answers show awarded points and feedback after manual grading; no final percentage or pass decision is issued before that review is complete.

Each new attempt shuffles the question order on the server and saves it with that attempt. Resuming an unfinished exam keeps its order and saved answers. Retakes use a different order when the exam contains more than one question. Answer choices stay in their authored order. Shuffling changes presentation; it does not create a new question bank.

Learners select Save answers to resume an unfinished attempt. Selecting Submit
final exam locks the answers. An unfinished attempt resumes rather than consuming
another attempt. A submitted written exam blocks another attempt until grading
is complete. Administrators open Content manager > Grade written exams, award
points against each rubric and save the final grade with optional feedback.
An administrator cannot grade their own written exam.

## Learner progress and published versions

Learners open Class catalog, complete the modules and take the final exam.
Mark module complete records learner-confirmed progress. It is not a measurement
of attention or a tamper-resistant assessment of lab mastery. Required module
completion can gate entry to the exam. My results contains both lab verification
history and class progress/exam results.

Saving an administrator draft does not change an existing published class.
Publishing creates an immutable version. A learner already enrolled can resume
that version through My results, even after a later version is published.
Unpublish removes the current class from the catalog while retaining existing
enrollments, slides and results. This first release does not permanently delete
classes or uploaded PDFs; include content storage in capacity planning.

## Add a VM lab

The recommended process is the offline lab-package workflow in
`IMPORTING_LABS.md`. It packages a qcow2/raw VM disk and learner-facing metadata,
installs and acceptance-tests the template from USB on Proxmox, then generates a
small receipt that Administration imports. This avoids browser-uploading a large
VM image and keeps root-level Proxmox operations outside the web application.

For the Linux training environment you plan to provide, use the existing Linux
Lab placeholder. Prepare and validate its offline Proxmox template first, register
its template VM ID for the restricted provisioning account, then save that ID
and activate Linux Lab in Administration. Uploading training files alone does
not produce a launchable VM.

For a genuinely new lab, select Add lab in Administration or Content manager.
Enter a unique ID, title, description, template VM ID, CPU and RAM requirements.
Optionally upload exercise definitions matching lab-exercises.example.json.
The entry is created inactive. Each exercise ID must match the guest actions
implemented inside that VM; the JSON file supplies instructions, not executable
host commands. The guest must provide Ubuntu, SSH, cloud-init, QEMU guest agent,
the Academy readiness marker and /usr/local/sbin/academy-lab action interface.
See ARCHITECTURE.md for that contract. Register the template with the supplied
register-template.sh on Proxmox before activating it in Administration. The
activation check verifies the Proxmox template flag; it does not replace offline
boot, readiness, exercise, console and isolation acceptance tests.

## Offline upgrade, backup and recovery

For an existing installation, extract the new full offline media on the Ubuntu
services VM and run sudo bash scripts/upgrade-services.sh EXTRACTED-MEDIA.
The upgrader verifies the media, refuses to interrupt queued/running lab jobs,
backs up the existing application/database/configuration/content, loads the
service images and updates the application. The release adds new tables without
altering the existing lab/user/result tables. It retains site settings and live
catalog activation/template IDs. The API restarts briefly; a learner's terminal
may need Reconnect. Existing learner VMs are retained. The installer script is
for new installations; use the upgrader for existing deployments.

Slide PDFs are stored in the services installation's content directory, mounted
at /var/lib/academy/content inside the API. PostgreSQL stores drafts, published
versions, progress, answers and grades. Lab VM disks remain on Proxmox lab
storage. The updated backup.sh stops the API and worker briefly to produce a
consistent database/content backup, then restarts them. Keep the database dump,
content archive and private configuration archive from the same recovery point
together. Restore the content archive as well as the database; see OPERATIONS.md.
Generic installation media does not contain your subsequently uploaded classes
or learner results. Keep site backups separately from deployable media.

## Materials needed to publish real training

Provide slide decks exported as PDF, class/module titles and descriptions,
question sets with correct answers and points, and rubrics for written questions.
Specify passing scores, permitted attempts and answer-feedback policy. For Linux
Lab activation, provide its actual training environment and required offline
files/dependencies so its template can be built and validated.
