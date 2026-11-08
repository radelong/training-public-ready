#!/usr/bin/env bash
# Start a guarded add-on for an already installed GDP Academy.
set -euo pipefail
package="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec python3 "$package/install_callback.py" "$@"
