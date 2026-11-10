"""The agent's definition (agent/definition.json) and the script that creates the agent through the App's API (agent/register.py), seen
from outside: the file as the platform App receives it, the script's print mode, and the script's calls to a small fake App, with
extended identity (your token) and with --view-as (your name in the view-as header). No Domino host: the fake App on
127.0.0.1 also serves the Workspace's token and Domino's /api/users/v1/self. The script runs with python -S (no site-packages), so a
package outside the stdlib fails the check. The real calls are proven in the live check.

  python tests/check_registration.py
"""
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFINITION = ROOT / "agent" / "definition.json"
failed = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{str(detail)[:600]}]" if detail and not ok else ""), flush=True)
    if not ok:
        failed.append(name)


# ------------------------------------------------------------------------------------------------------------------- the definition
try:
    d = json.loads(DEFINITION.read_text())
except (OSError, ValueError) as e:
    d = {}
    check("agent/definition.json is a JSON file", False, e)

check("the lane is framework", d.get("lane") == "framework", d.get("lane"))
check("the framework is langgraph, at agent/graph.py:build_graph, with the two client-side tools",
      d.get("framework") == {"name": "langgraph", "entrypoint": "agent/graph.py:build_graph",
                             "clientTools": ["aml_close_alert", "aml_escalate_to_sar"]}, d.get("framework"))
check("toolServers names aml only, with every tool", d.get("toolServers") == [{"server": "aml"}], d.get("toolServers"))
model = d.get("model") or {}
check("the model is one Claude alias from the LLM Gateway, with the acting identity's grants",
      model.get("source") == "gateway" and len(model.get("models") or []) == 1 and model.get("access") == "acting"
      and (model.get("models") or [""])[0] in ("sonnet", "opus", "haiku"), model)
ex = d.get("execution") or {}
check("it runs as a Job, and the file names no Environment (the script sets the certified one for the variant it creates)",
      ex.get("runtime") == "job" and "environment" not in ex, ex)
check("it has one input: a required project", d.get("inputs") == [{"name": "project", "type": "project", "required": True}],
      d.get("inputs"))
access = (d.get("guardrails") or {}).get("access") or {}
check("project access is read and data access is none", access.get("project") == "read" and access.get("data") == "none", access)
check("it acts as the analyst who starts the task (triggering_user)", d.get("identity") == {"mode": "triggering_user"}, d.get("identity"))
check("its access is restricted, and the file names no person (the script adds them)",
      d.get("access") == {"mode": "restricted", "users": [], "editors": []}, d.get("access"))
check("it has a name and a description", bool(d.get("name")) and bool(d.get("description")), (d.get("name"), d.get("description")))
check("a failed run fails the task, and no key is one the App drops (it keeps only its agent fields)",
      d.get("onError") == "fail" and not set(d) - {"name", "description", "tags", "color", "scope", "model", "systemPrompt", "guardrails",
                                                    "completion", "identity", "access", "onError", "execution", "enabled", "inputs",
                                                    "lane", "framework", "toolServers"}, sorted(d))

# ------------------------------------------------------------------------------------------------------- the AML rules in the prompt
prompt = d.get("systemPrompt") or ""
lines = [ln.lower() for ln in prompt.splitlines()]


def rule(name, *words):
    """One line of the prompt says the rule: it holds every one of `words` (case aside)."""
    check(f"the prompt says: {name}", any(all(w.lower() in ln for w in words) for ln in lines), words)


rule("read the alert first", "aml_get_alert", "first")
rule("a closed or escalated alert gets a report and no write", "closed or escalated", "write nothing", "report")
rule("read the profile and the transactions before any decision", "aml_get_customer_profile", "aml_get_transactions",
     "before", "decide")
rule("close only with a reason code and a rationale", "aml_close_alert", "only with a reason code", "rationale")
rule("the reason codes", "false_positive", "explained_activity", "duplicate")
rule("escalate only with a narrative and the supporting transaction IDs", "aml_escalate_to_sar", "only with a narrative",
     "transaction ids", "support")
rule("ask the analyst when the evidence is unclear", "unclear", "ask the analyst", "ask_human")
rule("...unclear means one transaction that doesn't fit the profile and no pattern: ask what it is for before escalating",
     "unclear when", "no pattern", "ask what the transaction is for before you escalate")
