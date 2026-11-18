"""The agent folder validator (governance/validator-folder/): the App validator of the harness lane (opencode), domino-agent-service
spec #260, Implementation Decision 8, ticket #267. Seen from outside: its files as `domino-agent deploy` uploads them, its checklist
skill as the agent reads it, the templates of its event subscription, and the agent that a local agent service registers from it.

  python tests/check_validator_folder.py                                                    # the files only
  AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_validator_folder.py   # on Linux: everything (README)
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "governance" / "validator-folder"
UPLOADED = ("definition.md", "instructions.md", "skills/app-validation/SKILL.md")   # what deploy uploads of the folder
failed = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{str(detail)[:600]}]" if detail and not ok else ""), flush=True)
    if not ok:
        failed.append(name)


def done(skip=None):
    if skip:
        print(f"SKIP: {skip}", flush=True)
    sys.exit(1 if failed else 0)


def text(path):
    try:
        return path.read_text()
    except OSError as e:
        return f"<{e}>"


def known(rel):
    """Is `rel` (a path in the folder) a file that deploy uploads? definition.md, instructions.md, skills/<name>/<file> and
    subagents/<file>.md (the service's docs/definition-file.md, "The limits and the refusals")."""
    parts = rel.split("/")
    return rel in ("definition.md", "instructions.md") or (len(parts) >= 3 and parts[0] == "skills") \
        or (len(parts) == 2 and parts[0] == "subagents" and rel.endswith(".md"))


# --------------------------------------------------------------------------------------------------------------------- the files
every = {p.relative_to(FOLDER).as_posix(): p.read_text() for p in sorted(FOLDER.rglob("*")) if p.is_file()} if FOLDER.is_dir() else {}
files = {k: v for k, v in every.items() if known(k)}
check("governance/validator-folder/ uploads definition.md, instructions.md and one own skill, app-validation, and nothing else",
      sorted(files) == sorted(UPLOADED), sorted(files))
settings, instructions, skill = (files.get(k, "") for k in UPLOADED)
check("definition.md holds only the settings, between its two --- lines: the instructions are instructions.md",
      settings.startswith("---\n") and settings.rstrip().endswith("\n---") and settings.count("\n---") == 1, settings[-200:])

done()
