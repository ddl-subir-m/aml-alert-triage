"""The scripted check "Validation status" of the App deployment policy (governance/app-deployment-policy.yaml, domino-agent-service
spec #260). An approver clicks Run on the bundle's Validation stage, and Domino runs this file as a Job, as that person:

  governance/validation_status.py <bundle ID> <the agent service App's own URL>

It finds the validators' tasks with the App's task search (GET /api/tasks, q = the bundle ID, event trigger), as the person who
clicked (the Job's token), and prints one block for each validator: the agent, the task, its status, its verdict, its doc's location
and the task's link. Its lines go to stdout (the Job's log) and to validation_status.txt (the check's output, outputTypes txt). It
sends only GET requests to the App: it never starts or changes an agent. It prints no token.
"""
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
LINES = []


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


def get(app, path, query):
    """GET <app><path>?<query> with the Job's token. Returns the JSON answer."""
    req = urllib.request.Request(f"{app}{path}?{urllib.parse.urlencode(query)}",
                                 headers={"Authorization": "Bearer " + token(), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


def facts(summary):
    """The verdict, critical vulns and doc location lines of a validator's result (its task's summary), Markdown aside."""
    found = {}
    for line in (summary or "").splitlines():
        plain = re.sub(r"[*_`]", "", line).strip().lstrip("-#> ").strip()
        m = re.match(r"(verdict|critical vulns|doc location)\s*:\s*(.+)$", plain, re.I)
        if m and m.group(1).lower() not in found:
            found[m.group(1).lower()] = m.group(2).strip()
    return found


def show(app, title, agent, tasks):
    say(title)
    field("agent", agent)
    t = tasks[0]
    field("task", f"{t.get('key')}  {t.get('title')}")
    field("status", t.get("status"))
    got = facts(t.get("summary"))
    for label in ("verdict", "critical vulns", "doc location"):
        field(label, got.get(label, "not in the task's result"))
    field("task link", f"{app}/#/tasks/{t.get('id')}")
    say()


def main(argv):
    bundle = (argv[1] if len(argv) > 1 else "").strip()
    app = (argv[2] if len(argv) > 2 else "").strip().rstrip("/")
    say(f"Validation status of bundle {bundle}")
    say()
    tasks = get(app, "/api/tasks", {"q": bundle, "trigger_type": "event"})
    for title, agent in VALIDATORS:
        show(app, title, agent, [t for t in tasks if t.get("agentName") == agent])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