rule("with no answer, leave the alert open and say why", "no answer", "leave the alert open", "say why")
rule("after a denied escalation, report the denial and who denied it", "denies", "report the denial", "who denied it")
rule("...and make no other write", "denies", "no other write")
heads = ["**Decision**", "**Rationale**", "**Evidence**", "**Action taken**"]
at = [prompt.find(h) for h in heads]
check("the prompt ends the task with the summary: Decision, Rationale, Evidence, Action taken, in that order",
      all(i >= 0 for i in at) and at == sorted(at), dict(zip(heads, at)))
rule("the summary's Evidence names the transaction IDs", "**evidence**", "transaction ids")
rule("an answer with a SAR case ID means that a reviewer approved the escalation and it ran", "sar case id",
     "reviewer approved", "only after it ran")
rule("...so Action taken never says that an escalation that ran still waits for approval", "**action taken**", "no longer waits")
named = set(re.findall(r"\baml_[a-z_]+", prompt))
check("the prompt names the five case-management tools, and no other aml_ name",
      named == {"aml_get_alert", "aml_get_customer_profile", "aml_get_transactions", "aml_close_alert", "aml_escalate_to_sar"}, named)
gateway = {"domino_", "get_project", "list_projects", "list_datasets", "get_dataset", "list_jobs"}
check("the prompt names no Domino gateway tool", not [g for g in gateway if g in prompt], [g for g in gateway if g in prompt])


# ------------------------------------------------------------------------------------------------------------------- the entry points
def text(path):
    try:
        return path.read_text()
    except OSError as e:
        return f"<{e}>"


ENTRY_POINTS = {   # the file: its one line, the ready-made agent of domino-agui (the helper library) for one framework
    "graph.py": "from domino_agui.langgraph import build_graph\n",
    "flow.py": "from domino_agui.crewai import build_flow\n",
    "handler.py": "from domino_agui.loop import handler\n",
}
for f, line in ENTRY_POINTS.items():
    check(f"agent/{f} is one line: {line.strip()}", text(ROOT / "agent" / f) == line, text(ROOT / "agent" / f)[:300])
agent_files = sorted(p.name for p in (ROOT / "agent").iterdir() if p.is_file() and not p.name.startswith("."))
check("agent/ holds the three entry points, the definition and the script, and nothing else",
      agent_files == sorted([*ENTRY_POINTS, "definition.json", "register.py"]), agent_files)
FRAMEWORK_IMPORT = re.compile(r"^\s*(from|import)\s+(domino_agui|langgraph|langchain\w*|crewai|litellm|anthropic|openai|ag_ui\w*)\b", re.M)
contract_code = sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob("*.py")
                       if not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(ROOT).parts)
                       and p.parent != ROOT / "agent" and FRAMEWORK_IMPORT.search(text(p)))
check("no other Python file imports domino-agui or an agent framework (the repo has no other agent contract code)",
      contract_code == [], contract_code)


# ------------------------------------------------------------------------------------------------------------------- the fake App
BEARER = "Authorization bearer (JWT or PAT, verified with Domino)"   # how the App knows you by your token (its api/me `source`)
CERTIFIED = [   # the App's GET api/platform/certified-environments: one entry per certified (Environment, framework) pair, in its order
    {"environmentId": "6ae2aaaaaaaaaaaaaaaaaaaa", "revisionId": "6ae2a1a1a1a1a1a1a1a1a1a1", "framework": "langgraph",
     "name": "agent-langgraph (first)"},
    {"environmentId": "6ae2cccccccccccccccccccc", "revisionId": "6ae2c1c1c1c1c1c1c1c1c1c1", "framework": "crewai", "name": "agent-crewai"},
    {"environmentId": "6ae2bbbbbbbbbbbbbbbbbbbb", "revisionId": "6ae2b1b1b1b1b1b1b1b1b1b1", "framework": "langgraph",
     "name": "agent-langgraph (second)"},
    {"environmentId": "6ae2dddddddddddddddddddd", "revisionId": "6ae2d1d1d1d1d1d1d1d1d1d1", "framework": "domino-agui", "name": None},
]
CERTIFIED_ID = {   # the one the script must take for each framework: the last one listed (two for langgraph)
    "langgraph": "6ae2bbbbbbbbbbbbbbbbbbbb", "crewai": "6ae2cccccccccccccccccccc", "domino-agui": "6ae2dddddddddddddddddddd"}


