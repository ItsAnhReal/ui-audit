#!/bin/bash
# Claude Code on the web: install the package so tests and the CLI work.
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:-.}"
python3 -m pip install --quiet --break-system-packages -e ".[dev]"
