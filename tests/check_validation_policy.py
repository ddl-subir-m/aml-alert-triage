"""The App deployment policy (governance/app-deployment-policy.yaml), the one source of its names and labels
(governance/checks.json), and its scripted check (governance/validation_status.py), for domino-agent-service specs #260 and #388
(tickets #266 and #392), seen from outside.

The one source: checks.json has the three checks (their names, evidence items and folders), the four fields' labels, the verdicts
and the severities, as the spec says them.

The policy: the YAML parses, and it has the three stages (Intake, Validation, Approval), the three checks' evidence items with the
four fields of checks.json and their options, and the scripted check, with the placeholders that the live script fills.

The scripted check: it runs as Domino runs it (with python -S, so only the stdlib), against a fake agent service App on 127.0.0.1
(the task search GET /api/tasks, in the shape of app.py's list_tasks answer) and a fake Domino API proxy (the Job's token). From the
fake answer it prints one row for each check and one count line of the verdicts, with no merged verdict; a check with no task says
not started, and a running task shows its status. It reads the checks from the checks.json next to it. It reads and never prints the
token; it writes its output file; it sends only GET requests; and it prints each App error with its status.

  python tests/check_validation_policy.py

One line per case, with a non-zero exit code on any failure. The policy part needs PyYAML (`pip install pyyaml`). No Domino host and
no App: the live check is domino-agent-service #397.
"""
import base64
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


# ------------------------------------------------------------------------------------------ the one source of the names and labels
# The spec's decisions 5 and 7 (domino-agent-service #388): the three checks, their evidence items and folders, the four fields'
# labels, the verdicts and the severities. These literals are the spec's text; checks.json must say the same.
CHECKS_FILE = ROOT / "governance" / "checks.json"
SPEC_CHECKS = [
    {"name": "Purpose and data", "evidenceItem": "Validation: Purpose and data", "folder": "governance/check-purpose-and-data"},
    {"name": "Architecture and access", "evidenceItem": "Validation: Architecture and access",
     "folder": "governance/check-architecture-and-access"},
    {"name": "Vulnerability scan", "evidenceItem": "Validation: Vulnerability scan", "folder": "governance/check-vulnerability-scan"}]
SPEC_FIELDS = {"verdict": "Verdict", "severity": "Highest severity", "summary": "Summary", "doc": "Doc location"}
SPEC_VERDICTS = ["approve", "do not approve", "could not check"]
SPEC_SEVERITIES = ["S0", "S1", "S2", "S3", "none"]
try:
    source = json.loads(CHECKS_FILE.read_text())
except (OSError, ValueError) as e:
    source = e
check("governance/checks.json is in the repo and parses to a JSON object", isinstance(source, dict), source)
source = source if isinstance(source, dict) else {}
check("its keys are checks, fields, verdicts and severities, and only those",
      sorted(source) == ["checks", "fields", "severities", "verdicts"], sorted(source))
check("checks: Purpose and data, Architecture and access, Vulnerability scan, in that order, each with its name, its evidence item "
      "(Validation: <name>) and its folder (governance/check-<name in lower case, with dashes>)",
      source.get("checks") == SPEC_CHECKS, source.get("checks"))
check("fields: the four labels Verdict, Highest severity, Summary, Doc location, by their keys verdict, severity, summary, doc",
      source.get("fields") == SPEC_FIELDS, source.get("fields"))
check("verdicts: approve, do not approve, could not check", source.get("verdicts") == SPEC_VERDICTS, source.get("verdicts"))
check("severities: S0, S1, S2, S3, none", source.get("severities") == SPEC_SEVERITIES, source.get("severities"))


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
CHECKS = [c for c in source.get("checks") or [] if isinstance(c, dict)]
LABEL = source.get("fields") or {}
order = [e.get("name") for e in (stage.get("Validation") or {}).get("evidenceSet") or [] if isinstance(e, dict)]
check("Validation has the evidence items of governance/checks.json, in its order, then Validation status, and no other",
      CHECKS and order == [c.get("evidenceItem") for c in CHECKS] + ["Validation status"], order)
IDS = {"Validation: Purpose and data": "Local.validation-purpose-and-data",
       "Validation: Architecture and access": "Local.validation-architecture-and-access",
       "Validation: Vulnerability scan": "Local.validation-vulnerability-scan"}