class Fake(BaseHTTPRequestHandler):
    """The platform App behind its Apps path /app, the Workspace's token at /access-token, and Domino's /api/users/v1/self. `state` says
    how the App answers; `log` holds each request: (method, path, headers, body). Its api/me knows you by the view-as header when the
    request has one (the switch on), else by your token (extended identity: the token's owner is Domino's /self)."""
    state, log = {}, []

    def log_message(self, *a):
        pass

    def answer(self, status, body=None, headers=()):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        Fake.log.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        s = Fake.state
        if self.path == "/access-token":
            return self.send_token()
        if self.path == "/api/users/v1/self":
            return self.answer(200, {"user": {"userName": s.get("self", "analyst1")}})
        if self.path == "/app/api/me":
            view_as = self.headers.get("X-Prototype-View-As")
            mine = ((200, {"userName": view_as, "viewAsEnabled": True, "source": "prototype view-as switch"}) if view_as
                    else (200, {"userName": s.get("self", "analyst1"), "viewAsEnabled": False, "source": BEARER}))
            return self.answer(*s.get("me", mine))
        if self.command == "GET" and self.path == "/app/api/agents":
            return self.answer(200, s.get("agents", []))
        if self.command == "GET" and self.path == "/app/api/platform/certified-environments":
            return self.answer(*s.get("certified", (200, CERTIFIED)))
        if self.command in ("POST", "PUT") and s.get("refuse"):
            return self.answer(*s["refuse"])
        if self.command == "POST" and self.path == "/app/api/agents":
            return self.answer(200, {**body, "id": "agt_0123456789", "canEdit": True})
        m = re.fullmatch(r"/app/api/agents/(agt_\w+)", self.path)
        if self.command == "PUT" and m:
            return self.answer(200, {**body, "id": m.group(1), "canEdit": True})
        return self.answer(404, {"detail": "Not Found"})

    def send_token(self):
        data = b"Bearer tok-123"
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = handle_any


server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=server.serve_forever, daemon=True).start()
HOST = f"http://127.0.0.1:{server.server_address[1]}"
APP = f"{HOST}/app"


def register(*args, state=None, env=None):
    """Runs the script as a Workspace would, without site-packages (-S: the stdlib only), against the fake App.
    -> (exit code, stdout, stderr, the App's log)"""
    Fake.state, Fake.log[:] = state or {}, []
    e = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "DOMINO_API_PROXY": HOST, "DOMINO_API_HOST": HOST,
         "DOMINO_STARTING_USERNAME": "analyst1", **(env or {})}
    e = {k: v for k, v in e.items() if v is not None}
    r = subprocess.run([sys.executable, "-S", str(ROOT / "agent" / "register.py"), *args], env=e, capture_output=True, text=True,
                       timeout=60)
    return r.returncode, r.stdout, r.stderr, list(Fake.log)


CLIENT_TOOLS = ["aml_close_alert", "aml_escalate_to_sar"]
VARIANTS = {   # --framework: the agent's name (the wizard's label for the framework as its suffix) and its framework block
    "langgraph": ("AML alert triage",
                  {"name": "langgraph", "entrypoint": "agent/graph.py:build_graph", "clientTools": CLIENT_TOOLS}),
    "crewai": ("AML alert triage (CrewAI)",
               {"name": "crewai", "entrypoint": "agent/flow.py:build_flow", "clientTools": CLIENT_TOOLS}),
    "domino-agui": ("AML alert triage (Domino AG-UI SDK)",
                    {"name": "domino-agui", "entrypoint": "agent/handler.py:handler", "clientTools": CLIENT_TOOLS}),
}


def body_with(**changes):
    """The definition file with the variant, the people and the overrides the script must add (expected values, written out here)."""
    b = json.loads(DEFINITION.read_text())
    b["name"], b["framework"] = VARIANTS[changes.get("framework", "langgraph")]
    b["access"] = {"mode": "restricted", "users": changes.get("users", ["analyst1"]), "editors": changes.get("editors", ["reviewer1"])}
    if "model" in changes:
        b["model"] = {**b["model"], "models": [changes["model"]]}
    b["execution"] = {**b["execution"],
                      "environment": {"id": changes.get("environment", CERTIFIED_ID[changes.get("framework", "langgraph")])}}
    return b


def shown_environment(body):
    """The Environment ID in a printed body ("" when it has none)."""
    return str((((body or {}).get("execution") or {}).get("environment") or {}).get("id", ""))


