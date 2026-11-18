"""The LangGraph validator (governance/validator-langgraph/, domino-agent-service spec #260, Implementation Decision 9), seen from
outside: its definition as the wizard makes it, its event subscription's templates, and its graph as a framework-lane Job runs it.

With no service, it checks the two files. With the service (AGENT_SERVICE_REPO, the path of a domino-agent-service checkout), and a
Python that has the agent-langgraph Environment's packages (langgraph, ag-ui-langgraph, langchain-anthropic, uvicorn), it runs the
graph as the framework lane runs it, with the platform's own parts and no Domino host:
  - the platform's serve module (agent_runtime/lanes/framework/serve.py) loads the entry point from this repo and serves it with the
    LangGraph adapter, on a Unix socket, with domino-agui (tests/fetch_domino_agui.py gives the pinned version);
  - the platform's AG-UI client, thread and stream rules play the driver, and its translator gives the task's result;
  - the relay is the Job's own (agent_runtime/proxies.py relay, agent_runtime/run.py Gateway: each call decided by gateway.decide() on
    the task's policy and made by gateway.execute()), with a fake Domino that answers in Domino's API shape;
  - the model is the certification seam's fake LLM Gateway (tests/certify/fake_model.py), in the Anthropic Messages format.
The task is the one the event subscription makes: the instruction is the subscription's template, filled from a stage-change event.
Without the service or the packages, that part prints a SKIP line.

  python tests/check_validator_langgraph.py
  AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_validator_langgraph.py   # the AML venv: README, the check
"""
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "governance" / "validator-langgraph"
NAME = "App validator (LangGraph)"   # exact: the scripted check finds the validator's tasks by this agent name
EVIDENCE = "Validation (LangGraph)"   # the evidence item it fills, in the policy's Validation stage
ENTRYPOINT = "governance/validator-langgraph/graph.py:build_graph"
failed = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{str(detail)[:600]}]" if detail and not ok else ""), flush=True)
    if not ok:
        failed.append(name)


def done(skip=None):
    if skip:
        print(f"SKIP: {skip}", flush=True)
    sys.exit(1 if failed else 0)


def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        check(f"{path.relative_to(ROOT)} is a JSON file", False, e)
        return {}


# ------------------------------------------------------------------------------------------------------------- the definition
d = load(FOLDER / "agent.json")
VALIDATORS = runpy.run_path(str(ROOT / "governance" / "validation_status.py")).get("VALIDATORS") or ()
check("its name is the one the scripted check looks for, with its evidence item",
      d.get("name") == NAME and (EVIDENCE, NAME) in VALIDATORS, (d.get("name"), VALIDATORS))
check("the lane is framework: a LangGraph graph at governance/validator-langgraph/graph.py:build_graph, with no client-side tool",
      d.get("lane") == "framework" and d.get("framework") == {"name": "langgraph", "entrypoint": ENTRYPOINT, "clientTools": []},
      (d.get("lane"), d.get("framework")))
check("the entry point's file is in the repo", (ROOT / ENTRYPOINT.split(":")[0]).is_file())
ex = d.get("execution") or {}
check("it runs as a Domino Job, and the file names no Environment (the wizard picks the certified one)",
      ex.get("runtime") == "job" and "environment" not in ex, ex)
g = d.get("guardrails") or {}
check("Run a Job is on and Git push is off (the framework lane has no push)",
      (g.get("tools") or {}).get("jobs") is True and (g.get("tools") or {}).get("push") is False, g.get("tools"))
check("Project files and Project datasets are Read & write, the event's bundle (an attached resource) too, and nothing else",
      g.get("access") == {"project": "write", "data": "write", "named": "write", "other": "none"}, g.get("access"))
check("it acts as a service account, and the file names none (the owner picks it in the wizard)",
      d.get("identity") == {"mode": "service_account"}, d.get("identity"))
check("its access is restricted, and the file names no person", d.get("access") == {"mode": "restricted", "users": [], "editors": []},
      d.get("access"))
check("a failed run fails the task (nobody answers an event task)", d.get("onError") == "fail", d.get("onError"))
check("the model is sonnet from the LLM Gateway, with the acting identity's grants",
      d.get("model") == {"source": "gateway", "models": ["sonnet"], "access": "acting"}, d.get("model"))
check("it has one input, a required project, and no tool server",
      d.get("inputs") == [{"name": "project", "type": "project", "required": True}] and d.get("toolServers") == [],
      (d.get("inputs"), d.get("toolServers")))
check("no key is one the App drops (it keeps only its agent fields)", not set(d) - {
    "name", "description", "tags", "color", "scope", "model", "systemPrompt", "guardrails", "completion", "identity", "access",
    "onError", "execution", "enabled", "inputs", "lane", "framework", "toolServers"}, sorted(d))

# ------------------------------------------------------------------------------------------------------- the event subscription
s = load(FOLDER / "subscription.json")
ev = s.get("event") or {}
check("the subscription is an event trigger on governance.bundle.stage_changed",
      s.get("type") == "event" and ev.get("eventType") == "governance.bundle.stage_changed" and s.get("enabled") is True, s)
check("its filter: the bundle moved to Validation, in the demo project (a placeholder: the live script fills it)",
      ev.get("filter") == [{"field": "toStage", "op": "equals", "value": "Validation"},
                           {"field": "project.id", "op": "equals", "value": "__DEMO_PROJECT_ID__"}], ev.get("filter"))
title, instruction = s.get("titleTemplate") or "", s.get("instructionTemplate") or ""
check("the title template names the agent and the bundle ID (the scripted check searches the title for the bundle ID)",
      title.startswith(NAME) and "{{bundle.id}}" in title, title)
