"""The scripted check "Validation status" of the App deployment policy (governance/app-deployment-policy.yaml, domino-agent-service
specs #260 and #388). An approver clicks Run on the bundle's Validation stage, and Domino runs this file as a Job, as that person:

  governance/validation_status.py <bundle ID> <the agent service App's own URL>

It finds the checks' tasks with the App's task search (GET /api/tasks, q = the bundle ID, event trigger), as the person who clicked
(the Job's token). It prints a table with one row for each check: its verdict, its highest severity, and its task's key and status.
Below each row are the task's title, the doc location and the task's link. Then one count line counts the verdicts, for example
"2 of 3 say do not approve". There is no merged verdict: the checks advise, and the approver decides.

The bundle ID "newest" (the policy's default) shows the newest event task of each check in the Job's project instead. Its lines go
to stdout (the Job's log) and to validation_status.txt (the check's output, outputTypes txt). It sends only GET requests to the App:
it never starts or changes an agent. It prints no token, and it sends the token only to an https URL.

The checks and the labels come from checks.json, next to this file: the one source of the names and labels. A check is found by its
agent's name, which is the check's name. Its verdict, highest severity and doc location are lines of its result (the task's
summary): "Verdict: ...", "Highest severity: ...", "Doc location: ..." (Markdown aside).
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple

CHECKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checks.json")
WIDTH = 15   # the label column of the lines below a row: "earlier tasks: " is the longest label
OUTPUT = "validation_status.txt"
LINES = []   # every line said, for the output file
FINISHED = ("review", "done")     # the task ended with its result
ENDED = ("failed", "cancelled")   # the task ended with no result
# One check's row. cells: [check, verdict, highest severity, task]. below: the lines below it, as (label, value). counted: what the count
# line counts for it, as (kind, value): ("verdict", <the verdict>), ("no verdict yet", <status>), ("no verdict", <why>) or
# ("not started", None).
Row = namedtuple("Row", "cells below counted")


def say(line=""):
    LINES.append(line)
    print(line, flush=True)


def load_checks():
    """checks.json: the checks' names (in the policy's order), the four fields' labels, and the policy's verdicts."""
    with open(CHECKS) as f:
        source = json.load(f)
    names = [c["name"] for c in source["checks"]]
    fields, verdicts = source["fields"], source["verdicts"]
    if not names or not all(isinstance(x, str) and x for x in names + [fields["verdict"], fields["severity"], fields["doc"]]):
        raise ValueError("a check's name or a field's label is missing")
    return names, fields, verdicts


def token():
    """The Job's token: the person who clicked Run. Domino's API proxy in the Job gives it: GET /access-token on DOMINO_API_PROXY
    (else localhost:8899), in a scripted check's Job too."""
    url = os.environ.get("DOMINO_API_PROXY", "http://localhost:8899").rstrip("/") + "/access-token"
    t = urllib.request.urlopen(url, timeout=10).read().decode().strip()
    return t[len("Bearer "):] if t.startswith("Bearer ") else t


def who(tok):
    """The token's user name (its preferred_username claim), to say whose view this is. Not a check: the App checks the token."""
    try:
        part = tok.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("preferred_username") or "unknown"
    except Exception:
        return "unknown (the token is not a JWT)"


