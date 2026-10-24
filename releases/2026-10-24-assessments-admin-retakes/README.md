# Academy assessments and administrator exam retakes

The Academy now serves separate Overall readiness and Graduation assessments, each with 80 mixed questions and a one-question, Next-only viewer. It saves progress at each step and shows area scores after submission. The protected question bank and answer keys are not in this public repository.

Administrators can select a learner and reopen one exam or all exams from Administration. This covers Academy assessments, class opening pretests, module quizzes, and class final exams. Earlier graded results, audit history, and class progress remain saved. Unfinished attempts close to edits. Resetting a class opening pretest offers it once more; the learner may take or skip it.

The production application update is version `27-admin-exam-retakes-2026-10-24`. The offline GDP installation set contains updates 25, 26, and 27 in order, with checksums and a protected assessment bank in update 25. This repository contains source and tests, not a fresh-install VM image or private learner data. The local test suite passed 91 tests; production API health and the administrator controls were checked at `60thtraining.com`.