def parsed(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------------------------- print mode
code, out, err, log = register("--print", "--reviewer", "reviewer1", "--app", APP)
shown = shown_environment(parsed(out))
check("--print shows the definition with you (the analyst) in its users list and the reviewer in its editors list",
      code == 0 and parsed(out) == body_with(environment=shown), (code, out[:300], err[:300]))
check("--print calls nothing, not even with --app", log == [], log)
for fw in ("langgraph", "crewai", "domino-agui"):
    code, out, err, log = register("--print", "--framework", fw, "--reviewer", "reviewer1", "--app", APP)
    shown = shown_environment(parsed(out))
    check(f"--print --framework {fw} without --environment: the Environment is a placeholder that names {fw} and "
          "GET api/platform/certified-environments (not an ID), and it calls nothing",
          code == 0 and "GET api/platform/certified-environments" in shown and fw in shown
          and not re.fullmatch(r"[0-9a-f]{24}", shown) and log == [], (code, shown, err[:300], log))
code, out, err, log = register("--print", "--reviewer", "reviewer1", "--model", "haiku", "--environment", "6ae2ffffffffffffffffffff")
check("--print shows the model alias and Environment overrides, and keeps the rest of the model and execution",
      code == 0 and parsed(out) == body_with(model="haiku", environment="6ae2ffffffffffffffffffff"), (code, out[:300], err[:300]))
code, out, err, log = register("--print", "--reviewer", "analyst1")
check("the reviewer can't be you (maker-checker needs a second person): it stops before any call",
      code != 0 and "reviewer" in err.lower() and not log and not out, (code, out[:200], err[:300]))
code, out, err, log = register("--print", "--reviewer", "reviewer1", "--reviewer", "reviewer2")
check("--reviewer given twice: --print shows both reviewers in its editors list, in the order given",
      code == 0 and parsed(out) == body_with(editors=["reviewer1", "reviewer2"], environment=shown_environment(parsed(out))),
      (code, out[:300], err[:300]))
code, out, err, log = register("--print", "--reviewer", "reviewer1", "--reviewer", "reviewer2", "--reviewer", " reviewer1 ")
check("...a reviewer named twice is in the editors list once",
      code == 0 and parsed(out) == body_with(editors=["reviewer1", "reviewer2"], environment=shown_environment(parsed(out))),
      (code, out[:300], err[:300]))
code, out, err, log = register("--print", "--reviewer", "reviewer1", "--reviewer", "analyst1")
check("...no reviewer can be you, even with others: it stops before any call, and names you",
      code != 0 and "analyst1" in err and not log and not out, (code, out[:200], err[:300]))
code, out, err, log = register("--print", "--reviewer", "reviewer1", "--reviewer", " ")
check("...an empty --reviewer stops it", code != 0 and "empty" in err and not log and not out, (code, out[:200], err[:300]))
for fw in ("crewai", "domino-agui", "langgraph"):
    code, out, err, log = register("--print", "--framework", fw, "--reviewer", "reviewer1", "--environment", "6ae2ffffffffffffffffffff",
                                   "--app", APP)
    check(f"--print --framework {fw}: the name {VARIANTS[fw][0]!r}, the framework {fw} at {VARIANTS[fw][1]['entrypoint']} with the "
          "same client-side tools, and the rest of the definition as it is; it calls nothing",
          code == 0 and parsed(out) == body_with(framework=fw, environment="6ae2ffffffffffffffffffff") and log == [],
          (code, out[:300], err[:300], log))
code, out, err, log = register("--print", "--framework", "smolagents", "--reviewer", "reviewer1")
check("--framework takes langgraph, crewai or domino-agui only: another one stops it (exit 2) before any call",
      code == 2 and "--framework" in err and not log and not out, (code, out[:200], err[:300]))
code, out, err, log = register("--print")
check("the reviewer's name is required", code != 0 and "--reviewer" in err and not log, (code, err[:300]))
code, out, err, log = register("--reviewer", "reviewer1")
check("without --print, the App's URL is required", code != 0 and "--app" in err and not log, (code, err[:300]))


# ------------------------------------------------------------------------------------------------------------------- the App's calls
def app_calls(log):
    return [(m, p) for m, p, _, _ in log if p.startswith("/app/")]


def writes(log):
    return [(m, p, b) for m, p, _, b in log if m in ("POST", "PUT")]


NAME = json.loads(DEFINITION.read_text())["name"]
CREATE = [("GET", "/app/api/me"), ("GET", "/app/api/platform/certified-environments"), ("GET", "/app/api/agents"),
          ("POST", "/app/api/agents")]
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1")
check("with no agent of its name, it creates one: GET api/me, GET api/platform/certified-environments, GET api/agents, then "
      "POST api/agents", code == 0 and app_calls(log) == CREATE, (code, app_calls(log), err[:300]))
check("...with the whole agent body (you, the analyst, in its users list, the reviewer in its editors list)",
      writes(log) == [("POST", "/app/api/agents", body_with())], writes(log))
check("...on the certified LangGraph Environment: of the two listed for langgraph, the last one",
      shown_environment((writes(log) or [(0, 0, {})])[0][2]) == "6ae2bbbbbbbbbbbbbbbbbbbb", writes(log)[:1])
check("...and it prints the Environment it took, with its name", "6ae2bbbbbbbbbbbbbbbbbbbb" in out and "agent-langgraph (second)" in out,
      out)
check("...each call with the Workspace's token and no view-as header (the App has extended identity: it takes your token)",
      all(h.get("authorization") == "Bearer tok-123" and "x-prototype-view-as" not in h for _, p, h, _ in log if p.startswith("/app/")),
      [(p, h.get("authorization"), h.get("x-prototype-view-as")) for _, p, h, _ in log])
check("...and it prints the agent's ID and page URL", "agt_0123456789" in out and f"{APP}/#/agents/agt_0123456789" in out, out)
check("...and how the App knows you (by your token)", BEARER in out, out)

code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", "--view-as")
check("--view-as (an App without extended identity): the same calls and body, each with the Workspace's token and your name in the "
      "view-as header",
      code == 0 and app_calls(log) == CREATE and writes(log) == [("POST", "/app/api/agents", body_with())]
      and all(h.get("authorization") == "Bearer tok-123" and h.get("x-prototype-view-as") == "analyst1"
              for _, p, h, _ in log if p.startswith("/app/")),
      (code, app_calls(log), [(p, h.get("x-prototype-view-as")) for _, p, h, _ in log], err[:300]))
check("...and how the App knows you (the live check records it: the view-as switch)", "prototype view-as switch" in out, out)

code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", "--reviewer", "reviewer2")
check("with two reviewers, it sends both in the agent's editors list, and prints both names",
      code == 0 and writes(log) == [("POST", "/app/api/agents", body_with(editors=["reviewer1", "reviewer2"]))]
      and "reviewer1, reviewer2 as its editors" in out, (code, writes(log), out[:300], err[:300]))

for fw in ("crewai", "domino-agui"):
    code, out, err, log = register("--app", APP, "--framework", fw, "--reviewer", "reviewer1")
    check(f"--framework {fw}: it creates the agent {VARIANTS[fw][0]!r} with the {fw} framework block, its entry point, and the "
          f"Environment certified for {fw} ({CERTIFIED_ID[fw]})",
          code == 0 and app_calls(log) == CREATE and writes(log) == [("POST", "/app/api/agents", body_with(framework=fw))],
          (code, app_calls(log), writes(log), err[:300]))
check("...an Environment that Domino gives no name: it prints the ID", CERTIFIED_ID["domino-agui"] in out, out)

no_crewai = (200, [c for c in CERTIFIED if c["framework"] != "crewai"])
code, out, err, log = register("--app", APP, "--framework", "crewai", "--reviewer", "reviewer1", state={"certified": no_crewai})
check("no certified Environment for the framework: it stops, says so, prints the endpoint's answer, and writes nothing",
      code == 1 and "crewai" in err and "6ae2bbbbbbbbbbbbbbbbbbbb" in err and "agent-langgraph (second)" in err and not writes(log),
      (code, err[:600], writes(log)))
code, out, err, log = register("--app", APP, "--framework", "crewai", "--reviewer", "reviewer1", state={"certified": (200, [])})
check("...an empty list: it stops the same way, and shows the empty answer",
      code == 1 and "crewai" in err and "[]" in err and not writes(log), (code, err[:600], writes(log)))
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", state={"certified": (404, {"detail": "Not Found"})})
check("the App doesn't answer GET api/platform/certified-environments (404): it stops with the App's reason, and writes nothing",
      code == 1 and "certified-environments" in err and "404" in err and not writes(log), (code, err[:600], writes(log)))

agents = [{"id": "agt_00000000aa", "name": NAME, "canEdit": True}, {"id": "agt_00000000bb", "name": "Another agent", "canEdit": True}]
code, out, err, log = register("--app", APP + "/#/agents", "--reviewer", "reviewer1", "--model", "haiku", state={"agents": agents})
check("with an agent of its name, it updates that one: PUT api/agents/<id> with the whole body, and no POST",
      code == 0 and writes(log) == [("PUT", "/app/api/agents/agt_00000000aa", body_with(model="haiku"))], (code, writes(log), err[:300]))
check("...and it prints that agent's ID and page URL (an App URL copied from the browser works too)",
      f"{APP}/#/agents/agt_00000000aa" in out, out)

DOMINO_401 = (401, {"detail": "Domino didn't accept that token. Send a current JWT or PAT as Authorization: Bearer <token>, "
                              "or an API key as X-Domino-Api-Key."})
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", state={"me": DOMINO_401})
check("the App without extended identity (Domino refuses the changed token: 401): it stops, says to publish the App with extended "
      "identity or use --view-as, and sends nothing more",
      code == 1 and "extended identity" in err and "--view-as" in err and app_calls(log) == [("GET", "/app/api/me")],
      (code, err[:400], app_calls(log)))
other = {"me": (200, {"userName": "publisher", "viewAsEnabled": False, "source": "domino-username header (app)"})}
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", state=other)
check("the App sees you as someone else: it stops, names who, and writes nothing",
      code == 1 and "publisher" in err and not writes(log), (code, err[:400], app_calls(log)))
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", "--view-as", state={"me": DOMINO_401})
check("--view-as, the switch off (the App checks the changed token: 401): it stops, says to set SMOKE_ALLOW_VIEW_AS=1, and sends "
      "nothing more",
      code == 1 and "SMOKE_ALLOW_VIEW_AS=1" in err and app_calls(log) == [("GET", "/app/api/me")], (code, err[:400], app_calls(log)))
off = {"me": (200, {"userName": "analyst1", "viewAsEnabled": False, "source": BEARER})}
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", "--view-as", state=off)
check("--view-as, the switch off (api/me says viewAsEnabled false): it stops the same way",
      code == 1 and "SMOKE_ALLOW_VIEW_AS=1" in err and app_calls(log) == [("GET", "/app/api/me")], (code, err[:400], app_calls(log)))
dropped = {"me": (200, {"userName": "publisher", "viewAsEnabled": True, "source": "domino-username header (app)"})}
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", "--view-as", state=dropped)
check("--view-as, the App didn't take the view-as header: it stops, names the header, and writes nothing",
      code == 1 and "X-Prototype-View-As" in err and not writes(log), (code, err[:400], app_calls(log)))
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1",
                               state={"me": (302, None, [("Location", "https://apps.example/login?next=app")])})