lines = instruction.splitlines()
check("the instruction template names the bundle ID on its own line", "Bundle ID: {{bundle.id}}" in lines, lines)
check("the instruction template names the evidence item that the validator fills", f"Evidence item: {EVIDENCE}" in lines, lines)
check("the instruction template names the doc's dataset and where it is mounted (placeholders: the live script fills them)",
      "Doc dataset ID: __DOC_DATASET_ID__" in lines and "Doc dataset path: __DOC_DATASET_PATH__" in lines, lines)
placeholders = set(re.findall(r"__[A-Z_]+__", json.dumps(s)))
check("the subscription's placeholders are the three that the live script fills",
      placeholders == {"__DEMO_PROJECT_ID__", "__DOC_DATASET_ID__", "__DOC_DATASET_PATH__"}, placeholders)
check("it names no Domino resource: no 24-hex ID and no host", not re.search(r"\b[0-9a-f]{24}\b|https?://|\.domino\.", json.dumps(s)),
      json.dumps(s)[:300])
check("it has no default resource and no write-back", s.get("defaultResources") == [] and s.get("writeBack") == [], s)

# --------------------------------------------------------------------------------------------- the graph, as the framework lane runs it
service = os.environ.get("AGENT_SERVICE_REPO", "").strip()
if not service:
    done("AGENT_SERVICE_REPO is not set, so the graph wasn't run. Set it to a domino-agent-service checkout (README, \"The LangGraph "
         "validator\")")
service = Path(service).expanduser().resolve()
SERVE = service / "agent_runtime" / "lanes" / "framework" / "serve.py"
if not SERVE.is_file() or not (service / "tests" / "certify" / "fake_model.py").is_file():
    check(f"AGENT_SERVICE_REPO ({service}) is a domino-agent-service checkout with the framework lane", False)
    done()
try:
    import ag_ui_langgraph  # noqa: F401  (the agent-langgraph Environment's packages: the serve module's adapter needs them)
    import langchain_anthropic  # noqa: F401
    import langgraph.checkpoint.sqlite.aio  # noqa: F401
    import uvicorn  # noqa: F401
    import yaml
except ImportError as e:
    done(f"this Python has no {e.name}: run the check with a Python that has the agent-langgraph Environment's packages (the AML venv, "
         "README, \"The LangGraph validator\")")
sys.path[:0] = [str(service / "tests" / "certify"), str(service), str(service / "tests")]   # certify/ first: its fake_model.py
if not sys.platform.startswith("linux"):   # agent_runtime/sandbox.py calls Linux's prctl when it is imported. The relay and the gateway
    # never call it (it sandboxes the harness), so on another OS an empty module stands in for it. On Linux the real one loads.
    sys.modules["agent_runtime.sandbox"] = types.ModuleType("agent_runtime.sandbox")
import fake_model  # noqa: E402  (the certification seam's fake LLM Gateway, from AGENT_SERVICE_REPO)
import fetch_domino_agui  # noqa: E402
from agent_runtime import gateway, proxies, run as runtime  # noqa: E402
from agent_runtime.lanes.framework import client, events, stream, thread  # noqa: E402

gateway.LANE = "framework"   # as the framework lane's driver sets it: a denial names no harness tool
gateway.WAIT_S, gateway.WAIT_EVERY = 0.3, 0.1   # wait_job waits up to 45 s for each call: here a fraction of a second
AGUI = fetch_domino_agui.for_check()   # the folder with domino_agui/ in it: the pinned version from PyPI (cached)

PROJECT = {"id": "p-demo", "name": "aml-app-validation", "gitBased": True}   # the demo project: Git-based, as spec #260 decision 5
BUNDLE = {"id": "0b1c2d3e-4f50-4617-8293-a4b5c6d7e8f9", "name": "aml-case-management v3"}   # Domino gives a bundle a UUID
DATASET = {"id": "ds-validation-docs", "name": "validation-docs"}
RELAY_TOKEN = "relay-token-268"


def render(template, payload):
    """{{dotted.path}} -> its value in the event's payload; a path that isn't there stays as it is (agent_service/service.py
    render_template, which the service part compares with)."""
    def one(m):
        v = payload
        for k in m.group(1).split("."):
            v = v.get(k) if isinstance(v, dict) else None
        return str(v) if v is not None else m.group(0)
    return re.sub(r"{{\s*([\w.]+)\s*}}", one, template)


def stage_change(bundle_name):
    """The payload of governance.bundle.stage_changed as the audit poller builds it (agent_service/audit_source.py to_payload)."""
    return {"source": "domino-audit-trail", "triggeredBy": "analyst", "occurredAt": 1763380000000, "auditTraceId": "trace-268",
            "bundle": {"id": BUNDLE["id"], "name": bundle_name}, "fromStage": "Intake", "toStage": "Validation",
            "policy": {"id": "pol-app", "name": "App deployment policy"}, "project": {"id": PROJECT["id"], "name": PROJECT["name"]}}


def instruction_for(bundle_name, dataset_path):
    """The task's instruction: the subscription's template, filled from the event, with the live script's placeholders replaced."""
    filled = render(s.get("instructionTemplate") or "", stage_change(bundle_name))
    return filled.replace("__DOC_DATASET_ID__", DATASET["id"]).replace("__DOC_DATASET_PATH__", str(dataset_path))


def gateway_policy(task_key):
    """The task's gateway policy, as harness.gateway_policy() builds it for this agent and an event task: the event names the bundle
    and the project, so both are task resources (service.resources_from_context), the bundle with the row "Other resources attached
    to the task" and the project with Project files (service.assign_access). The service part compares it with the real one."""
    a = {**g["access"], "inputs": {}}
    return {"project": dict(PROJECT), "taskKey": task_key, "access": a,
            "resources": [{"type": "project", "id": PROJECT["id"], "name": PROJECT["name"], "access": a["project"], "input": None},
                          {"type": "bundle", "id": BUNDLE["id"], "name": BUNDLE["name"], "access": a["named"], "input": None}],
            "tools": {"jobs": True, "push": False, "files": False}, "branchPushed": False, "planLock": False}


