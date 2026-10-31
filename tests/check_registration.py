"""The agent's definition (agent/definition.json) and its registration script (agent/register.py), seen from outside: the file as the
platform App receives it, the script's print mode, and the script's calls to a small fake App. No Domino host: the fake App on
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
check("it runs as a Job on the cloud-dogfood certified LangGraph Environment",
      ex.get("runtime") == "job" and ex.get("environment") == {"id": "6ae24cb24abd2d2682011252"}, ex)
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


# ------------------------------------------------------------------------------------------------------------------- the fake App
class Fake(BaseHTTPRequestHandler):
    """The platform App behind its Apps path /app, the Workspace's token at /access-token, and Domino's /api/users/v1/self. `state` says
    how the App answers; `log` holds each request: (method, path, headers, body)."""
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
            return self.answer(*s.get("me", (200, {"userName": self.headers.get("X-Prototype-View-As"), "viewAsEnabled": True,
                                                  "source": "prototype view-as switch"})))
        if self.command == "GET" and self.path == "/app/api/agents":
            return self.answer(200, s.get("agents", []))
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


def body_with(**changes):
    """The definition file with the people and the overrides the script must add (expected values, written out here)."""
    b = json.loads(DEFINITION.read_text())
    b["access"] = {"mode": "restricted", "users": changes.get("users", ["analyst1"]), "editors": changes.get("editors", ["reviewer1"])}
    if "model" in changes:
        b["model"] = {**b["model"], "models": [changes["model"]]}
    if "environment" in changes:
        b["execution"] = {**b["execution"], "environment": {"id": changes["environment"]}}
    return b


def parsed(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------------------------- print mode
code, out, err, log = register("--print", "--reviewer", "reviewer1", "--app", APP)
check("--print shows the definition with you (the analyst) in its users list and the reviewer in its editors list",
      code == 0 and parsed(out) == body_with(), (code, out[:300], err[:300]))
check("--print calls nothing, not even with --app", log == [], log)
code, out, err, log = register("--print", "--reviewer", "reviewer1", "--model", "haiku", "--environment", "6ae2ffffffffffffffffffff")
check("--print shows the model alias and Environment overrides, and keeps the rest of the model and execution",
      code == 0 and parsed(out) == body_with(model="haiku", environment="6ae2ffffffffffffffffffff"), (code, out[:300], err[:300]))
code, out, err, log = register("--print", "--reviewer", "analyst1")
check("the reviewer can't be you (maker-checker needs a second person): it stops before any call",
      code != 0 and "reviewer" in err.lower() and not log and not out, (code, out[:200], err[:300]))
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
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1")
check("with no agent of its name, it creates one: GET api/me, GET api/agents, then POST api/agents",
      code == 0 and app_calls(log) == [("GET", "/app/api/me"), ("GET", "/app/api/agents"), ("POST", "/app/api/agents")],
      (code, app_calls(log), err[:300]))
check("...with the whole agent body (you, the analyst, in its users list, the reviewer in its editors list)",
      writes(log) == [("POST", "/app/api/agents", body_with())], writes(log))
check("...each call with the Workspace's token for the Apps proxy and your name in the view-as header",
      all(h.get("authorization") == "Bearer tok-123" and h.get("x-prototype-view-as") == "analyst1"
          for _, p, h, _ in log if p.startswith("/app/")), [(p, h.get("authorization"), h.get("x-prototype-view-as")) for _, p, h, _ in log])
check("...and it prints the agent's ID and page URL", "agt_0123456789" in out and f"{APP}/#/agents/agt_0123456789" in out, out)
check("...and how the App knows you (the live check records it: the view-as switch)", "prototype view-as switch" in out, out)

agents = [{"id": "agt_00000000aa", "name": NAME, "canEdit": True}, {"id": "agt_00000000bb", "name": "Another agent", "canEdit": True}]
code, out, err, log = register("--app", APP + "/#/agents", "--reviewer", "reviewer1", "--model", "haiku", state={"agents": agents})
check("with an agent of its name, it updates that one: PUT api/agents/<id> with the whole body, and no POST",
      code == 0 and writes(log) == [("PUT", "/app/api/agents/agt_00000000aa", body_with(model="haiku"))], (code, writes(log), err[:300]))
check("...and it prints that agent's ID and page URL (an App URL copied from the browser works too)",
      f"{APP}/#/agents/agt_00000000aa" in out, out)

DOMINO_401 = (401, {"detail": "Domino didn't accept that token. Send a current JWT or PAT as Authorization: Bearer <token>, "
                              "or an API key as X-Domino-Api-Key."})
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", state={"me": DOMINO_401})
check("view-as switch off (the App checks the changed token: 401): it stops, says to set SMOKE_ALLOW_VIEW_AS=1, and sends nothing more",
      code == 1 and "SMOKE_ALLOW_VIEW_AS=1" in err and app_calls(log) == [("GET", "/app/api/me")], (code, err[:400], app_calls(log)))
off = {"me": (200, {"userName": "analyst1", "viewAsEnabled": False, "source": "Authorization bearer (JWT or PAT, verified with Domino)"})}
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", state=off)
check("view-as switch off (api/me says viewAsEnabled false): it stops the same way",
      code == 1 and "SMOKE_ALLOW_VIEW_AS=1" in err and app_calls(log) == [("GET", "/app/api/me")], (code, err[:400], app_calls(log)))
dropped = {"me": (200, {"userName": "publisher", "viewAsEnabled": True, "source": "domino-username header (app)"})}
code, out, err, log = register("--app", APP, "--reviewer", "reviewer1", state=dropped)
check("the App didn't take the view-as header: it stops, names the header, and writes nothing",
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
      and all(h.get("x-prototype-view-as") == "analyst2" for _, p, h, _ in log if p.startswith("/app/")),
      (code, self_calls, err[:300]))

print(f"\n{len(failed)} failed: {', '.join(failed)}" if failed else "\nall checks passed")
sys.exit(1 if failed else 0)
