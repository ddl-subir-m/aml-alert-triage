#!/usr/bin/env bash
# Domino App entry point: the case-management system (App aml-case-management), MCP on port 8888.
set -euo pipefail
cd "$(dirname "$0")"
# The Domino Standard Environment already has `mcp`. Install it only when it is missing.
# (Not a root requirements.txt: Domino would install that into the agent's Jobs too.)
if ! python -c "import mcp.server.fastmcp" 2>/dev/null; then
  if command -v uv >/dev/null; then
    uv pip install --system --quiet -r case_server/requirements.txt
  else
    pip install --quiet -r case_server/requirements.txt
  fi
fi
# The state lives on the AML project's dataset aml-cases, so it survives an App restart.
# A Git-based project mounts its datasets at /mnt/data/<dataset name>.
export AML_DB_PATH="${AML_DB_PATH:-${DOMINO_DATASETS_DIR:-/mnt/data}/aml-cases/cases.db}"
exec python case_server/server.py