# ------------------------------------------------------------------------------------------------- the fake Domino, in Domino's shape
POLICY_YAML = yaml.safe_load((ROOT / "governance" / "app-deployment-policy.yaml").read_text())


def published_policy():
    """GET /api/governance/v1/policies/{id}: a guardrails.Policy (api-governance.swagger.json), as Domino makes it from the AML policy
    file: each evidence item and each artifact gets its own UUID, and an item's externalId is its YAML id after "Local."."""
    stages = []
    for st in POLICY_YAML["stages"]:
        items = [{"id": str(uuid.uuid4()), "name": e["name"], "description": e.get("description"), "externalId": e["id"].split(".", 1)[-1],
                  "policyId": "pol-app", "policyVersionId": "pv-1", "visible": True,
                  "artifacts": [{"id": str(uuid.uuid4()), "artifactType": a["artifactType"], "details": a["details"],
                                 "policyEntityId": f"pe-{n}", "visible": True} for n, a in enumerate(e.get("definition") or [])]}
                 for e in st.get("evidenceSet") or []]
        stages.append({"id": str(uuid.uuid4()), "name": st["name"], "policyVersionId": "pv-1", "evidenceSet": items,
                       "approvals": st.get("approvals") or []})
    return {"id": "pol-app", "name": "App deployment policy", "status": "Published", "description": "", "archived": False,
            "createdAt": "2026-11-17T09:00:00Z", "createdBy": {"id": "u-gov", "userName": "gov_admin"}, "stages": stages,
            "gates": [], "taxonomyTags": [], "taxonomyProperties": []}


