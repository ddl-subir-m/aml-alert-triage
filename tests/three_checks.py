"""The shared parts of the checks of the three validation checks: tests/check_purpose_and_data.py (check 1),
tests/check_architecture_and_access.py (check 2) and tests/check_vulnerability_scan.py (check 3), domino-agent-service spec #388.
Stdlib only. Each check imports it from its own folder (tests/), so that the three read their files and judge the same way.

- check(), done(), text(): one line per case, and exit 1 on any failure.
- load_checks(): governance/checks.json, the one source of the names and labels, and one check's entry, found by its folder.
- rules(), blocks(): one case for each rule that a line (or a paragraph) of a text says.
- LEAK, leaks(): what the public repo must not hold.
- The seam part, for a local agent service (the service's seam helper, tests/agent_folder_seam.py, on Linux): the event bundle's GET,
  a stage move, its publish to the subscription, the Job that it starts, and that Job's spec. These import the service's own modules
  (agent_service, requests) only when they run, from AGENT_SERVICE_REPO.
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failed = []


def check(name, ok, detail=""):
    """One case: its line, `ok` or `FAIL`, with the detail of a failure."""
    print(("ok   " if ok else "FAIL ") + name + (f"  [{str(detail)[:600]}]" if detail and not ok else ""), flush=True)
    if not ok:
        failed.append(name)


def done(skip=None):
    """The end of the check, with a SKIP line that says why the rest did not run. Exit 1 when a case failed."""
    if skip:
        print(f"SKIP: {skip}", flush=True)
    sys.exit(1 if failed else 0)


def text(path):
    """The file's text, or "<the error>" when it can't be read (a case then fails on it)."""
    try:
        return path.read_text()
    except OSError as e:
        return f"<{e}>"


# ------------------------------------------------------------------------------------------------------------------ checks.json
def load_checks(folder):
    """governance/checks.json (the one source of the names and labels of the three checks, ticket #392), and the entry of the check
    whose folder is `folder` (its path from the repo root, as checks.json names it). -> (the file's object, that entry or {}). A file
    that is missing or not a JSON object gives ({}, {}) and a failed case."""
    try:
        source = json.loads((ROOT / "governance" / "checks.json").read_text())
    except (OSError, ValueError) as e:
        source = e
    if not isinstance(source, dict):
        check("governance/checks.json is a JSON object", False, source)
        return {}, {}
    return source, next((c for c in source.get("checks") or [] if isinstance(c, dict) and c.get("folder") == folder), {})
