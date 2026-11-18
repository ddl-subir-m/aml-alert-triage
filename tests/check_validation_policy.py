"""The App deployment policy (governance/app-deployment-policy.yaml) and its scripted check (governance/validation_status.py), for
domino-agent-service spec #260 (ticket #266), seen from outside.

The policy: the YAML parses, and it has the three stages (Intake, Validation, Approval), the two validators' evidence items with their
four fields, and the scripted check, with the placeholders that the live script fills.

The scripted check: it runs as Domino runs it (with python -S, so only the stdlib), against a fake agent service App on 127.0.0.1
(the task search GET /api/tasks, in the shape of app.py's list_tasks answer) and a fake Domino API proxy (the Job's token). From the
fake answer it prints one block for each validator; it reads and never prints the token; it writes its output file; it sends only
GET requests; and it prints each App error with its status.

  python tests/check_validation_policy.py

One line per case, with a non-zero exit code on any failure. The policy part needs PyYAML (`pip install pyyaml`). No Domino host and
no App: the live check is domino-agent-service #270.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

status = validation.get("Validation status") or {}
check("Validation has the evidence item \"Validation status\" (Local.validation-status) for the scripted check",
      status.get("id") == "Local.validation-status", {n: e.get("id") for n, e in validation.items()})
arts = status.get("definition") or []
check("...with one artifact, a scripted check (policyScriptedCheck)",
      len(arts) == 1 and isinstance(arts[0], dict) and arts[0].get("artifactType") == "policyScriptedCheck", arts)
sc = (arts[0].get("details") or {}) if arts and isinstance(arts[0], dict) else {}
check("the scripted check has a name and a label: validation-status, Validation status",
      (sc.get("name"), sc.get("label")) == ("validation-status", "Validation status"), (sc.get("name"), sc.get("label")))
COMMAND = "governance/validation_status.py ${bundle_id} ${service_url}"
check("its command runs governance/validation_status.py with the bundle ID and the agent service App's URL, in that order",
      sc.get("command") == COMMAND, sc.get("command"))
params = [p for p in sc.get("parameters") or [] if isinstance(p, dict)]
placeholders = re.findall(r"\$\{([a-z_]+)\}", sc.get("command") or "")
check("each ${name} in the command is a parameter, and each parameter is in the command (Domino puts its value there)",
      placeholders and sorted(placeholders) == sorted(p.get("name") for p in params), (placeholders, [p.get("name") for p in params]))
check("each parameter is text, with a default (the value that a click runs with, when the person who clicks changes nothing)",
      params and all(p.get("type") == "text" and isinstance(p.get("default"), str) and p["default"] for p in params), params)
default = {p.get("name"): p.get("default") for p in params}
check("bundle_id's default is newest: with no bundle ID typed, the check shows the newest validation of each validator in the project",
      default.get("bundle_id") == "newest", default)
check("service_url's default is the placeholder __AGENT_SERVICE_URL__ (the live script fills it)",
      default.get("service_url") == "__AGENT_SERVICE_URL__", default)
check("it shows a text output file (outputTypes: txt)", sc.get("outputTypes") == ["txt"], sc.get("outputTypes"))
check("its Environment and hardware tier are the placeholders __ENVIRONMENT_ID__ and __HARDWARE_TIER_ID__ (they depend on the deployment)",
      (sc.get("environmentId"), sc.get("hardwareTierId")) == ("__ENVIRONMENT_ID__", "__HARDWARE_TIER_ID__"),
      (sc.get("environmentId"), sc.get("hardwareTierId")))
check("its volume size is a whole number of GiB", isinstance(sc.get("volumeSizeGiB"), int) and sc["volumeSizeGiB"] > 0, sc.get("volumeSizeGiB"))

approval = stage.get("Approval") or {}
approvals = [a for a in approval.get("approvals") or [] if isinstance(a, dict)]
check("Approval has one approval, Deployment sign off, by a person: the placeholder __APPROVER__ (the live script fills it)",
      [(a.get("name"), a.get("approvers")) for a in approvals] == [("Deployment sign off", ["__APPROVER__"])],
      [(a.get("name"), a.get("approvers")) for a in approvals])
check("Approval has no evidence item: the approver reads the Validation stage, then approves or not", not approval.get("evidenceSet"),
      approval.get("evidenceSet"))

PLACEHOLDERS = {"__ENVIRONMENT_ID__", "__HARDWARE_TIER_ID__", "__AGENT_SERVICE_URL__", "__APPROVER__"}
body = "\n".join(ln for ln in raw.splitlines() if not ln.lstrip().startswith("#"))
check("the placeholders are these four, and the file's head names each one", set(re.findall(r"__[A-Z_]+__", body)) == PLACEHOLDERS
      and all(re.search(rf"^#.*{p}", raw, re.M) for p in PLACEHOLDERS), set(re.findall(r"__[A-Z_]+__", body)))
check("the file is for a PUBLIC repo: no host name, no cloud-dogfood, no Domino object ID",
      not re.search(r"https?://|\.domino\.tech|cloud-dogfood|\b[0-9a-f]{24}\b|\b[0-9a-f]{8}-[0-9a-f]{4}-", raw), "a host or an ID")
dashed = [p.name for p in (POLICY, ROOT / "governance" / "validation_status.py", Path(__file__)) if p.is_file() and "\u2014" in p.read_text()]
check("no em dash in the policy, the scripted check or this check", not dashed, dashed)

# ------------------------------------------------------------------------------------------------- the scripted check, on a fake App
SCRIPT = ROOT / "governance" / "validation_status.py"
check("the command's file, governance/validation_status.py, is in the repo", SCRIPT.is_file())
if not SCRIPT.is_file():
    sys.exit(1)

BUNDLE = "0e5e1b7a-0000-4000-8000-000000000266"   # a made-up bundle ID
PROJECT = "aml-validation-demo"                   # the demo project, as the Job's DOMINO_PROJECT_NAME names it
TOKEN = "eyJhbGciOiJub25lIn0.eyJwcmVmZXJyZWRfdXNlcm5hbWUiOiJhbWFyYSJ9.fake-signature-266"   # a fake JWT, for amara (the approver)
FOLDER, LANGGRAPH = "App validator (agent folder)", "App validator (LangGraph)"   # the validators' agent names (#267, #268)
APP = {"tasks": [], "calls": [], "answer": None}
PROXY = {"token": TOKEN, "calls": 0}


def task(key, agent, status, summary=None, *, bundle=BUNDLE, created="2026-11-17T10:00:00Z", trigger="event", project=PROJECT,
         waiting=None):
    """A task as the agent service App's GET /api/tasks answers it: the task row (agent_service/service.py, create_task) plus what
    app.py's _task_out adds (agentName, agentColor, sessionCount, openBlockers, tokens, costUsd, segmentKinds)."""
    n = key.split("-")[1]
    return {
        "id": f"task_{n:0>10}", "key": key, "agentId": "agt_" + ("folder" if agent == FOLDER else "graph" if agent == LANGGRAPH else "other"),
        "title": f"{agent}: validate bundle {bundle}", "instruction": f"Validate the App of bundle {bundle}.", "status": status,
        "waitingReason": waiting,
        "trigger": ({"type": "event", "triggerId": "trg_x", "name": "On Validation", "eventType": "governance.bundle.stage_changed",
                     "publishedBy": "audit-poller"} if trigger == "event" else {"type": trigger, "via": "app", "triggerId": "trg_d", "name": "From the app"}),
        "triggeredBy": {"userName": "olivia"}, "actingAs": {"mode": "service_account", "userName": "validator-sa", "kind": "service_account"},
        "project": {"id": "p1", "name": project}, "resources": [], "inputs": {}, "context": {"bundle": {"id": bundle}},
        "createdAt": created, "updatedAt": created, "completedAt": None, "summary": summary, "sessionIds": ["ses_1"],
        "deliverTo": [], "deliveries": [], "live": None, "intake": None, "accessCaps": None, "resolution": None,
        "agentName": agent, "agentColor": "#543FDE", "sessionCount": 1, "openBlockers": 0, "tokens": 1200, "costUsd": 0.02,
        "segmentKinds": ["job"],
    }