def scan_module():
    """governance/scan.py as a module: its summary lines come from its own code. Each tool's version is the tested one (its --version
    would run the tool, which this Python may not have)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("governance_scan", ROOT / "governance" / "scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.version = {"pip_audit": "2.10.1", "bandit": "1.9.4"}.get
    return mod


SCAN = scan_module()
SCANNED = "4c9e1f0a7b3d2e6f8a1b0c9d8e7f6a5b4c3d2e1f"   # the commit that the scan Job read


def scan_log(fixture="clean", fail=None):
    """The stdout of the scan Job, as governance/scan.py prints it in a Domino Job, with the fixtures' pip-audit and bandit answers
    (tests/fixtures/scan/): its progress lines, its summary between the two markers, and the lines Domino adds after the command.
    `fail`: the tool that could not run (scan.py then exits 1, and Domino's Job fails)."""
    out = "/mnt/artifacts/governance-scan"
    folder = ROOT / "tests" / "fixtures" / "scan" / fixture
    audit = (None, "could not run (exit 1): ERROR: No matching distribution found") if fail == "pip-audit" else \
        (json.loads((folder / "pip-audit.json").read_text()), "")
    bandit = (json.loads((folder / "bandit.json").read_text()), "")
    result = f"result: {fail} could not run (its messages: {fail}.log)" if fail else "result: both tools ran"
    return "\n".join([f"scan: pip-audit and bandit on case_server (governance/scan.py), output in {out}",
                      "scan: running pip-audit on case_server/requirements.txt", "scan: running bandit on case_server",
                      SCAN.START, f"commit: {SCANNED}", *SCAN.pip_audit_lines(*audit), *SCAN.bandit_lines(*bandit),
                      f"JSON: {out}/bandit.json" if fail else f"JSON: {out}/pip-audit.json, {out}/bandit.json", result, SCAN.END,
                      "Evaluating cleanup command on EXIT ...", "Caught termination signal!"])


JOB_SECONDS = 0.45   # how long the scan Job runs: longer than one wait_job call (gateway.WAIT_S), shorter than two


class FakeDomino:
    """The Job's sidecar for one case: Domino's APIs as the specs have them (reference_materials/domino-api-specs in the service repo).
    Governance (api-governance.swagger.json): guardrails.Bundle, guardrails.Policy, POST /findings (guardrails.Finding), POST
    /rpc/submit-result-to-policy (guardrails.ComputedPolicy), POST /bundles/{id}/attachments (guardrails.Attachment), errors as
    {"message"}. Jobs and datasets (public-api.json): JobEnvelopeV1, LogsEnvelopeV1, DatasetRwEnvelopeV1, SnapshotEnvelopeV1. `calls`
    holds each request: (method, path, query, body)."""

    def __init__(self, job_end="Succeeded", log=None, snapshot_statuses=("pending", "active")):
        self.policy = published_policy()
        self.bundle = {"id": BUNDLE["id"], "name": BUNDLE["name"], "projectId": PROJECT["id"], "projectName": PROJECT["name"],
                       "projectOwner": "analyst", "policyId": "pol-app", "policyName": "App deployment policy", "policyVersionId": "pv-1",
                       "policyVersion": "1", "stage": "Validation", "state": "Active", "createdAt": "2026-11-17T10:00:00Z",
                       "createdBy": {"id": "u-analyst", "userName": "analyst"}, "attachments": [], "stages": [], "policies": []}
        self.job_end, self.log, self.snapshot_statuses = job_end, scan_log() if log is None else log, list(snapshot_statuses)
        self.calls, self.snapshots, self.job, self.job_started, self.folder = [], {}, None, None, None   # folder: the dataset's mount

    def http(self, method, path, query=None, body=None, raw=False, ctype=None, headers=None):
        self.calls.append((method, path, query, body))
        parts = path.strip("/").split("/")
        if method == "GET" and path == f"/api/governance/v1/bundles/{BUNDLE['id']}":
            return 200, self.bundle
        if method == "GET" and path == "/api/governance/v1/policies/pol-app":
            return 200, self.policy
        if method == "POST" and path == "/api/jobs/v1/jobs":
            self.job_started = time.time()
            self.job = {"id": "job-1", "number": 41, "title": body.get("title"), "runCommand": body.get("runCommand"),
                        "projects": [{"projectId": body.get("projectId"), "commitId": SCANNED}], "status": self.job_status("Queued")}
            return 200, {"job": self.job, "metadata": {"requestId": "rq-job", "notices": []}}
        if method == "GET" and path == "/api/jobs/beta/jobs/job-1":
            # the Job runs for JOB_SECONDS: a wait_job call (WAIT_S) ends before that, so the graph must call it again
            status = self.job_end if time.time() - self.job_started >= JOB_SECONDS else "Running"
            return 200, {"job": {**self.job, "status": self.job_status(status)}, "metadata": {"requestId": "rq-get", "notices": []}}
        if method == "GET" and path == "/api/jobs/beta/jobs/job-1/logs":
            text = self.log if (query or {}).get("logType") == "stdout" else "Pulling image ...\nContainer started"
            return 200, {"logs": {"isComplete": True, "logContent": [
                {"log": line, "logType": query["logType"], "size": len(line), "timestamp": "2026-11-17T11:00:00Z"}
                for line in text.splitlines()]}, "metadata": {"requestId": "rq-logs", "notices": []}}
        if method == "GET" and path == f"/api/datasetrw/v1/datasets/{DATASET['id']}":
            return 200, {"dataset": {"id": DATASET["id"], "name": DATASET["name"], "projectId": PROJECT["id"], "description": "",
                                     "createdAt": "2026-11-01T10:00:00Z", "snapshotIds": list(self.snapshots), "tags": {}},
                         "metadata": {"requestId": "rq-ds", "notices": []}}
        if method == "POST" and path == f"/api/datasetrw/v1/datasets/{DATASET['id']}/snapshots":
            sid = f"snap-{len(self.snapshots) + 1}"   # what the dataset holds at the snapshot: the files written before it
            self.snapshots[sid] = sorted(str(f.relative_to(self.folder)) for f in self.folder.rglob("*") if f.is_file())
            return 200, self.snapshot(sid, "pending")
        if method == "GET" and parts[:4] == ["api", "datasetrw", "v1", "snapshots"] and parts[4:] and parts[4] in self.snapshots:
            status = self.snapshot_statuses.pop(0) if len(self.snapshot_statuses) > 1 else self.snapshot_statuses[0]
            return 200, self.snapshot(parts[4], status)
        if method == "POST" and path == "/api/governance/v1/findings":
            return 200, {"id": f"fnd-{len(self.posted('/api/governance/v1/findings'))}", "status": "ToDo", **body,
                         "createdAt": "2026-11-17T11:06:00Z", "createdBy": {"id": "u-sa", "userName": "svc_validator"}}
        if method == "POST" and path == "/api/governance/v1/rpc/submit-result-to-policy":
            if body.get("policyId") != "pol-app" or body.get("bundleId") != BUNDLE["id"]:
                return 400, {"message": "the policy isn't the bundle's"}
            results = [{"id": f"res-{aid}", "artifactId": aid, "artifactContent": v, "bundleId": BUNDLE["id"], "evidenceId": body["evidenceId"],
                        "createdAt": "2026-11-17T11:07:00Z", "createdBy": {"id": "u-sa", "userName": "svc_validator"}, "isLatest": True}
                       for aid, v in (body.get("content") or {}).items()]
            return 200, {"bundle": self.bundle, "policy": self.policy, "results": results, "approvals": [], "bundleStages": [],
                         "drafts": [], "commentsInfo": {"bundleCommentsCount": 0}, "findingsInfo": {"bundleFindingsCount": 2},
                         "isUserApprover": False}
        if method == "POST" and path == f"/api/governance/v1/bundles/{BUNDLE['id']}/attachments":
            return 200, {"id": "att-1", "type": body["type"], "identifier": body["identifier"], "source": "MANUAL",
                         "createdAt": "2026-11-17T11:05:00Z", "createdBy": {"id": "u-sa", "userName": "svc_validator"},
                         "approvalTimelineMap": {}}
        return 404, {"message": f"{path} not found"}

    def posted(self, path):
        """The bodies of the POSTs that Domino got on this path."""
        return [b for m, p, q, b in self.calls if (m, p) == ("POST", path)]

    @staticmethod
    def snapshot(sid, status):
        return {"snapshot": {"id": sid, "datasetId": DATASET["id"], "status": status, "createdAt": "2026-11-17T11:04:00Z",
                             "creatorId": "u-sa", "description": ""}, "metadata": {"requestId": f"rq-{sid}", "notices": []}}

    @staticmethod
    def job_status(status):
        return {"executionStatus": status, "isCompleted": status in ("Succeeded", "Failed", "Stopped", "Error"), "isArchived": False,
                "isScheduled": False}


# ------------------------------------------------------------------------------------------------------ the relay, as a Job sets it up
class Relay:
    """The Job's relay (proxies.relay) with the Job's Gateway (run.Gateway): as the framework lane starts it, with no relay tool of its
    own (run.py). Each case gets a new Gateway on its own fake Domino; `calls` holds the graph's tool calls, (name, arguments)."""

    def __init__(self):
        self.gw, self.calls, self.events = None, [], []
        self.server, _ = proxies.relay(0, RELAY_TOKEN, [], self.events.append, None, gateway=self, inbox=None, on_error="fail", hide=())
        proxies.serve(self.server)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self, domino, task_key):
        self.gw = runtime.Gateway(gateway_policy(task_key), self.events.append, http=domino.http)
        self.calls.clear()
        self.events.clear()

    def names(self):
        return list(gateway.TOOLS)

    def defs(self):
        return self.gw.defs()

    def call(self, name, args):
        self.calls.append((name, args))
        return self.gw.call(name, args)

    @property
    def held(self):
        return self.gw.held if self.gw else None


