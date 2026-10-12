# Development tests

These tests are for developers/staging, not for the offline learner installation. Run with Python 3.12 and the pinned application dependencies, plus pytest 8.3.5 and PyYAML 6.0.2. From the source root:

```bash
export PYTHONPATH="$PWD/backend:$PWD/tests"
python -m pytest tests/test_academy.py tests/test_proxmox.py tests/test_packaging.py tests/test_learning.py -q
```

SQLite is used only for these application tests. `fakes.py` is a test provider; it never appears in the production Docker image or the real worker. The real production worker requires PostgreSQL and the Proxmox adapter.

The connected media builder runs `container-check.sh` against real PostgreSQL/Guacamole images and the practice-container image before packaging. Its `container_smoke.py` refuses any database name other than `academy_build_check`. The compose check stack publishes no host ports and uses a temporary database filesystem.

The deployment's hardware/network/console acceptance checks are in `docs/ACCEPTANCE.md`. A successful fake-provider test must not be reported as a real VM deployment or SSH console test.