DONE_FOLDER = ("The App is a small MCP server with an open reset route.\n\n**Verdict:** approve after fixes\n**Critical vulns:** yes\n"
               "**Doc location:** agent/AGT-12 at 1a2b3c4, docs/validation/aml-case-management.md\n")
DONE_GRAPH = ("Verdict: approve after fixes\nCritical vulns: yes\n"
              "Doc location: dataset aml-validation-demo, snapshot 3, validation/aml-case-management.md\n")


class Fake(BaseHTTPRequestHandler):
    """The Domino API proxy of a Job (GET /access-token: the Job's token, as plain text) and the agent
    service App's task search (GET /api/tasks): app.py's list_tasks, with its filters (agent_id, status, triggered_by, project,
    trigger_type, q in the title or key, case aside), newest first. Who may read a task is the App's rule (service.can_read_task):
    here the caller may read every task, and a task that the caller may not read is one that the answer doesn't hold."""

    def log_message(self, *a):
        pass

    def answer(self, code, body, ctype="application/json", headers=()):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_any(self):
        url = urllib.parse.urlsplit(self.path)
        if self.server.role == "proxy":
            PROXY["calls"] += 1
            if self.command != "GET" or url.path != "/access-token":
                return self.answer(404, b"", "text/plain")
            return self.answer(200, PROXY["token"].encode(), "text/plain")
        APP["calls"].append({"method": self.command, "path": url.path, "query": urllib.parse.parse_qs(url.query),
                             "auth": self.headers.get("Authorization")})
        if self.command != "GET" or url.path != "/api/tasks":
            return self.answer(405 if self.command != "GET" else 404, {"detail": "Not Found"})
        if APP["answer"]:
            return self.answer(*APP["answer"])
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            return self.answer(401, {"detail": "Domino didn't accept that token."})
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        statuses = set(q["status"].split(",")) if q.get("status") else None

        def pred(t):
            return ((not q.get("agent_id") or t["agentId"] == q["agent_id"]) and (not statuses or t["status"] in statuses)
                    and (not q.get("triggered_by") or t["triggeredBy"]["userName"] == q["triggered_by"])
                    and (not q.get("project") or (t.get("project") or {}).get("name") == q["project"])
                    and (not q.get("trigger_type") or t["trigger"]["type"] == q["trigger_type"])
                    and (not q.get("q") or q["q"].lower() in (t["title"] + " " + t["key"]).lower()))
        rows = [t for t in APP["tasks"] if pred(t)]
        return self.answer(200, sorted(rows, key=lambda t: t["createdAt"], reverse=True))

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_any