relay = Relay()
model = fake_model.start()
TMP = Path(tempfile.mkdtemp(prefix="v268-", dir="/tmp" if os.path.isdir("/tmp") else None))   # a short path: a Unix socket's limit
SOCKET = str(TMP / "agui.sock")
server_log = open(TMP / "serve.log", "w")
(TMP / "state").mkdir()   # the state folder: the bootstrapper makes it, and the adapter keeps the checkpoint there
env = {"PATH": os.environ.get("PATH", ""), "HOME": str(TMP), "PYTHONPATH": str(AGUI), "PYTHONDONTWRITEBYTECODE": "1",
       "AGENT_SERVICE_URL": relay.url, "SESSION_TOKEN": RELAY_TOKEN, "AGENT_MODEL": "sonnet", "AGENT_MODEL_FORMAT": "anthropic",
       "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{model.server_address[1]}/anthropic", "NO_PROXY": "127.0.0.1,localhost",
       "TASK_KEY": "AGT-268"}
agent_server = subprocess.Popen([sys.executable, str(SERVE), "--framework", "langgraph", "--entrypoint", ENTRYPOINT, "--socket", SOCKET,
                                 "--code", str(ROOT), "--state", str(TMP / "state")], env=env, cwd=str(ROOT), stdout=server_log,
                                stderr=subprocess.STDOUT)


def healthy():
    """The agent server's /health answer, or None while nothing listens on the socket (client.health raises OSError then)."""
    try:
        return client.health(SOCKET)
    except (OSError, client.ClientError):
        return None


for _ in range(300):
    if agent_server.poll() is not None or healthy():
        break
    time.sleep(0.1)
up = agent_server.poll() is None and (healthy() or {}).get("framework") == "langgraph"
check("the platform's serve module loads the entry point from this repo and serves it with the LangGraph adapter", up,
      (TMP / "serve.log").read_text()[-1500:])


def close():
    agent_server.terminate()
    try:
        agent_server.wait(10)
    except subprocess.TimeoutExpired:
        agent_server.kill()
    relay.server.shutdown()
    model.shutdown()
    if os.environ.get("KEEP") == "1":   # KEEP=1 keeps the folder: the agent server's log and each case's doc
        print(f"     kept {TMP}", flush=True)
    else:
        shutil.rmtree(TMP, ignore_errors=True)


if not up:
    close()
    done()


def run_task(case, domino, thread_id=None, task_key="AGT-268", messages=None):
    """One AG-UI run of the task, as the framework lane's driver makes it: the instruction as the user message, the operating rules and
    the task brief as the context. -> {"result", "error", "events", "thread"}. `case` names the fake model's script ([certify <case>] in
    the bundle's name, so in the instruction)."""
    relay.start(domino, task_key)
    fake_model.seen.clear()
    folder = TMP / f"data-{case}"   # the doc dataset's mount in the Job
    folder.mkdir(exist_ok=True)
    domino.folder = folder
    th = messages or thread.Thread(thread_id or f"t-{case}")
    if not messages:
        th.add_user(instruction_for(f"{BUNDLE['name']} [certify {case}]", folder))
    context = [{"description": "Domino Agents: the operating rules and the task brief",
                "value": (d.get("systemPrompt") or "") + "\n\n## Operating rules\n\n(the platform's rules)\n\n## Task brief\n\n(the brief)"}]
    body = th.run_input(f"run-{case}-{uuid.uuid4().hex[:6]}", tools=[], context=context)
    rules, tr, got, error = stream.Rules(), events.Translator(), [], None
    try:
        for ev in client.run(SOCKET, body, deadline=time.time() + 120):
            got.append(ev)
            rules.see(ev)
            tr.feed(ev)
            if rules.final:
                break
        rules.end(tr.open_calls(set()))
    except (stream.StreamError, client.ClientError, OSError) as e:
        error = str(e)
    if (rules.final or {}).get("type") == "RUN_ERROR":
        error = rules.final.get("message") or "RUN_ERROR"
    th.absorb(tr.messages, tr.state)
    final = (rules.final or {}).get("result")
    return {"result": final if final is not None else tr.last_text, "error": error, "events": got, "thread": th, "folder": folder}


def tools(calls):
    return [n for n, _ in calls]


# ------------------------------------------------------------------------------------------------------------ the case: a clean App
ANALYSIS = "validation_analysis"   # the tool through which the model gives its analysis (the graph's structured output)
MAIN = {   # the model's analysis of main: what a careful reviewer finds there (no CVE; the two bandit hits are false)
    "app": "aml-case-management",
    "purpose": "A fake case-management system for AML alerts, served as an MCP server. Agents read alerts and close or escalate them.",
    "tech_stack": "Python 3, the mcp package (FastMCP, streamable HTTP), SQLite.",
    "architecture": "app.sh starts case_server/server.py on port 8888. The MCP tools and the /reset and board routes are on one server.",
    "dependencies": [{"name": "mcp", "version": ">=1.10,<2", "installed_by": "app.sh, from PyPI at App start when it is missing"}],
    "real_findings": [
        {"title": "POST /reset wipes all state for any caller", "severity": "S1", "source": "code",
         "evidence": "case_server/server.py: the /reset route", "fix": "Allow /reset only to the App's owner.",
         "description": "Anyone who can open the App can wipe every alert and SAR case."},
        {"title": "A write with no domino-username runs as no identity", "severity": "S2", "source": "code",
         "evidence": "case_server/server.py: who acted", "fix": "Refuse a write with no identity.",
         "description": "A write records no person when the header is missing."}],
    "false_hits": [{"hit": "B104 hardcoded_bind_all_interfaces at case_server/server.py:159",
                    "reason": "Domino's Apps proxy reaches the App only on 0.0.0.0."},
                   {"hit": "B608 hardcoded_sql_expressions at case_server/store.py:215",
                    "reason": "The query builds only placeholders; the values are bound."}],
    "critical_vulns_reason": "No real finding is S0: pip-audit found no known vulnerability.",
    "verdict": "approve after fixes", "verdict_reason": "Fix the /reset route first: anyone can wipe the data.",
    "could_not_check": ["What only the running App shows: the Apps proxy and the identity headers."],
    "summary": "A small MCP App with no known vulnerability. Anyone can wipe its state with POST /reset."}