FOUR = [(LABEL.get("verdict"), "radio", source.get("verdicts")), (LABEL.get("severity"), "radio", source.get("severities")),
        (LABEL.get("summary"), "textarea", []), (LABEL.get("doc"), "textinput", [])]
for c in CHECKS:
    name = c.get("evidenceItem")
    item = validation.get(name) or {}
    check(f"\"{name}\" has the ID {IDS.get(name)}", item.get("id") == IDS.get(name), {n: e.get("id") for n, e in validation.items()})
    got = fields(item)
    check("...with the four fields of checks.json, in its order: Verdict (its verdicts), Highest severity (its severities), Summary "
          "(textarea), Doc location (textinput), and only those", got == FOUR, got)
    check("...and it has no other artifact (the check fills every one)", len(item.get("definition") or []) == 4, item.get("definition"))
OLD = ("Validation (agent folder)", "Validation (LangGraph)", "Critical vulns", "approve after fixes", "App validator")
check("the policy names none of the #260 validators' evidence items, fields, values or agents", not [o for o in OLD if o in raw],
      [o for o in OLD if o in raw])
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
check("bundle_id's default is newest: with no bundle ID typed, the check shows the newest validation of each check in the project",
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
dashed = [p.name for p in (POLICY, CHECKS_FILE, ROOT / "governance" / "validation_status.py", Path(__file__))
          if p.is_file() and "\u2014" in p.read_text()]
check("no em dash in the policy, checks.json, the scripted check or this check", not dashed, dashed)

# ------------------------------------------------------------------------------------------------- the scripted check, on a fake App
SCRIPT = ROOT / "governance" / "validation_status.py"
check("the command's file, governance/validation_status.py, is in the repo", SCRIPT.is_file())
if not SCRIPT.is_file():
    sys.exit(1)

BUNDLE = "0e5e1b7a-0000-4000-8000-000000000392"   # a made-up bundle ID
PROJECT = "aml-validation-demo"                   # the demo project, as the Job's DOMINO_PROJECT_NAME names it
PD, AA, VS = "Purpose and data", "Architecture and access", "Vulnerability scan"   # the agents' names: the checks' names (decision 5)


def fake_jwt(claims):
    """A fake JWT with no signature (alg none) for these claims. It is made when the check runs, so the repo holds no text in the
    shape of a token (a secret scanner reads one as a real secret)."""
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=").decode()
    return f"{part({'alg': 'none'})}.{part(claims)}.fake-signature"


TOKEN = fake_jwt({"preferred_username": "amara"})   # a fake JWT, for amara (the approver)
APP = {"tasks": [], "calls": [], "answer": None}
PROXY = {"token": TOKEN, "calls": 0}


def task(key, agent, status, summary=None, *, bundle=BUNDLE, created="2026-11-19T10:00:00Z", trigger="event", project=PROJECT,
         waiting=None):
    """A task as the agent service App's GET /api/tasks answers it: the task row (agent_service/service.py, create_task, with the
    event trigger of a fired subscription) plus what app.py's _task_out adds (agentName, agentColor, sessionCount, openBlockers,
    tokens, costUsd, segmentKinds). The title names the bundle, as each check's title template does (decision 13). The IDs are
    made up, in no real ID's shape."""
    n = key.split("-")[1]
    payload = {"source": "domino-audit-trail", "triggeredBy": "olivia", "occurredAt": 0, "auditTraceId": "trace-1",
               "bundle": {"id": bundle, "name": "aml-case-management 1"}, "fromStage": "Intake", "toStage": "Validation",
               "policy": {"id": "policy-1", "name": "App deployment policy"}, "project": {"id": "project-1", "name": project}}
    return {
        "id": f"task_{n:0>10}", "key": key, "agentId": "fake-agent-" + agent.lower().replace(" ", "-"),
        "title": f"{agent}: bundle {bundle}", "instruction": f"Check the App of bundle {bundle}.", "status": status,
        "waitingReason": waiting,
        "trigger": ({"type": "event", "triggerId": "trigger-1", "name": "On Validation", "eventType": "governance.bundle.stage_changed",
                     "publishedBy": "audit-poller"} if trigger == "event"
                    else {"type": trigger, "via": "app", "triggerId": "trigger-2", "name": "From the app", "source": None}),
        "triggeredBy": {"userName": "olivia"}, "actingAs": {"mode": "service_account", "userName": "validator-sa", "kind": "service_account"},
        "project": {"id": "project-1", "name": project}, "resources": [], "inputs": {}, "context": payload,
        "createdAt": created, "updatedAt": created, "completedAt": None, "summary": summary, "sessionIds": ["session-1"],
        "deliverTo": [], "deliveries": [], "live": None, "intake": None, "accessCaps": None, "resolution": None,
        "agentName": agent, "agentColor": "#543FDE", "sessionCount": 1, "openBlockers": 0, "tokens": 1200, "costUsd": 0.02,
        "segmentKinds": ["job"],
    }


def result(verdict, severity, doc, summary="The reason, and the real findings by name and severity."):
    """A check's result (its task's summary): report_result's first lines are the four evidence values (decision 7)."""
    return f"Verdict: {verdict}\nHighest severity: {severity}\nSummary: {summary}\nDoc location: {doc}\n\nMore text of the result.\n"


DOC_PD = f"agent/AGT-12 at 1a2b3c4, docs/validation/purpose-and-data-{BUNDLE}.md"
DOC_AA = f"agent/AGT-13 at 5d6e7f8, docs/validation/architecture-and-access-{BUNDLE}.md"
DOC_VS = f"dataset validation-docs, snapshot 3, vulnerability-scan-{BUNDLE}.md"
DONE_PD = result("do not approve", "S1", DOC_PD)
DONE_AA = ("**Verdict:** do not approve\n- **Highest severity:** `S1`\n**Summary:** [Architecture and access] POST /reset is open.\n"
           f"**Doc location:** `{DOC_AA}`\n")
DONE_VS = result("approve", "none", DOC_VS)


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


def run(bundle=BUNDLE, url=None, tasks=(), env=None, script=SCRIPT):
    """Runs the scripted check as Domino runs it ('governance/validation_status.py' '<bundle>' '<url>'), in a fresh working
    folder, with python -S (so a package outside the stdlib fails it). Returns (exit code, stdout + stderr, the output file's text)."""
    APP["tasks"], APP["calls"] = list(tasks), []
    work = LAST["work"] = Path(tempfile.mkdtemp(dir=WORK))
    full = {"PATH": os.environ.get("PATH", ""), "DOMINO_API_PROXY": f"http://127.0.0.1:{proxy_server.server_port}",
            "DOMINO_PROJECT_NAME": PROJECT, "DOMINO_ARTIFACTS_DIR": str(work / "artifacts"), **(env or {})}
    p = subprocess.run([sys.executable, "-S", str(script), bundle, APP_URL if url is None else url], cwd=work, env=full,
                       capture_output=True, text=True, timeout=60)
    out = work / "validation_status.txt"
    return p.returncode, p.stdout + p.stderr, out.read_text() if out.is_file() else None


def row(out, name):
    """One check's row: its line in the table (the cells between the | marks), then its indented lines below it, as (label, value)."""
    lines = out.splitlines()
    i = next((n for n, ln in enumerate(lines) if ln.startswith(name + " ") and "|" in ln), None)
    if i is None:
        return None, []
    more = []
    for ln in lines[i + 1:]:
        if not ln.startswith("    "):
            break
        label, _, value = ln.strip().partition(":")
        more.append((label, value.strip()))
    return [c.strip() for c in lines[i].split("|")], more


def count_line(out):
    return next((ln for ln in out.splitlines() if re.match(r"\d+ of \d+ ", ln)), None)


ALL = [task("AGT-12", PD, "review", DONE_PD), task("AGT-13", AA, "done", DONE_AA), task("AGT-14", VS, "review", DONE_VS)]
code, out, _ = run(tasks=ALL)
check("three finished checks: exit 0", code == 0, out)
check("the head names the bundle", f"Validation status of bundle {BUNDLE}" in out.splitlines(), out)
lines = out.splitlines()
head = next((n for n, ln in enumerate(lines) if ln.startswith("Check ")), None)
check("a table: the head line Check | Verdict | Highest severity | Task, then one row for each check, in the order of checks.json",
      head is not None and [c.strip() for c in lines[head].split("|")] == ["Check", "Verdict", "Highest severity", "Task"]
      and [ln.split("|")[0].strip() for ln in lines[head + 1:] if "|" in ln] == [PD, AA, VS], out)
check("...its columns line up: each | is at the same place in each line",
      head is not None and len({tuple(m.start() for m in re.finditer(r"\|", ln)) for ln in lines if "|" in ln}) == 1, out)
check("Purpose and data's row: its verdict, its highest severity, its task's key and status",
      row(out, PD)[0] == [PD, "do not approve", "S1", "AGT-12, review"], row(out, PD))
check("...then its task's title, its doc location and its task's link, below it",
      row(out, PD)[1] == [("title", f"{PD}: bundle {BUNDLE}"), ("doc location", DOC_PD),
                          ("task link", f"{APP_URL}/#/tasks/task_0000000012")], row(out, PD))
check("Architecture and access's row: Markdown only around a label or a value goes (a value keeps its _ and *)",
      row(out, AA)[0] == [AA, "do not approve", "S1", "AGT-13, done"] and ("doc location", DOC_AA) in row(out, AA)[1], row(out, AA))
check("Vulnerability scan's row", row(out, VS)[0] == [VS, "approve", "none", "AGT-14, review"]
      and ("doc location", DOC_VS) in row(out, VS)[1], row(out, VS))
check("one count line that counts the verdicts, in the policy's order of verdicts: 1 of 3 says approve, 2 of 3 say do not approve",
      count_line(out) == "1 of 3 says approve, 2 of 3 say do not approve.", count_line(out))
check("...after the table", count_line(out) in lines and head is not None and lines.index(count_line(out)) > head + 3, out)
check("...and then: the checks advise, you decide", "The checks advise. You decide." in lines, out)

code, out, _ = run(tasks=[task("AGT-12", PD, "review", result("could not check", "none", DOC_PD)), task("AGT-14", AA, "running")])
check("a check with no task yet: exit 0 (a result, not an error)", code == 0, out)
check("...its row says not started, with no verdict and no severity",
      row(out, VS)[0] == [VS, "-", "-", "not started"], row(out, VS))
check("...and why a task can be missing for this person",
      row(out, VS)[1] == [("note", "no task of this agent names the bundle that you may read (only its owner and editors see all its tasks)")],
      row(out, VS))
check("a task that still runs shows its status, and no verdict, severity or doc location yet",
      row(out, AA)[0] == [AA, "not yet", "not yet", "AGT-14, running"] and ("doc location", "not yet") in row(out, AA)[1], row(out, AA))
check("the count line counts could not check, a running task and not started apart",
      count_line(out) == "1 of 3 says could not check, 1 of 3 has no verdict yet (running), 1 of 3 is not started.", count_line(out))

code, out, _ = run(tasks=[task("AGT-15", PD, "waiting", waiting="approval"), task("AGT-16", AA, "queued"),
                          task("AGT-17", VS, "failed", "Not run: the Job's Environment is not certified.\nMore lines.")])
check("a waiting task shows what it waits for; a queued task shows queued",
      row(out, PD)[0] == [PD, "not yet", "not yet", "AGT-15, waiting (approval)"] and row(out, AA)[0] == [AA, "not yet", "not yet", "AGT-16, queued"],
      (row(out, PD), row(out, AA)))
check("a failed task shows its status, no verdict, and the first line of its result",
      row(out, VS)[0] == [VS, "-", "-", "AGT-17, failed"] and ("result", "Not run: the Job's Environment is not certified.") in row(out, VS)[1],
      row(out, VS))
check("the count line: 2 of 3 have no verdict yet (waiting, queued), 1 of 3 has no verdict (failed)",
      count_line(out) == "2 of 3 have no verdict yet (waiting, queued), 1 of 3 has no verdict (failed).", count_line(out))

code, out, _ = run(tasks=[task("AGT-20", PD, "review", DONE_PD, created="2026-11-19T12:00:00Z"),
                          task("AGT-18", PD, "review", result("approve", "none", DOC_PD), created="2026-11-19T09:00:00Z"),
                          task("AGT-19", PD, "failed", "Not run.", created="2026-11-19T11:00:00Z"),
                          task("AGT-21", "Stage change listener", "review", "Verdict: approve"),
                          task("AGT-22", AA, "review", DONE_AA, trigger="direct"),
                          task("AGT-23", VS, "done", "All good, no verdict line.")])
check("a new stage move gives a new task: the row shows the newest, and names the earlier ones",
      row(out, PD)[0] == [PD, "do not approve", "S1", "AGT-20, review"] and ("earlier tasks", "AGT-19 (failed), AGT-18 (review)") in row(out, PD)[1],
      row(out, PD))
check("another agent's task that names the bundle is not a check's, and a task that a person started is not a validation",
      "AGT-21" not in out and "AGT-22" not in out and row(out, AA)[0] == [AA, "-", "-", "not started"], out)
check("a finished task with no verdict line in its result says so",
      row(out, VS)[0] == [VS, "not in the result", "not in the result", "AGT-23, done"], row(out, VS))
check("...and the count line counts it as no verdict",
      count_line(out) == "1 of 3 says do not approve, 1 of 3 has no verdict (not in its result), 1 of 3 is not started.", count_line(out))
code, out, _ = run(tasks=[task("AGT-24", PD, "review", "Verdict: Do not approve.\nHighest severity: S1"),
                          task("AGT-25", AA, "review", "Verdict: approve after fixes\nHighest severity: S2"),
                          task("AGT-26", VS, "cancelled")])
check("a verdict is counted with its case and an end dot aside; one that is not the policy's is counted as the check wrote it",
      count_line(out) == "1 of 3 says do not approve, 1 of 3 says approve after fixes, 1 of 3 has no verdict (cancelled)."
      and row(out, PD)[0][1] == "Do not approve.", (count_line(out), row(out, PD)))
code, out, _ = run(tasks=[])
check("no task at all: three rows that say not started, and 3 of 3 are not started",
      [row(out, n)[0] for n in (PD, AA, VS)] == [[n, "-", "-", "not started"] for n in (PD, AA, VS)]
      and count_line(out) == "3 of 3 are not started.", out)

# No merged verdict: the checks advise, and the approver decides.
VERDICT_WORDS = re.compile(r"\b(approve|could not check)\b", re.I)
for tasks, why in ((ALL, "mixed verdicts"), ([task("AGT-30", n, "review", result("approve", "none", "a doc")) for n in (PD, AA, VS)],
                                             "three approve")):
    code, out, _ = run(tasks=tasks)
    named = [ln for ln in out.splitlines() if VERDICT_WORDS.search(ln)]
    rows_ = [ln for ln in named if "|" in ln and ln.split("|")[0].strip() in (PD, AA, VS)]
    parts = count_line(out)[:-1].split(", ") if count_line(out) else []
    check(f"no merged verdict ({why}): a verdict shows only in a check's row and in the count line, whose parts are each "
          "'<n> of 3 say(s) <verdict>'",
          len(rows_) == 3 and set(named) == set(rows_) | {count_line(out)}
          and all(re.fullmatch(r"\d of 3 says? (approve|do not approve|could not check)", p) for p in parts), named)
    check(f"...and no overall result, pass or fail ({why})", not re.search(r"\b(overall|merged|pass(ed)?|fail(ed)?)\b", out, re.I), out)

# The one source: the script reads governance/checks.json from its own folder (Domino runs it from the repo, as its command says).
other = WORK / "other-source"
other.mkdir()
shutil.copy(SCRIPT, other / "validation_status.py")
(other / "checks.json").write_text(json.dumps({**source, "checks": [{"name": "Only check", "evidenceItem": "Validation: Only check",
                                                                     "folder": "governance/check-only"}],
                                               "fields": {**SPEC_FIELDS, "verdict": "Decision"}}))
code, out, _ = run(tasks=[task("AGT-40", "Only check", "review", "Decision: approve\nHighest severity: S3\nDoc location: x.md"),
                          task("AGT-41", PD, "review", DONE_PD)], script=other / "validation_status.py")
check("the checks and the labels come from the checks.json next to the script: another file there gives other rows",
      row(out, "Only check")[0] == ["Only check", "approve", "S3", "AGT-40, review"] and row(out, PD)[0] is None
      and count_line(out) == "1 of 1 says approve.", out)
(other / "checks.json").unlink()
code, out, text = run(tasks=ALL, script=other / "validation_status.py")
check("no checks.json next to the script: it says so, exits 1, calls no App, and still writes its output file",
      code == 1 and not APP["calls"] and any(ln.startswith("No checks: ") for ln in out.splitlines()) and "Traceback" not in out
      and text is not None and "No checks: " in text, out)

# The token: Domino's API proxy in the Job gives the token of the person who clicked Run.
code, out, text = run(tasks=ALL)
check("it calls the App with the Job's token, from Domino's API proxy (DOMINO_API_PROXY/access-token)",
      APP["calls"] and all(c["auth"] == "Bearer " + TOKEN for c in APP["calls"]), APP["calls"])
check("the head says whose view it is: the person who clicked Run (the token's user name), not the token",
      "Read as:   amara (the Job's token: the person who clicked Run)" in out.splitlines(), out)
check("it never prints the token: not in the Job's log, not in its output file",
      TOKEN not in out and TOKEN.split(".")[2] not in out and TOKEN not in (text or ""), "the token is in the output")
PROXY["token"] = "Bearer " + TOKEN
code, out, _ = run(tasks=ALL)
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


code, out, text = run(tasks=[task("AGT-12", PD, "review", DONE_PD), task("AGT-16", VS, "running")])
check("it writes validation_status.txt in its working folder, with the lines of the Job's log",
      text is not None and text.splitlines() == out.splitlines() and count_line(text) is not None, text)
check("...and a copy in the Job's artifacts folder (DOMINO_ARTIFACTS_DIR: a Git-based project keeps the Job's results there)",
      text is not None and copy() == text, copy())

# Only GET: the check never starts or changes an agent.
seen = []
for tasks in ([], ALL, [task("AGT-14", PD, "running"), task("AGT-16", VS, "waiting")]):
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
check("the scripted check names none of the #260 validators' fields, values or agents", not [o for o in OLD if o in src],
      [o for o in OLD if o in src])

# An App error: printed with its status (the App's errors are FastAPI's {"detail": ...}).
ERRORS = {401: "Domino didn't accept that token. Send a current JWT or PAT as Authorization: Bearer <token>.",
          403: "You can't read this.", 500: "Internal Server Error",
          503: "Couldn't verify the caller with Domino: timed out"}
for status, detail in ERRORS.items():
    APP["answer"] = (status, {"detail": detail}) if status != 500 else (500, b"Internal Server Error", "text/plain")
    code, out, text = run(tasks=ALL)
    check(f"an App error {status} is printed with its status and its detail, exit 1, and no row and no count",
          code == 1 and f"App error: HTTP {status}: {detail}" in out.splitlines() and "|" not in out and count_line(out) is None
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

# bundle_id "newest" (the policy's default): the newest validation of each check in the Job's project.
OTHER = "0e5e1b7a-0000-4000-8000-000000000999"
newest = [task("AGT-30", PD, "review", DONE_PD, bundle=OTHER, created="2026-11-19T12:00:00Z"),
          task("AGT-31", PD, "review", result("approve", "none", DOC_PD), created="2026-11-19T08:00:00Z"),
          task("AGT-32", VS, "running", bundle=OTHER, created="2026-11-19T12:01:00Z"),
          task("AGT-33", VS, "review", DONE_VS, bundle=OTHER, project="another-project", created="2026-11-19T13:00:00Z")]
code, out, _ = run(bundle="newest", tasks=newest)
check("newest: one search for the event tasks of the Job's project (DOMINO_PROJECT_NAME), with no q",
      [c["query"] for c in APP["calls"]] == [{"trigger_type": ["event"], "project": [PROJECT]}], [c["query"] for c in APP["calls"]])
check("...the head says that no bundle ID was given, and which project it read",
      f"Validation status: no bundle ID given, so the newest validation of each check in project {PROJECT}" in out.splitlines(), out)
check("...each row shows that check's newest task in the project, whose title names its bundle",
      row(out, PD)[0][3] == "AGT-30, review" and ("title", f"{PD}: bundle {OTHER}") in row(out, PD)[1]
      and ("earlier tasks", "AGT-31 (review)") in row(out, PD)[1]
      and row(out, VS)[0][3] == "AGT-32, running" and "AGT-33" not in out
      and ("note", "no task of this agent in project aml-validation-demo that you may read (only its owner and editors see all its tasks)")
      in row(out, AA)[1], out)
code, out, _ = run(bundle="", tasks=newest)
check("an empty bundle ID is newest too", code == 0 and [c["query"] for c in APP["calls"]] == [{"trigger_type": ["event"], "project": [PROJECT]}],
      [c["query"] for c in APP["calls"]])

# The App's URL: the token goes only to an https App (or to this machine, for this check).
for url, why in (("__AGENT_SERVICE_URL__", "the policy's placeholder"), ("", "no URL"), ("http://apps.example/apps-internal/x", "plain http")):
    PROXY["calls"] = 0
    code, out, text = run(url=url, tasks=ALL)
    check(f"an App URL that isn't https ({why}): it says so, exits 1, reads no token and calls nothing",
          code == 1 and not APP["calls"] and PROXY["calls"] == 0 and any(ln.startswith("No App URL: ") for ln in out.splitlines())
          and text is not None, out)

shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if failed else 0)