class AppError(Exception):
    """The App's answer was not a task list. The text says why, with the HTTP status when there was one."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # a redirect is the Apps proxy's sign-in or consent page, never the App's answer
        return None


def get_tasks(app, query, tok):
    """GET <app>/api/tasks?<query> with the Job's token: the App's task search (app.py, list_tasks). Returns its list of tasks."""
    req = urllib.request.Request(f"{app}/api/tasks?{urllib.parse.urlencode(query)}",
                                 headers={"Authorization": "Bearer " + tok, "Accept": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            raise AppError(f"HTTP {e.code}: a redirect to {e.headers.get('Location', '')[:200]}")
        body = e.read()
        try:
            detail = json.loads(body).get("detail")
        except Exception:
            detail = None
        raise AppError(f"HTTP {e.code}: {detail or body[:200].decode('utf-8', 'replace').strip() or e.reason}")
    except (urllib.error.URLError, OSError) as e:
        raise AppError(f"no answer from the App ({getattr(e, 'reason', e)})")
    try:
        tasks = json.loads(body)
    except ValueError:
        tasks = None
    if not isinstance(tasks, list):
        raise AppError(f"HTTP {status}, but the answer is not a task list: {body[:120].decode('utf-8', 'replace').strip()}")
    return tasks


def result_lines(summary, labels):
    """The lines of a check's result (its task's summary) with these labels, Markdown aside: {label in lower case: value}."""
    found = {}
    for line in (summary or "").splitlines():   # "- **Verdict:** approve", "_Doc location_: `a_b`": marks around, never inside
        m = re.match(rf"[\s>#*_`-]*({'|'.join(map(re.escape, labels))})[*_`]*\s*:(.+)$", line, re.I)
        value = m.group(2).strip(" \t*_`") if m else ""
        if value and m.group(1).lower() not in found:
            found[m.group(1).lower()] = value
    return found


def row(app, name, tasks, fields, where):
    """One check's Row: its cells, the lines below it, and what the count line counts for it. `tasks` are its tasks, newest first:
    the newest is the validation; a new stage move starts a new one."""
    if not tasks:
        note = f"no task of this agent {where} that you may read (only its owner and editors see all its tasks)"
        return Row([name, "-", "-", "not started"], [("note", note)], ("not started", None))
    t, status = tasks[0], tasks[0].get("status") or "unknown"
    shown = f"{status} ({t['waitingReason']})" if status == "waiting" and t.get("waitingReason") else status
    labels = [fields["verdict"], fields["severity"], fields["doc"]]
    got = result_lines(t.get("summary"), labels)
    if status in FINISHED:
        verdict, severity, doc = (got.get(x.lower(), "not in the result") for x in labels)
        kind = ("verdict", verdict) if fields["verdict"].lower() in got else ("no verdict", "not in its result")
    elif status in ENDED:
        verdict, severity, doc = "-", "-", "-"
        kind = ("no verdict", status)
    else:
        verdict, severity, doc = "not yet", "not yet", "not yet"
        kind = ("no verdict yet", status)
    below = [("title", t.get("title") or "")]
    if status in ENDED:
        below.append(("result", (t.get("summary") or "").strip().split("\n")[0][:200] or "none"))
    below += [("doc location", doc), ("task link", f"{app}/#/tasks/{t.get('id')}")]
    if len(tasks) > 1:
        below.append(("earlier tasks", ", ".join(f"{e.get('key')} ({e.get('status')})" for e in tasks[1:])))
    return Row([name, verdict, severity, f"{t.get('key')}, {shown}"], below, kind)


def count(kinds, verdicts):
    """The count line: how many checks say each verdict (the policy's verdicts in its order, then any other as the check wrote it),
    how many have no verdict yet (their tasks still run), how many have none (their tasks ended without one), and how many are not
    started. It merges nothing: each check is counted once, as it is."""
    n, said, policy = len(kinds), {}, {v.lower(): v for v in verdicts}
    for kind, value in kinds:
        if kind == "verdict":
            key = value.strip().rstrip(".").strip().lower()
            said.setdefault(key, [policy.get(key, value), 0])[1] += 1
    order = [v for v in policy if v in said] + [k for k in said if k not in policy]
    parts = [f"{said[k][1]} of {n} {'says' if said[k][1] == 1 else 'say'} {said[k][0]}" for k in order]
    for kind, verb, text in (("no verdict yet", ("has", "have"), "no verdict yet"), ("no verdict", ("has", "have"), "no verdict"),
                             ("not started", ("is", "are"), "not started")):
        values = [value for k, value in kinds if k == kind]
        if values:
            why = f" ({', '.join(dict.fromkeys(values))})" if kind != "not started" else ""
            parts.append(f"{len(values)} of {n} {verb[len(values) != 1]} {text}{why}")
    return ", ".join(parts) + "."


def table(rows, fields):
    """The rows (each a Row) as a table: the cells between | marks, each column as wide as its widest cell, then each row's lines below
    it."""
    head = ["Check", fields["verdict"], fields["severity"], "Task"]
    widths = [max(len(cells[i]) for cells in [head] + [r.cells for r in rows]) for i in range(3)]
    for cells, below in [(head, [])] + [(r.cells, r.below) for r in rows]:
        say(" | ".join([f"{c:<{w}}" for c, w in zip(cells, widths)] + [cells[3]]))
        for label, value in below:
            say(f"    {label + ':':<{WIDTH}}{value}")


def safe_url(app):
    """The token goes only to an https App, or to this machine (the repo's check runs a fake App on 127.0.0.1)."""
    u = urllib.parse.urlsplit(app)
    return bool(u.hostname) and (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")))


def main(argv):
    bundle = (argv[1] if len(argv) > 1 else "").strip()
    app = (argv[2] if len(argv) > 2 else "").strip().rstrip("/")
    project = os.environ.get("DOMINO_PROJECT_NAME", "").strip()
    if bundle in ("", "newest"):   # the policy's default: no bundle ID typed
        scope = f"project {project}" if project else "any project"
        query, where = {"trigger_type": "event", **({"project": project} if project else {})}, f"in {scope}"
        say(f"Validation status: no bundle ID given, so the newest validation of each check in {scope}")
    else:
        query, where = {"q": bundle, "trigger_type": "event"}, "names the bundle"
        say(f"Validation status of bundle {bundle}")
    try:
        names, fields, verdicts = load_checks()
    except (OSError, ValueError, KeyError, TypeError) as e:
        say(f"No checks: {CHECKS} did not give the checks and their labels ({e.__class__.__name__}: {e}). It is in the repo, next "
            "to this script: ask your governance admin.")
        return 1
    if not safe_url(app):
        say(f"No App URL: {app!r} is not the agent service App's https URL. The policy's service_url must be the App's own URL "
            "(it ends in /apps-internal/<App ID>): ask your governance admin.")
        return 1
    try:
        tok = token()
    except Exception as e:
        say(f"No token: Domino's API proxy did not give the Job's token ({e.__class__.__name__}). Run this check from the bundle's "
            "Validation stage in Domino.")
        return 1
    say(f"Read as:   {who(tok)} (the Job's token: the person who clicked Run)")
    say()
    try:
        tasks = get_tasks(app, query, tok)
    except AppError as e:
        say(f"App error: {e}")
        return 1
    tasks = sorted(tasks, key=lambda t: t.get("createdAt") or "", reverse=True)   # newest first, as the route sorts them
    rows = [row(app, name, [t for t in tasks if t.get("agentName") == name], fields, where) for name in names]
    table(rows, fields)
    say()
    say(count([r.counted for r in rows], verdicts))
    say("The checks advise. You decide.")
    return 0


def write_output():
    """validation_status.txt, the check's output (outputTypes txt): in the working folder, and in the Job's artifacts folder, where
    a Git-based project keeps a Job's results (DOMINO_ARTIFACTS_DIR, else /mnt/artifacts, as the service's tests/certify does)."""
    artifacts = os.environ.get("DOMINO_ARTIFACTS_DIR") or ("/mnt/artifacts" if os.access("/mnt/artifacts", os.W_OK) else "")
    folders = [os.getcwd()] + ([artifacts] if artifacts and os.path.abspath(artifacts) != os.getcwd() else [])
    for folder in folders:
        try:
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, OUTPUT), "w") as f:
                f.write("\n".join(LINES) + "\n")
        except OSError as e:
            print(f"Could not write {OUTPUT} in {folder}: {e}", flush=True)


if __name__ == "__main__":
    try:
        code = main(sys.argv)
    finally:
        write_output()
    sys.exit(code)