before_model = []   # the graph's tool calls before the model's first request


def analyst(analysis):
    """The fake model's script: the analysis, through the validation_analysis tool when the request offers it."""
    def script(conv):
        if ANALYSIS not in conv.tools:
            return fake_model.answer(f"no {ANALYSIS} tool was offered")
        return fake_model.answer("", [(ANALYSIS, analysis)])
    return script


fake_model.SCRIPTS["C268main"] = analyst(MAIN)
fake_model.BEFORE["C268main"] = lambda conv: before_model.append(tools(relay.calls))
dom = FakeDomino()
ran = run_task("C268main", dom)
ran["result"] = ran["result"] or ""
check("MAIN the run ends with no error", ran["error"] is None, ran["error"])
check("MAIN collect: the graph first reads the bundle and its policy (get_bundle, then get_policy), with the event's bundle ID",
      relay.calls[:2] == [("get_bundle", {"bundleId": BUNDLE["id"]}), ("get_policy", {"bundleId": BUNDLE["id"]})], relay.calls[:3])
check("MAIN the task has a result, which names the bundle", BUNDLE["id"] in (ran["result"] or ""), ran["result"])


def scan_calls(calls):
    """The scan step's calls: run_job, then each wait_job, then get_job_logs. -> (run_job's arguments, the number of wait_job calls,
    whether get_job_logs came right after them for the same Job), or None when the calls aren't in that shape."""
    names = tools(calls)
    if "run_job" not in names:
        return None
    i = names.index("run_job")
    n = next((k for k, name in enumerate(names[i + 1:]) if name != "wait_job"), len(names) - i - 1)
    after = calls[i + 1 + n] if i + 1 + n < len(calls) else (None, None)
    return calls[i][1], n, after == ("get_job_logs", {"jobId": "job-1"}) and all(a == {"jobId": "job-1"} for _, a in calls[i + 1:i + 1 + n])


check("MAIN scan: right after the policy, run_job with the shared scan's command, then wait_job until the Job is done (it still runs "
      "at the first wait, so two calls or more), then get_job_logs",
      tools(relay.calls).index("run_job") == 2 and scan_calls(relay.calls)[0] == {"command": "python governance/scan.py",
                                                                                 "title": "App validation scan (LangGraph)"}
      and scan_calls(relay.calls)[1] >= 2 and scan_calls(relay.calls)[2], relay.calls[2:8])
asked = [r for r in fake_model.seen if r.get("format") == "anthropic"]
body = asked[0]["body"] if asked else {}
check("MAIN analyze: one model call, after the scan's get_job_logs", len(fake_model.seen) == 1 and before_model
      and before_model[0][-1] == "get_job_logs" and "write_governance_finding" not in before_model[0], (len(fake_model.seen), before_model))
check("MAIN its model is the agent's alias, in the Anthropic format, with max_tokens 16000 (domino-agui#1: the ready-made model's "
      "default gives an alias 4,096)", body.get("model") == "sonnet" and body.get("max_tokens") == 16000,
      {k: body.get(k) for k in ("model", "max_tokens")})
offered = [x.get("name") for x in body.get("tools") or []]
check("MAIN the model gets one tool, validation_analysis, and the choice isn't forced (Claude's newest models refuse a forced one)",
      offered == [ANALYSIS] and (body.get("tool_choice") or {}).get("type") in (None, "auto"), (offered, body.get("tool_choice")))
said = asked[0]["conv"].text() if asked else ""
check("MAIN the model reads the scan's summary (each bandit hit), the App's code and the task's instruction",
      SCAN.START in said and "B608 hardcoded_sql_expressions at case_server/store.py:215" in said
      and (ROOT / "case_server" / "server.py").read_text()[:400] in said and "Bundle ID: " + BUNDLE["id"] in said, said[:300])
check("MAIN the model reads the shared rules: the severity scale and the rule for critical vulns (governance/README.md)",
      "## The severity scale" in said and "## Critical vulns" in said and "S0 (critical)" in said, said[:300])
shown = [e for e in ran["events"] if e.get("type", "").startswith(("TEXT_MESSAGE", "TOOL_CALL"))]
check("MAIN the model's analysis stays out of the task's stream: no tool call, and no text but the result",
      not [e for e in shown if e["type"].startswith("TOOL_CALL")]
      and all(MAIN["false_hits"][0]["reason"] not in json.dumps(e) for e in shown), shown[:3])
lines = (ran["result"] or "").splitlines()
check("MAIN the result starts with the verdict and critical vulns: the model's verdict, and no S0 finding is no",
      lines[:2] == ["Verdict: approve after fixes", "Critical vulns: no"], lines[:3])
docs = sorted(f.name for f in ran["folder"].iterdir())
doc = (ran["folder"] / docs[0]).read_text() if len(docs) == 1 else ""
after = tools(relay.calls)[tools(relay.calls).index("get_job_logs") + 1:]
check("MAIN write: after the scan, write_dataset_snapshot of the doc dataset, then get_dataset_snapshot until the snapshot is active (it "
      "is pending at first), then write_bundle_attachment",
      after[:4] == ["write_dataset_snapshot", "get_dataset_snapshot", "get_dataset_snapshot", "write_bundle_attachment"]
      and relay.calls[tools(relay.calls).index("write_dataset_snapshot")][1] == {"datasetId": DATASET["id"]}
      and all(a == {"datasetId": DATASET["id"], "snapshotId": "snap-1"} for n, a in relay.calls if n == "get_dataset_snapshot"), after)
check("MAIN the doc is one Markdown file in the dataset's folder, written before the snapshot (the snapshot has it)",
      len(docs) == 1 and docs[0].endswith(".md") and BUNDLE["id"] in docs[0] and dom.snapshots.get("snap-1") == docs, (docs, dom.snapshots))