def serve(role):
    s = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    s.role = role
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


app_server, proxy_server = serve("app"), serve("proxy")
APP_URL = f"http://127.0.0.1:{app_server.server_port}"
WORK = Path(tempfile.mkdtemp(prefix="check-validation-status-"))
LAST = {}   # the last run's working folder


def run(bundle=BUNDLE, url=None, tasks=(), env=None):
    """Runs the scripted check as Domino runs it ('governance/validation_status.py' '<bundle>' '<url>'), in a fresh working
    folder, with python -S (so a package outside the stdlib fails it). Returns (exit code, stdout + stderr, the output file's text)."""
    APP["tasks"], APP["calls"] = list(tasks), []
    work = LAST["work"] = Path(tempfile.mkdtemp(dir=WORK))
    full = {"PATH": os.environ.get("PATH", ""), "DOMINO_API_PROXY": f"http://127.0.0.1:{proxy_server.server_port}",
            "DOMINO_PROJECT_NAME": PROJECT, "DOMINO_ARTIFACTS_DIR": str(work / "artifacts"), **(env or {})}
    p = subprocess.run([sys.executable, "-S", str(SCRIPT), bundle, APP_URL if url is None else url], cwd=work, env=full,
                       capture_output=True, text=True, timeout=60)
    out = work / "validation_status.txt"
    return p.returncode, p.stdout + p.stderr, out.read_text() if out.is_file() else None


def block(out, title):
    """The lines of one validator's block: from its title line to the next empty line."""
    lines = out.splitlines()
    if title not in lines:
        return []
    i = lines.index(title)
    end = lines.index("", i) if "" in lines[i:] else len(lines)
    return lines[i:end]


