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


# -------------------------------------------------------------------------------------------------------------------- the rules
def blocks(md):
    """The paragraphs, list items and table rows of the Markdown text `md`, each on one line (a README wraps its lines)."""
    out = []
    for para in re.split(r"\n\s*\n", md):
        item = []
        for ln in para.splitlines():
            if item and re.match(r"\s*(- |\| |\d+\. |#|```)", ln):
                out.append(" ".join(item))
                item = []
            item.append(ln.strip())
        if item:
            out.append(" ".join(item))
    return out


def rules(says, body, units=str.splitlines):
    """-> rule(name, *words): one case, "<says>: <name>", that passes when one unit of `body` holds every one of `words`, case
    aside. A unit is a line, or with units=blocks a paragraph, a list item or a table row."""
    found = [u.lower() for u in units(body)]

    def rule(name, *words):
        check(f"{says}: {name}", any(all(w.lower() in u for w in words) for u in found), words)
    return rule


# ------------------------------------------------------------------------------------------------------------- the public repo
# What the public repo must not hold: the ID of a Domino object (24 hex digits, an agent's agt_ ID, a store skill's skl_ ID), a
# Domino host, an App's own URL (apps-internal/<App ID>), or a token (a JWT starts with eyJ).
LEAK = re.compile(r"[0-9a-f]{24}|agt_[0-9a-z]{6,}|skl_[0-9a-z]{6,}|[\w.-]+\.domino\.tech|apps-internal/[0-9a-f]+|eyJ[\w-]{20,}")


def leaks(files):
    """Each match of LEAK in `files` ({path: text}), as "<path>: <match>", sorted."""
    return sorted({f"{rel}: {m.group(0)}" for rel, body in files.items() for m in LEAK.finditer(body)})


# --------------------------------------------------------------------------------------------- the seam part: a local agent service
# The fields of a governance.bundle.stage_changed payload, as the service's audit poller builds it (agent_service/audit_source.py)
PAYLOAD = ("source", "triggeredBy", "occurredAt", "auditTraceId", "bundle.id", "bundle.name", "fromStage", "toStage", "policy.id",
           "policy.name", "project.id", "project.name")
BUNDLE = {"id": "4f2b7c1e-0d3a-4e5f-9a8b-7c6d5e4f3a21", "name": "aml-case-management v7"}   # made up (Domino gives a bundle a UUID)
POLICY = {"id": "pol-app-deployment", "name": "App deployment policy"}


def serve_bundle(bundle, project, policy=POLICY):
    """Make the seam's fake Domino also answer the event bundle's GET (GET /api/governance/v1/bundles/{id}: guardrails.Bundle of the
    service's reference_materials/domino-api-specs/api-governance.swagger.json): `bundle` ({"id", "name"}), in its Validation stage,
    a bundle of `project` ({"id", "name"}). -> a function that puts the fake's own GET back."""
    from agent_service import domino   # the service's module, from AGENT_SERVICE_REPO
    real = domino.get

    def get(path, params=None, cache=True, token=None, credential=None):
        if path == f"/api/governance/v1/bundles/{bundle['id']}":
            return {"id": bundle["id"], "name": bundle["name"], "projectId": project["id"], "projectName": project["name"],
                    "policyId": policy["id"], "policyName": policy["name"], "stage": "Validation", "state": "Active"}
        return real(path, params, cache=cache, token=token, credential=credential)
    domino.get = get
    return lambda: setattr(domino, "get", real)


def stage_move(seam, bundle, to="Validation", project=None, *, by):
    """The payload of one stage move of `bundle`, from Intake to `to`, in `project` ((ID, name); the seam's project by default), by
    the person `by`, as the audit poller publishes it: Domino's audit row (AuditEvent, as the service's tests/check_phase3.py
    audit_event() copies a real stage move), made into the payload by the poller's own audit_source.to_payload."""
    from agent_service import audit_source   # the service's module, from AGENT_SERVICE_REPO
    ent = lambda kind, id_, name_: {"entityType": kind, "id": id_, "name": name_, "tags": []}
    p = project or (seam.PROJECT["id"], seam.PROJECT["name"])
    row = {"timestamp": 1795000000000, "actor": {"id": f"u-{by}", "name": by},
           "action": {"eventName": "Change Governance Bundle Stage", "using": [ent("eventSource", "Web", None)], "traceId": "tr-388"},
           "targets": [{"entity": ent("governanceBundle", bundle["id"], bundle["name"]),
                        "fieldChanges": [{"fieldType": "scalar", "fieldName": "stage", "before": "Intake", "after": to}]}],
           "affecting": [ent("governancePolicy", POLICY["id"], POLICY["name"])], "in": ent("project", *p)}
    return audit_source.to_payload("governance.bundle.stage_changed", row)


def fire(seam, trigger, payload, person):
    """Publish `payload` to the subscription `trigger` (the stored trigger) as `person`, through its test route, which runs the same
    fan-out (service.emit_event) as the audit poller. -> the event's `fired` list (one entry for each agent that it reached), or
    (the HTTP status, the text) when the route refused it."""
    r = seam.api("POST", f"/api/triggers/{trigger.get('id')}/test", person, json={"payload": payload})
    return r.json().get("fired") if r.status_code == 200 else (r.status_code, r.text[:300])


def new_job(seam, before):
    """The one Domino Job that the seam's fake Domino saw start after its first `before` Jobs, or {} for none or more than one. A
    task starts its Job in the background, so it waits up to 10 seconds."""
    for _ in range(100):
        if len(seam.JOBS) > before:
            break
        time.sleep(0.1)
    return seam.JOBS[-1] if len(seam.JOBS) == before + 1 else {}


def spec_of(seam, job):
    """The Job's spec, as its bootstrapper reads it: claim the session with the Job's own credential, then the spec route."""
    import requests   # the service's checks image has it
    tok = requests.post(f"{seam.B}/api/runtime/sessions/{job['sid']}/claim", headers={"authorization": f"Bearer {job['credential'][1]}"},
                        json={"runId": f"localjob{len(seam.JOBS)}"}, timeout=30).json().get("token")
    return requests.get(f"{seam.B}/api/runtime/sessions/{job['sid']}/spec", headers={"x-agent-session-token": tok}, timeout=30).json()
