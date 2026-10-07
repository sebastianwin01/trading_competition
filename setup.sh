#!/usr/bin/env bash
set -euo pipefail

sdk_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        exec "$candidate" "$sdk_dir/scripts/setup.py" "$@"
    fi
done
printf '%s\n' 'Install Python 3.11 or newer, reopen your terminal, and rerun setup.sh.' >&2
exit 1