code, out, _ = run(tasks=[task("AGT-12", FOLDER, "review", DONE_FOLDER), task("AGT-13", LANGGRAPH, "review", DONE_GRAPH)])
check("two finished validators: exit 0", code == 0, out)
check("the head names the bundle", f"Validation status of bundle {BUNDLE}" in out.splitlines(), out)
check("one block for the agent folder validator: agent, task key, status, verdict, critical vulns, doc location, task link",
      block(out, "Validation (agent folder)") == [
          "Validation (agent folder)",
          f"  agent:          {FOLDER}",
          f"  task:           AGT-12  {FOLDER}: validate bundle {BUNDLE}",
          "  status:         review",
          "  verdict:        approve after fixes",
          "  critical vulns: yes",
          "  doc location:   agent/AGT-12 at 1a2b3c4, docs/validation/aml-case-management.md",
          f"  task link:      {APP_URL}/#/tasks/task_0000000012"], out)
check("one block for the LangGraph validator, after it (the verdict lines without Markdown)",
      block(out, "Validation (LangGraph)") == [
          "Validation (LangGraph)",
          f"  agent:          {LANGGRAPH}",
          f"  task:           AGT-13  {LANGGRAPH}: validate bundle {BUNDLE}",
          "  status:         review",
          "  verdict:        approve after fixes",
          "  critical vulns: yes",
          "  doc location:   dataset aml-validation-demo, snapshot 3, validation/aml-case-management.md",
          f"  task link:      {APP_URL}/#/tasks/task_0000000013"]
      and out.index("Validation (agent folder)") < out.index("Validation (LangGraph)"), out)

MARKED = ("_Verdict_: **do not approve**\n- **Critical vulns:** `no`\n"
          "**Doc location**: `dataset validation_docs, snapshot snap_2, file validation_aml_case__v2.md`\n")
code, out, _ = run(tasks=[task("AGT-17", FOLDER, "done", MARKED)])
check("Markdown only around a value goes: the value itself keeps its _ and * (a doc location with _ prints as the validator wrote it)",
      block(out, "Validation (agent folder)")[4:7] == [
          "  verdict:        do not approve", "  critical vulns: no",
          "  doc location:   dataset validation_docs, snapshot snap_2, file validation_aml_case__v2.md"], out)

code, out, _ = run(tasks=[task("AGT-14", FOLDER, "running")])
check("a validator with no task yet: exit 0 (a result, not an error)", code == 0, out)
check("...its block says not started, and why a task can be missing for this person",
      block(out, "Validation (LangGraph)") == [
          "Validation (LangGraph)",
          f"  agent:          {LANGGRAPH}",
          "  status:         not started",
          "  note:           no task of this agent names the bundle that you may read (only its owner and editors see all its tasks)"],
      out)
check("a task that still runs shows its status, and no verdict yet",
      block(out, "Validation (agent folder)")[3:6] == ["  status:         running", "  verdict:        not yet (the task is running)",
                                                       "  critical vulns: not yet (the task is running)"], out)
code, out, _ = run(tasks=[task("AGT-15", FOLDER, "waiting", waiting="approval"), task("AGT-16", LANGGRAPH, "queued")])
check("a waiting task shows what it waits for; a queued task shows queued",
      "  status:         waiting (approval)" in block(out, "Validation (agent folder)")
      and "  status:         queued" in block(out, "Validation (LangGraph)"), out)
code, out, _ = run(tasks=[task("AGT-17", LANGGRAPH, "failed", "Not run: the Job's Environment is not certified.\nMore lines.")])
check("a failed task shows its status, and the first line of its result",
      block(out, "Validation (LangGraph)")[3:5] == ["  status:         failed",
                                                    "  result:         Not run: the Job's Environment is not certified."], out)
check("...and no verdict", "  verdict:        none (the task failed)" in block(out, "Validation (LangGraph)"), out)
code, out, _ = run(tasks=[task("AGT-20", FOLDER, "review", DONE_FOLDER, created="2026-11-17T12:00:00Z"),
                          task("AGT-18", FOLDER, "review", "Verdict: do not approve", created="2026-11-17T09:00:00Z"),
                          task("AGT-19", FOLDER, "failed", "Not run.", created="2026-11-17T11:00:00Z"),
                          task("AGT-21", "Stage change listener", "review", "Verdict: approve"),
                          task("AGT-22", LANGGRAPH, "review", DONE_GRAPH, trigger="direct")])
b = block(out, "Validation (agent folder)")
check("a new stage move gives a new task: the block shows the newest, and names the earlier ones",
      len(b) > 2 and b[2].startswith("  task:           AGT-20 ") and "  verdict:        approve after fixes" in b
      and "  earlier tasks:  AGT-19 (failed), AGT-18 (review)" in b, b)
