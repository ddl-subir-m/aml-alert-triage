"""The App deployment policy (governance/app-deployment-policy.yaml) and its scripted check (governance/validation_status.py), for
domino-agent-service spec #260 (ticket #266), seen from outside.

The policy: the YAML parses, and it has the three stages (Intake, Validation, Approval), the two validators' evidence items with their
four fields, and the scripted check, with the placeholders that the live script fills.

  python tests/check_validation_policy.py

One line per case, with a non-zero exit code on any failure. The policy part needs PyYAML (`pip install pyyaml`). No Domino host and
no App: the live check is domino-agent-service #270.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "governance" / "app-deployment-policy.yaml"
failed = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{str(detail)[:600]}]" if detail and not ok else ""), flush=True)
    if not ok:
        failed.append(name)


# ------------------------------------------------------------------------------------------------------------------- the policy
try:
    import yaml
except ImportError:
    yaml = None
check("PyYAML is installed, to parse the policy (pip install pyyaml)", yaml is not None)
raw = POLICY.read_text() if POLICY.is_file() else ""
check("governance/app-deployment-policy.yaml is in the repo", bool(raw))
policy = None
if yaml is not None and raw:
    try:
        policy = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        policy = e
check("the policy YAML parses to a mapping with a list of stages",
      isinstance(policy, dict) and isinstance(policy.get("stages"), list), policy if not isinstance(policy, dict) else list(policy))
policy = policy if isinstance(policy, dict) else {}
stages = [s for s in policy.get("stages") or [] if isinstance(s, dict)]
check("it has three stages, in this order: Intake, Validation, Approval", [s.get("name") for s in stages] == ["Intake", "Validation", "Approval"],
      [s.get("name") for s in stages])
stage = {s.get("name"): s for s in stages}


def items(name):
    """The evidence items of a stage, by their name."""
    return {e.get("name"): e for e in (stage.get(name) or {}).get("evidenceSet") or [] if isinstance(e, dict)}


def fields(item):
    """An evidence item's artifacts that take an input, as (label, type, option values) in their order."""
    out = []
    for a in (item or {}).get("definition") or []:
        d = a.get("details") or {} if isinstance(a, dict) else {}
        if isinstance(a, dict) and a.get("artifactType") == "input":
            out.append((d.get("label"), d.get("type"), [o.get("value") if isinstance(o, dict) else o for o in d.get("options") or []]))
    return out


evidence = [e for s in stages for e in s.get("evidenceSet") or [] if isinstance(e, dict)]
ids = [e.get("id") for e in evidence]
check("each evidence item has an ID of its own that starts with Local. (Domino keeps the rest as the item's externalId)",
      ids and all(isinstance(i, str) and re.fullmatch(r"Local\.[a-z0-9-]+", i) for i in ids) and len(set(ids)) == len(ids), ids)
check("each evidence item has a name, a description and a definition (its artifacts)",
      evidence and all(e.get("name") and e.get("description") and isinstance(e.get("definition"), list) for e in evidence),
      [e.get("name") for e in evidence])

intake = items("Intake")
check("Intake has one evidence item, Intake (Local.app-intake)", list(intake) == ["Intake"] and intake["Intake"].get("id") == "Local.app-intake",
      {n: e.get("id") for n, e in intake.items()})
got = [(label, kind) for label, kind, _ in fields(intake.get("Intake"))]
check("...with the inputs that the analyst fills: Purpose (textarea), Users (textinput), Data class (radio)",
      got == [("Purpose", "textarea"), ("Users", "textinput"), ("Data class", "radio")], got)
data_class = [opts for label, _, opts in fields(intake.get("Intake")) if label == "Data class"]
check("...and Data class has the options Public, Internal, Confidential, Restricted",
      data_class == [["Public", "Internal", "Confidential", "Restricted"]], data_class)

validation = items("Validation")
VALIDATORS = {"Validation (agent folder)": "Local.validation-agent-folder", "Validation (LangGraph)": "Local.validation-langgraph"}
FOUR = [("Verdict", "radio", ["approve", "approve after fixes", "do not approve"]), ("Critical vulns", "radio", ["yes", "no"]),
        ("Summary", "textarea", []), ("Doc location", "textinput", [])]
for name, want_id in VALIDATORS.items():
    item = validation.get(name) or {}
    check(f"Validation has the evidence item \"{name}\" ({want_id})", item.get("id") == want_id, {n: e.get("id") for n, e in validation.items()})
    got = fields(item)
    check(f"...with four fields: Verdict, Critical vulns (yes or no), Summary, Doc location, and only those", got == FOUR, got)
    check(f"...and it has no other artifact (a validator fills every one)", len(item.get("definition") or []) == 4, item.get("definition"))
values = [v for s in stages for e in s.get("evidenceSet") or [] if isinstance(e, dict) for _, _, opts in fields(e) for v in opts]
check("every option value is text (quoted: an unquoted yes or no is a boolean to a YAML 1.1 reader)",
      values and all(isinstance(v, str) for v in values), [v for v in values if not isinstance(v, str)])

sys.exit(1 if failed else 0)
