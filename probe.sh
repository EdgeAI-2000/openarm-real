#!/usr/bin/env bash
# Keep the virtual environment path intact: Dora canonicalizes Python symlinks.
set -euo pipefail
probe_root="$(cd -- "$(dirname -- "$0")" && pwd)"
exec "$probe_root/.venv/bin/python" "$probe_root/probe.py"