check("another agent's task that names the bundle is not a validator's, and a task that a person started is not a validation",
      "AGT-21" not in out and "AGT-22" not in out and "  status:         not started" in block(out, "Validation (LangGraph)"), out)
code, out, _ = run(tasks=[task("AGT-23", FOLDER, "done", "All good, no verdict line.")])
check("a finished task with no verdict line in its result says so",
      "  verdict:        not in the task's result" in block(out, "Validation (agent folder)"), out)

# The token: Domino's API proxy in the Job gives the token of the person who clicked Run.
code, out, text = run(tasks=[task("AGT-12", FOLDER, "review", DONE_FOLDER)])
check("it calls the App with the Job's token, from Domino's API proxy (DOMINO_API_PROXY/access-token)",
      APP["calls"] and all(c["auth"] == "Bearer " + TOKEN for c in APP["calls"]), APP["calls"])
check("the head says whose view it is: the person who clicked Run (the token's user name), not the token",
      "Read as:   amara (the Job's token: the person who clicked Run)" in out.splitlines(), out)
check("it never prints the token: not in the Job's log, not in its output file",
      TOKEN not in out and TOKEN.split(".")[2] not in out and TOKEN not in (text or ""), "the token is in the output")
PROXY["token"] = "Bearer " + TOKEN
code, out, _ = run(tasks=[task("AGT-12", FOLDER, "review", DONE_FOLDER)])
check("a proxy answer of the form \"Bearer <token>\" works the same", code == 0 and APP["calls"] and APP["calls"][0]["auth"] == "Bearer " + TOKEN
      and TOKEN not in out, APP["calls"])
PROXY["token"] = TOKEN
code, out, text = run(env={"DOMINO_API_PROXY": "http://127.0.0.1:9"})
check("no token (no API proxy): it says so, exits 1, and calls no App",
      code == 1 and not APP["calls"] and any(ln.startswith("No token: Domino's API proxy did not give the Job's token")
                                             for ln in out.splitlines()), out)
check("...and its output file says so too", text is not None and "No token: Domino's API proxy" in text, text)


# The output file: Domino shows it to approvers (outputTypes txt).
def copy():
    f = LAST["work"] / "artifacts" / "validation_status.txt"
    return f.read_text() if f.is_file() else None


code, out, text = run(tasks=[task("AGT-12", FOLDER, "review", DONE_FOLDER), task("AGT-16", LANGGRAPH, "running")])
check("it writes validation_status.txt in its working folder, with the lines of the Job's log",
      text is not None and text.splitlines() == out.splitlines() and "Validation (LangGraph)" in text, text)
check("...and a copy in the Job's artifacts folder (DOMINO_ARTIFACTS_DIR: a Git-based project keeps the Job's results there)",
      text is not None and copy() == text, copy())

# Only GET: the check never starts or changes an agent.
seen = []
for tasks in ([], [task("AGT-12", FOLDER, "review", DONE_FOLDER)], [task("AGT-14", FOLDER, "running"), task("AGT-16", LANGGRAPH, "waiting")]):
    run(tasks=tasks)
    seen += APP["calls"]
check("it sends only GET requests to the App, and only to its task search (GET /api/tasks)",
      seen and all(c["method"] == "GET" and c["path"] == "/api/tasks" for c in seen), sorted({(c["method"], c["path"]) for c in seen}))
check("...one request for each click", len(seen) == 3, len(seen))
check("...with q = the bundle ID and the event trigger (trigger_type=event)",
      all(c["query"] == {"q": [BUNDLE], "trigger_type": ["event"]} for c in seen), [c["query"] for c in seen])
src = SCRIPT.read_text()
check("the script has no way to send another method: no POST, PUT, PATCH or DELETE, and no request body",
      not re.search(r"\b(POST|PUT|PATCH|DELETE)\b|method\s*=|data\s*=", src), re.findall(r"\b(POST|PUT|PATCH|DELETE)\b|method\s*=|data\s*=", src))

# An App error: printed with its status (the App's errors are FastAPI's {"detail": ...}).
ERRORS = {401: "Domino didn't accept that token. Send a current JWT or PAT as Authorization: Bearer <token>.",
          403: "You can't read this.", 500: "Internal Server Error",
          503: "Couldn't verify the caller with Domino: timed out"}