attach = next((a for n, a in relay.calls if n == "write_bundle_attachment"), {})
check("MAIN the attachment is the doc's file in that snapshot (DatasetSnapshotFile), on the event's bundle",
      attach == {"bundleId": BUNDLE["id"], "type": "DatasetSnapshotFile",
                 "identifier": {"datasetId": DATASET["id"], "snapshotId": "snap-1", "filename": docs[0] if docs else None}}, attach)
check("MAIN the result's third line is the doc's location: the dataset, the snapshot and the file",
      lines[2:3] == [f"Doc location: dataset {DATASET['id']}, snapshot snap-1, file {docs[0] if docs else None}"], lines[:4])
TEMPLATE = (ROOT / "governance" / "validation-doc.md").read_text()
heads = [ln for ln in TEMPLATE.splitlines() if ln.startswith("#")]
check("MAIN the doc is the shared template filled: every heading in its order, no field left and no comment",
      [ln for ln in doc.splitlines() if ln.startswith("#")] == [h.replace("{{app}}", MAIN["app"]) for h in heads]
      and "{{" not in doc and "<!--" not in doc, [ln for ln in doc.splitlines() if ln.startswith("#")][:3])
check("MAIN the doc names the validator, the bundle and the commit that the scan read",
      "Validator: App validator (LangGraph)" in doc and f"Bundle: {BUNDLE['id']}" in doc and SCANNED in doc, doc[:400])
check("MAIN the doc's scan results: each tool with its version and its hits, and the scan Job",
      "| pip-audit | 2.10.1 | no known vulnerabilities in 29 packages |" in doc and "| bandit | 1.9.4 | 2 hits: B104 hardcoded_bind_all_interfaces at case_server/server.py:159" in doc
      and "Job 41" in doc, doc[doc.find("## Scan results"):][:600])
check("MAIN the doc's real findings: a table with each finding's name (with [LangGraph]), severity, evidence and fix",
      "| [LangGraph] POST /reset wipes all state for any caller | S1 | case_server/server.py: the /reset route | Allow /reset only to "
      "the App's owner. |" in doc, doc[doc.find("### Real findings"):][:600])
check("MAIN the doc's false hits: each bandit hit with the reason", all(f"| {h['hit']} | {h['reason']} |" in doc for h in MAIN["false_hits"]),
      doc[doc.find("### False hits"):][:600])
check("MAIN the doc's verdict and critical vulns, with their reasons", "Critical vulns: no" in doc and MAIN["critical_vulns_reason"] in doc
      and "Verdict: approve after fixes" in doc and MAIN["verdict_reason"] in doc, doc[doc.find("## Critical vulns"):][:400])
check("MAIN the Intake fields say Not read (no gateway tool reads a bundle's results yet), and the doc says so under what the validator "
      "could not check", "Not read" in doc[doc.find("## Users and data class"):doc.find("## Tech stack")]
      and "Intake" in doc[doc.find("## What the validator could not check"):] and MAIN["could_not_check"][0] in doc,
      doc[doc.find("## Users and data class"):][:300])
item = next(e for st in dom.policy["stages"] for e in st["evidenceSet"] if e["name"] == EVIDENCE)
field = {(x["details"] or {}).get("label"): x["id"] for x in item["artifacts"]}
filed = [a for n, a in relay.calls if n == "write_governance_finding"]
check("MAIN findings: one write_governance_finding for each real finding, named [LangGraph] <title>, with its severity, and its "
      "evidence and fix in the description",
      [(a["bundleId"], a["name"], a["severity"]) for a in filed] == [(BUNDLE["id"], "[LangGraph] " + f["title"], f["severity"])
                                                                      for f in MAIN["real_findings"]]
      and all(f["evidence"] in a.get("description", "") and f["fix"] in a.get("description", "") for f, a in zip(MAIN["real_findings"], filed)),
      filed)
check("MAIN Domino got each finding on the bundle, with the bundle's policy version (the gateway fills it)",
      [(b["bundleId"], b["name"], b["policyVersionId"]) for b in dom.posted("/api/governance/v1/findings")]
      == [(BUNDLE["id"], "[LangGraph] " + f["title"], "pv-1") for f in MAIN["real_findings"]], dom.posted("/api/governance/v1/findings"))
result_call = relay.calls[-1] if relay.calls else (None, {})
content = result_call[1].get("content") or {}
check("MAIN last, write_policy_result for the evidence item Validation (LangGraph) only, found by its name in the policy",
      result_call[0] == "write_policy_result" and result_call[1].get("bundleId") == BUNDLE["id"]
      and result_call[1].get("evidenceId") == item["id"] and tools(relay.calls).count("write_policy_result") == 1, result_call)
check("MAIN its content fills the four fields, each by its label's artifact ID: the verdict and critical vulns as the radios' values, "
      "the summary, and the doc's location",
      set(content) == set(field.values()) and content[field["Verdict"]] == "approve after fixes" and content[field["Critical vulns"]] == "no"
      and MAIN["summary"] in content[field["Summary"]] and content[field["Doc location"]] == lines[2].split(": ", 1)[-1], content)
check("MAIN Domino got the result with the bundle's policy (the gateway fills it)",
      [(b["bundleId"], b["policyId"], b["evidenceId"]) for b in dom.posted("/api/governance/v1/rpc/submit-result-to-policy")]
      == [(BUNDLE["id"], "pol-app", item["id"])], dom.posted("/api/governance/v1/rpc/submit-result-to-policy"))
ORDER = re.compile(r"get_bundle get_policy run_job( wait_job)+ get_job_logs write_dataset_snapshot( get_dataset_snapshot)+ "
                   r"write_bundle_attachment( write_governance_finding)* write_policy_result")
check("MAIN the gateway calls, in the ticket's order: get_bundle, get_policy, run_job, wait_job until done, get_job_logs, "
      "write_dataset_snapshot, the snapshot wait, write_bundle_attachment, the findings, write_policy_result, and no other",
      ORDER.fullmatch(" ".join(tools(relay.calls))) is not None, tools(relay.calls))
