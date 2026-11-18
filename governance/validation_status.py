"""The scripted check "Validation status" of the App deployment policy (governance/app-deployment-policy.yaml, domino-agent-service
spec #260). An approver clicks Run on the bundle's Validation stage, and Domino runs this file as a Job, as that person:

  governance/validation_status.py <bundle ID> <the agent service App's own URL>

It finds the validators' tasks with the App's task search (GET /api/tasks, q = the bundle ID, event trigger), as the person who
clicked (the Job's token), and prints one block for each validator: the agent, the task, its status, its verdict, its critical vulns,
its doc's location and the task's link. The bundle ID "newest" (the policy's default) shows the newest event task of each validator
in the Job's project instead. Its lines go to stdout (the Job's log) and to validation_status.txt (the check's output, outputTypes
txt). It sends only GET requests to the App: it never starts or changes an agent. It prints no token, and it sends the token only to
an https URL.

A validator is found by its agent's name (VALIDATORS). Its verdict, critical vulns and doc location are lines of its result (the
task's summary): "Verdict: ...", "Critical vulns: ...", "Doc location: ..." (Markdown aside).
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# The validators, in the order of the Validation stage: the evidence item's name, and the agent's name (#267 and #268).
VALIDATORS = (("Validation (agent folder)", "App validator (agent folder)"),
              ("Validation (LangGraph)", "App validator (LangGraph)"))
WIDTH = 16   # the label column: "critical vulns: " is the longest label
OUTPUT = "validation_status.txt"
LINES = []   # every line said, for the output file


def say(line=""):
    LINES.append(line)
    print(line, flush=True)


def field(label, value):
    say(f"  {label + ':':<{WIDTH}}{value}")


def token():
    """The Job's token: the person who clicked Run. Domino's API proxy in the Job gives it (as the trigger test's probe read it)."""
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


def facts(summary):
    """The verdict, critical vulns and doc location lines of a validator's result (its task's summary), Markdown aside."""
    found = {}
    for line in (summary or "").splitlines():
        plain = re.sub(r"[*_`]", "", line).strip().lstrip("-#> ").strip()
        m = re.match(r"(verdict|critical vulns|doc location)\s*:\s*(.+)$", plain, re.I)
        if m and m.group(1).lower() not in found:
            found[m.group(1).lower()] = m.group(2).strip()
    return found


ENDED = {"failed": "the task failed", "cancelled": "the task was cancelled"}


def show(app, title, agent, tasks, where):
    """One validator's block. `tasks` are its tasks, newest first: the newest is the validation; a new stage move starts a new one."""
    say(title)
    field("agent", agent)
    if not tasks:
        field("status", "not started")
        field("note", f"no task of this agent {where} that you may read (only its owner and editors see all its tasks)")
        say()
        return
    t, status = tasks[0], tasks[0].get("status") or "unknown"
    field("task", f"{t.get('key')}  {t.get('title')}")
    field("status", f"{status} ({t['waitingReason']})" if status == "waiting" and t.get("waitingReason") else status)
    got = facts(t.get("summary"))
    if status in ENDED:
        field("result", (t.get("summary") or "").strip().split("\n")[0][:200] or "none")
    for label in ("verdict", "critical vulns", "doc location"):
        if status in ("review", "done"):
            field(label, got.get(label, "not in the task's result"))
        elif status in ENDED:
            field(label, f"none ({ENDED[status]})")
        else:
            field(label, f"not yet (the task is {status})")
    field("task link", f"{app}/#/tasks/{t.get('id')}")
    if len(tasks) > 1:
        field("earlier tasks", ", ".join(f"{e.get('key')} ({e.get('status')})" for e in tasks[1:]))
    say()


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
        say(f"Validation status: no bundle ID given, so the newest validation of each validator in {scope}")
    else:
        query, where = {"q": bundle, "trigger_type": "event"}, "names the bundle"
        say(f"Validation status of bundle {bundle}")
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
    for title, agent in VALIDATORS:
        show(app, title, agent, [t for t in tasks if t.get("agentName") == agent], where)
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