for status, detail in ERRORS.items():
    APP["answer"] = (status, {"detail": detail}) if status != 500 else (500, b"Internal Server Error", "text/plain")
    code, out, text = run(tasks=[task("AGT-12", FOLDER, "review", DONE_FOLDER)])
    check(f"an App error {status} is printed with its status and its detail, exit 1, and no validator block",
          code == 1 and f"App error: HTTP {status}: {detail}" in out.splitlines() and "Validation (agent folder)" not in out
          and "Traceback" not in out, out)
    check(f"...and the output file says so too ({status})", text is not None and f"App error: HTTP {status}: {detail}" in text, text)
APP["answer"] = (302, b"", "text/html", [("Location", "https://sign-in.example/login?next=/apps-internal/x")])
code, out, _ = run()
check("a redirect (the Apps proxy's sign-in or consent page) is not followed: printed with its status and where it goes",
      code == 1 and "App error: HTTP 302: a redirect to https://sign-in.example/login?next=/apps-internal/x" in out.splitlines()
      and len(APP["calls"]) == 1, out)
APP["answer"] = (200, b"<html>Sign in</html>", "text/html")
code, out, _ = run()
check("an answer that is not a task list is an error, with its start", code == 1 and
      "App error: HTTP 200, but the answer is not a task list: <html>Sign in</html>" in out.splitlines(), out)
APP["answer"] = None
code, out, _ = run(url="http://127.0.0.1:9")
check("an App that can't be reached: printed, exit 1", code == 1 and any(ln.startswith("App error: no answer from the App (") for ln in out.splitlines())
      and "Traceback" not in out, out)

# bundle_id "newest" (the policy's default): the newest validation of each validator in the Job's project.
OTHER = "0e5e1b7a-0000-4000-8000-000000000999"
newest = [task("AGT-30", FOLDER, "review", DONE_FOLDER, bundle=OTHER, created="2026-11-17T12:00:00Z"),
          task("AGT-31", FOLDER, "review", "Verdict: approve", created="2026-11-17T08:00:00Z"),
          task("AGT-32", LANGGRAPH, "running", bundle=OTHER, created="2026-11-17T12:01:00Z"),
          task("AGT-33", LANGGRAPH, "review", "Verdict: approve", bundle=OTHER, project="another-project", created="2026-11-17T13:00:00Z")]
code, out, _ = run(bundle="newest", tasks=newest)
check("newest: one search for the event tasks of the Job's project (DOMINO_PROJECT_NAME), with no q",
      [c["query"] for c in APP["calls"]] == [{"trigger_type": ["event"], "project": [PROJECT]}], [c["query"] for c in APP["calls"]])
check("...the head says that no bundle ID was given, and which project it read",
      f"Validation status: no bundle ID given, so the newest validation of each validator in project {PROJECT}" in out.splitlines(), out)
check("...each block shows that validator's newest task in the project, whose title names its bundle",
      "  task:           AGT-30  " + f"{FOLDER}: validate bundle {OTHER}" in block(out, "Validation (agent folder)")
      and "  earlier tasks:  AGT-31 (review)" in block(out, "Validation (agent folder)")
      and "  task:           AGT-32  " + f"{LANGGRAPH}: validate bundle {OTHER}" in block(out, "Validation (LangGraph)")
      and "AGT-33" not in out, out)
code, out, _ = run(bundle="", tasks=newest)
check("an empty bundle ID is newest too", code == 0 and [c["query"] for c in APP["calls"]] == [{"trigger_type": ["event"], "project": [PROJECT]}],
      [c["query"] for c in APP["calls"]])

# The App's URL: the token goes only to an https App (or to this machine, for this check).
for url, why in (("__AGENT_SERVICE_URL__", "the policy's placeholder"), ("", "no URL"), ("http://apps.example/apps-internal/x", "plain http")):
    PROXY["calls"] = 0
    code, out, text = run(url=url, tasks=[task("AGT-12", FOLDER, "review", DONE_FOLDER)])
    check(f"an App URL that isn't https ({why}): it says so, exits 1, reads no token and calls nothing",
          code == 1 and not APP["calls"] and PROXY["calls"] == 0 and any(ln.startswith("No App URL: ") for ln in out.splitlines())
          and text is not None, out)

shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if failed else 0)