steps = [e.get("stepName") for e in ran["events"] if e.get("type") == "STEP_STARTED"]
check("MAIN the graph's five steps run once each, in order: collect, scan, analyze, write, findings",
      steps == ["collect", "scan", "analyze", "write", "findings"], steps)
check("MAIN the result names the findings it filed and the false hits",
      all("[LangGraph] " + f["title"] in ran["result"] for f in MAIN["real_findings"]) and "False hits (2)" in ran["result"], ran["result"])
started = [b for m, p, q, b in dom.calls if (m, p) == ("POST", "/api/jobs/v1/jobs")]
check("MAIN Domino got one Job, in the task's project, with the scan's command",
      len(started) == 1 and started[0]["runCommand"] == "python governance/scan.py" and started[0]["projectId"] == PROJECT["id"], started)



def run_case(case, domino, analysis=None, script=None):
    """One more task, with its own fake Domino and the model's script. -> (the run, its result's lines, the doc, the filed findings,
    the evidence item's content by label)"""
    fake_model.SCRIPTS[case] = script or analyst(analysis)
    got = run_task(case, domino)
    got["result"] = got["result"] or ""
    files = sorted(got["folder"].iterdir())
    text = files[0].read_text() if len(files) == 1 else ""
    found = [a for n, a in relay.calls if n == "write_governance_finding"]
    last = relay.calls[-1] if relay.calls and relay.calls[-1][0] == "write_policy_result" else (None, {})
    mine = next(e for st in domino.policy["stages"] for e in st["evidenceSet"] if e["name"] == EVIDENCE)   # its own artifact IDs
    labels = {x["id"]: (x["details"] or {}).get("label") for x in mine["artifacts"]}
    filled = {labels.get(k, k): v for k, v in (last[1].get("content") or {}).items()}
    return got, got["result"].splitlines(), text, found, filled


# --------------------------------------------------------------------------------------------- the case: the scan Job fails
FAILED = {**MAIN, "real_findings": [
    {"title": "pyyaml 5.3.1 has PYSEC-2021-142", "severity": "S0", "source": "scan", "evidence": "the scan", "fix": "Pin pyyaml 5.4.",
     "description": "A scanner finding that the model gives although the scan did not run."},
    MAIN["real_findings"][0]], "verdict": "approve after fixes", "summary": "The code has one real finding."}
ran, lines, doc, filed, filled = run_case("C268fail", FakeDomino(job_end="Failed", log=scan_log(fail="pip-audit"),
                                                                 snapshot_statuses=("active",)), FAILED)
said = fake_model.seen[0]["conv"].text() if fake_model.seen else ""
check("SCANFAIL the run ends with no error, and the gateway calls keep the ticket's order",
      ran["error"] is None and ORDER.fullmatch(" ".join(tools(relay.calls))) is not None, (ran["error"], tools(relay.calls)))
check("SCANFAIL the model is told that the scan did not run to its end, and why (the Job failed, and pip-audit could not run)",
      "The scan did not run to its end: the scan Job 41 ended Failed: pip-audit could not run" in said
      and "Give no finding with the source scan" in said, said[said.find("## The scan"):][:300])
check("SCANFAIL no scanner finding is filed: only the finding from the code",
      [a["name"] for a in filed] == ["[LangGraph] " + MAIN["real_findings"][0]["title"]], [a["name"] for a in filed])
scan_part = doc[doc.find("## Scan results"):doc.find("## Findings")]
check("SCANFAIL the doc says so: its scan results say that the scan did not run to its end, with the Job and why",
      "The scan did not run to its end: the scan Job 41 ended Failed" in scan_part and "pip-audit could not run" in scan_part
      and "Scan Job 41: Failed." in scan_part, scan_part)
check("SCANFAIL the doc's real findings have no scanner finding, and what the validator could not check names the scan",
      "PYSEC-2021-142" not in doc[doc.find("### Real findings"):doc.find("### False hits")]
      and "The scan: the scan Job 41 ended Failed" in doc[doc.find("## What the validator could not check"):], doc[-600:])
check("SCANFAIL the verdict is do not approve, because the scan did not run (and critical vulns comes from the real findings only)",
      lines[:2] == ["Verdict: do not approve", "Critical vulns: no"] and "Verdict: do not approve" in doc
      and "the dependencies' known vulnerabilities were not checked" in doc, lines[:3])
check("SCANFAIL the evidence item says so: do not approve, and its summary says that the scan did not run to its end",
      filled.get("Verdict") == "do not approve" and filled.get("Critical vulns") == "no"
      and "The scan did not run to its end" in (filled.get("Summary") or ""), filled)

# --------------------------------------------------------------------------------------------- the case: no usable analysis
ran, lines, doc, filed, filled = run_case("C268noanalysis", FakeDomino(snapshot_statuses=("active",)),
                                          script=lambda conv: fake_model.answer("I looked at the code and it seems fine."))
check("NOANALYSIS the model is asked twice (an answer with no validation_analysis call is asked again once)",
      len(fake_model.seen) == 2 and "Your last answer could not be used" in fake_model.seen[1]["conv"].text(), len(fake_model.seen))
check("NOANALYSIS no finding is filed, and the run still writes the doc and fills the evidence item",
      not filed and "write_bundle_attachment" in tools(relay.calls) and tools(relay.calls)[-1] == "write_policy_result", tools(relay.calls))
check("NOANALYSIS the verdict is do not approve, and the result and the doc say that the analysis failed",
      lines[0] == "Verdict: do not approve" and "analyze: the model's answer has no validation_analysis call" in ran["result"]
      and "The validator's analysis failed" in doc, ran["result"])
check("NOANALYSIS the model's text stays out of the task's stream", "seems fine" not in json.dumps(ran["events"]), "")

close()
done()
