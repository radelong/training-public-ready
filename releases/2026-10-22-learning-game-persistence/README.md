# Per-learner learning game progress

The Academy now stores supported learning-game state per signed-in learner and game. Packet Loss uses the bridge to restore its current ticket after a learner leaves and returns. The game remains in an opaque-origin sandbox; the Academy validates its messages and performs authenticated, CSRF-protected storage requests. Saved state is limited to 128 KiB and must be a JSON object.

This release does not record game scores or completion credit. It adds an application update to the GDP package and a self-contained Packet Loss upload file. The update creates an additive PostgreSQL table and keeps existing lab and game records.

## Verification

- Academy API tests: 26 passed.
- Sanitized public-source Academy tests: 20 passed.
- JavaScript syntax checks passed.
- Live production check: Packet Loss rendered inside the Academy after reloading the page. Starting the first ticket stored progress through the authenticated API; leaving and reopening restored the “Continue: Crimp Expectations” prompt.
- GDP package verifier passed, including update 16 and the complete offline installer set.

The live check used the signed-in administrator account. No credentials, learner records, deployment addresses, or database dumps are included here.