check("a redirect (the Apps proxy's sign-in or consent page): it stops, says to open the App once, and writes nothing",
      code == 1 and "open the app once" in err.lower() and not writes(log), (code, err[:400], app_calls(log)))

TOOL_LIST = "toolServers names aml, which isn't in the tool server list. The tool servers are: acme."
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", state={"refuse": (400, {"detail": TOOL_LIST})})
check("a refused request: it stops with the App's reason, and prints no agent", code == 1 and TOOL_LIST in err and "agt_" not in out,
      (code, out[:200], err[:400]))
check("...and says what to do for a known reason (add the tool server aml first)", "Tool servers page" in err, err[:400])

two = [{"id": "agt_00000000aa", "name": NAME, "canEdit": True}, {"id": "agt_00000000cc", "name": NAME, "canEdit": True}]
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", state={"agents": two})
check("two agents of its name: it stops, names both, and writes nothing",
      code == 1 and "agt_00000000aa" in err and "agt_00000000cc" in err and not writes(log), (code, err[:400], writes(log)))
theirs = [{"id": "agt_00000000dd", "name": NAME, "canEdit": False, "owner": {"userName": "someone"}}]
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", state={"agents": theirs})
check("an agent of its name that you can't change: it stops, names its owner, and writes nothing",
      code == 1 and "someone" in err and not writes(log), (code, err[:400], writes(log)))

code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", state={"self": "analyst2"},
                               env={"DOMINO_STARTING_USERNAME": None})
self_calls = [h.get("authorization") for m, p, h, _ in log if p == "/api/users/v1/self"]
check("without DOMINO_STARTING_USERNAME, your name comes from Domino (GET /api/users/v1/self with the Workspace's token)",
      code == 0 and self_calls == ["Bearer tok-123"] and writes(log) == [("POST", "/app/api/agents", body_with(users=["analyst2"]))]
      and all("x-prototype-view-as" not in h for _, p, h, _ in log if p.startswith("/app/")),
      (code, self_calls, err[:300]))

print(f"\n{len(failed)} failed: {', '.join(failed)}" if failed else "\nall checks passed")
sys.exit(1 if failed else 0)
