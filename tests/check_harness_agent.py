"""The harness agent (harness/): the AML triage as an agent folder for the harness lane (domino-agent-service spec #220, ADR 0037),
seen from outside: its instructions as the agent reads them, the author's `domino-agent deploy --dry-run`, and the agent that a local
agent service registers from it, with a Job's spec.

With no service, it checks the folder's files and the AML rules in its instructions, as check_registration.py checks the framework
agent's prompt. The rules that don't depend on the lane are the framework agent's own lines (agent/definition.json), with the names that
a harness agent gives the case-management tools: domino_aml_<tool>. The spec's opencode config shows why: the federated tools come
through one MCP server, `domino`.

With the service (AGENT_SERVICE_REPO, the path of a domino-agent-service checkout with the agent folder; Linux only, as the service's
app needs it), it starts that service over real HTTP with a fake Domino (the service's seam helper, tests/agent_folder_seam.py), with
the folder committed in a temporary clone at harness/:
  - `domino-agent deploy --dry-run harness` is refused while `aml` isn't on the tool server list, then passes, and registers nothing.
  - `domino-agent deploy harness` registers the agent: the tool server aml, the requester as the acting identity, the instructions,
    and the framework agent's other settings where both lanes have them.
  - A task of it starts a Domino Job as the analyst. The Job's spec has the session's tools route (only an agent with a tool server gets
    one) and the instructions, at the top of the agent's rules.
With AGENT_SERVICE_REPO unset, or not on Linux, those parts print a SKIP line. No Domino host: the live run is domino-agent-service
#246.

  python tests/check_harness_agent.py                                                    # the files only
  AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_harness_agent.py   # on Linux: everything (README: the check)
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "harness"
DEFINITION = ROOT / "agent" / "definition.json"
SEED = ROOT / "case_server" / "seed.json"
REMOTE = "https://github.com/ddl-subir-m/aml-alert-triage.git"
ANALYST = "olivia"   # a person the seam's fake Domino knows: she deploys the folder (its owner) and starts the task
TITLE = "AML alert triage (harness)"
failed = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{str(detail)[:600]}]" if detail and not ok else ""), flush=True)
    if not ok:
        failed.append(name)


def done(skip=None):
    if skip:
        print(f"SKIP: {skip}", flush=True)
    sys.exit(1 if failed else 0)


def text(path):
    try:
        return path.read_text()
    except OSError as e:
        return f"<{e}>"


# --------------------------------------------------------------------------------------------------------------------- the files
files = {p.relative_to(FOLDER).as_posix(): p.read_text() for p in sorted(FOLDER.rglob("*")) if p.is_file()} if FOLDER.is_dir() else {}
cases = sorted(f for f in files if f.startswith("evals/"))   # the eval cases: `deploy` never sends a file of evals/
check("harness/ holds definition.md, instructions.md and the eval cases in evals/, and nothing else (deploy uploads only an agent "
      "folder's known paths)", sorted(f for f in files if f not in cases) == ["definition.md", "instructions.md"], sorted(files))
seeded = [x["alert_id"] for x in json.loads(text(SEED)).get("alerts") or []] if SEED.is_file() else []
check("evals/ has one eval case for each alert of the seed, and each case's first message triages its alert",
      len(cases) == len(seeded) > 0 and all(c.endswith(".yaml") and c.count("/") == 1 for c in cases)
      and sorted(re.findall(r"^  - Triage alert (A-\d+)\.$", "\n".join(files[c] for c in cases), re.M)) == sorted(seeded),
      (cases, seeded))
check("the eval case that writes says so, and names the reset of the case server",
      sum("POST /reset" in files[c] for c in cases) == 1 and all("domino_aml_close_alert" in files[c] for c in cases), cases)
instructions = files.get("instructions.md", "")
settings = files.get("definition.md", "")
check("definition.md holds only the settings, between its two --- lines: the instructions are instructions.md",
      settings.startswith("---\n") and settings.rstrip().endswith("\n---") and settings.count("\n---") == 1, settings[-200:])
check("definition.md turns on the three kinds of memory: personal, agent and task",
      re.search(r"^memory:[^\n]*\n  personal: true[^\n]*\n  agent: true[^\n]*\n  task: true", settings, re.M) is not None, settings[-600:])

# ----------------------------------------------------------------------------------------------------- the AML rules in instructions
lines = [ln.lower() for ln in instructions.splitlines()]


def rule(name, *words):
    """One line of the instructions says the rule: it holds every one of `words` (case aside)."""
    check(f"the instructions say: {name}", any(all(w.lower() in ln for w in words) for ln in lines), words)


rule("read the alert first", "domino_aml_get_alert", "first")
rule("a closed or escalated alert gets a report and no write", "closed or escalated", "write nothing", "report")
rule("read the profile and the transactions before any decision", "domino_aml_get_customer_profile", "domino_aml_get_transactions",
     "before", "decide")
rule("close only with a reason code and a rationale", "domino_aml_close_alert", "only with a reason code", "rationale")
rule("the reason codes", "false_positive", "explained_activity", "duplicate")
rule("escalate only with a narrative and the supporting transaction IDs", "domino_aml_escalate_to_sar", "only with a narrative",
     "transaction ids", "support")
rule("ask the analyst when the evidence is unclear", "unclear", "ask the analyst", "domino_ask_user")
rule("...unclear means one transaction that doesn't fit the profile and no pattern: ask what it is for before escalating",
     "unclear when", "no pattern", "ask what the transaction is for before you escalate")
rule("when the evidence is clear, close or escalate without asking the analyst first", "evidence is clear", "don't ask the analyst first",
     "close", "escalate")
rule("an escalation waits for a reviewer, so the run ends", "domino_aml_escalate_to_sar", "reviewer must approve", "end your turn")
rule("a question ends the turn, and the answer comes in a new run", "domino_ask_user", "end your turn", "new run")
rule("after a denied escalation, report the denial and who denied it", "denies", "report the denial", "who denied it")
rule("...and make no other write", "denies", "no other write")
rule("the summary goes to domino_report_result, once, last", "domino_report_result", "once", "last")
rule("notes of the work go to task memory before a question or the end of a round", "task memory", "before you ask the analyst",
     "before you end a round")
rule("a fact for everybody is a memory proposal, which an owner or an editor accepts", "agent memory", "memory proposal",
     "an owner or an editor", "accept")
rule("a wish of the analyst about the writing goes to personal memory, and the summary keeps its parts", "personal memory", "wish",
     "four parts")
heads = ["**Decision**", "**Rationale**", "**Evidence**", "**Action taken**"]
at = [instructions.find(h) for h in heads]
check("the instructions end the task with the summary: Decision, Rationale, Evidence, Action taken, in that order",
      all(i >= 0 for i in at) and at == sorted(at) and instructions.rstrip().splitlines()[-1].startswith("**Action taken**"),
      dict(zip(heads, at)))
rule("the summary is domino_report_result's", "end with domino_report_result", "summary")
rule("an answer with a SAR case ID means that a reviewer approved the escalation and it ran", "sar case id", "reviewer approved")
rule("...so Action taken never says that an escalation that ran still waits for approval", "**action taken**", "no longer waits")
named = set(re.findall(r"\bdomino_[a-z_]+", instructions))
check("the instructions name the five case-management tools, the question and the result, and no other Domino tool",
      named == {"domino_aml_get_alert", "domino_aml_get_customer_profile", "domino_aml_get_transactions", "domino_aml_close_alert",
                "domino_aml_escalate_to_sar", "domino_ask_user", "domino_report_result"}, named)
bare = re.findall(r"(?<![a-z_])aml_[a-z_]+|\bask_human\b", instructions)
check("they name no tool as a framework agent sees it (aml_<tool>, ask_human): a harness agent has none of those names", not bare, bare)

framework = json.loads(text(DEFINITION) if DEFINITION.is_file() else "{}").get("systemPrompt") or ""
SHARED = ("- aml_get_alert(", "- aml_get_customer_profile(", "- aml_get_transactions(", "- aml_close_alert(", "1. ", "2. ", "3. ", "4. ",
          "5. ", "8. ", "**Decision**", "**Rationale**", "**Evidence**", "**Action taken**")
shared = [re.sub(r"(?<![a-z_])aml_", "domino_aml_", ln) for ln in framework.splitlines() if ln.startswith(SHARED)]
missing = [ln for ln in shared if ln not in instructions.splitlines()]
check("the lines that don't depend on the lane (the read and close tools, rules 1 to 5 and 8, the summary) are the framework agent's, "
      "with the tools' harness names", len(shared) == len(SHARED) and not missing, missing or len(shared))

# --------------------------------------------------------------------------------------------------- the service: deploy and a Job
service = os.environ.get("AGENT_SERVICE_REPO", "").strip()
if not service:
    done("AGENT_SERVICE_REPO is not set, so the deploy and the Job's spec weren't checked. Set it to a domino-agent-service checkout "
         "with the agent folder, on Linux (README, \"The harness agent\")")
service = Path(service).expanduser().resolve()
if not (service / "tests" / "agent_folder_seam.py").is_file() or not (service / "domino_agent" / "deploy.py").is_file():
    check(f"AGENT_SERVICE_REPO ({service}) is a domino-agent-service checkout with the agent folder "
          "(tests/agent_folder_seam.py and domino_agent/)", False)
    done()
if not files:
    done()   # the first part said why: there is no folder to deploy
if not sys.platform.startswith("linux"):
    done("needs Linux for the deploy and the Job's spec: the service's app imports agent_runtime/sandbox.py. On a Mac, run it with "
         "Docker, in the image of the service's checks (README, \"The harness agent\")")
sys.path.insert(0, str(service / "tests"))
import agent_folder_seam as seam  # noqa: E402  (the service's seam helper, from AGENT_SERVICE_REPO)

seam.PROJECT["name"] = "aml-alert-triage"   # definition.md's `project`: the agent runs only in the project of this name
_fake_get = seam._fake_get


def _named(path, *args, **kw):
    """The seam's fake Domino, with its one project under the name that definition.md names."""
    out = _fake_get(path, *args, **kw)
    return json.loads(json.dumps(out).replace('"local-proj"', '"aml-alert-triage"')) if path.startswith("/api/projects/") else out


seam._fake_get = _named   # before the service starts: the seam reads its fake Domino when it starts
seam.start()
repo = seam.Repo(files, path="harness", remote=REMOTE)


def registered():
    """The agent that the folder's `name` registered, as the analyst sees it, or None."""
    agents = seam.api("GET", "/api/agents", ANALYST).json()
    return next((a for a in agents if (a.get("registration") or {}).get("name") == "aml-alert-triage"), None)


# The author's side: the dry run checks the folder on the laptop, then the service checks what only the deployment knows.
ran = seam.command("deploy", "--dry-run", "harness", cwd=repo.root, person=ANALYST)
check("deploy --dry-run is refused while aml isn't on the tool server list, and says so",
      ran.code == 1 and "aml is not on the tool server list" in ran.out and "Nothing was registered" in ran.out, ran)
seam.add_tool_server("aml", ("get_alert", "get_customer_profile", "get_transactions", "close_alert", "escalate_to_sar"))
ran = seam.command("deploy", "--dry-run", "harness", cwd=repo.root, person=ANALYST)
check("deploy --dry-run passes with aml on the list: it would create the agent, and registers nothing",
      ran.code == 0 and f"Dry run: would create {TITLE}" in ran.out and "Dry run: nothing was registered." in ran.out
      and registered() is None, ran)

ran = seam.command("deploy", "harness", cwd=repo.root, person=ANALYST)
check("deploy registers it: a new agent", ran.code == 0 and ran.out.startswith(f"Created {TITLE} (agt_"), ran)
a = registered() or {}
check("the agent is a harness agent with the folder's title, owned by the analyst who deployed it",
      a.get("lane") == "harness" and a.get("name") == TITLE and (a.get("owner") or {}).get("userName") == ANALYST,
      (a.get("lane"), a.get("name"), a.get("owner")))
rec = a.get("registration") or {}
check("its Registration names the AML repo, the folder's path, the commit, and a clean folder",
      rec.get("repo") == REMOTE and rec.get("path") == "harness" and rec.get("commit") == repo.head and rec.get("clean") is True
      and rec.get("how") == "deploy" and rec.get("by") == ANALYST, rec)
check("its tool server is the case-management system, aml, with every tool", a.get("toolServers") == [{"server": "aml"}],
      a.get("toolServers"))
check("it acts as the requester: the analyst who starts the task (triggering_user)", a.get("identity") == {"mode": "triggering_user"},
      a.get("identity"))
check("its system prompt is instructions.md", a.get("systemPrompt") == instructions.strip(), (a.get("systemPrompt") or "")[:200])

fw = json.loads(text(DEFINITION) if DEFINITION.is_file() else "{}")


def pick(d, *keys):
    return {k: (d or {}).get(k) for k in keys}


LIMITS, ACCESS = ("maxRuntimeMin", "maxTurns", "idleWaitMin"), ("project", "data", "named", "other")
same = {   # where both lanes have a setting: the framework agent's value (agent/definition.json), and the registered agent's
    "the model": (fw.get("model"), a.get("model")),
    "the acting identity": (fw.get("identity"), a.get("identity")),
    "the tool servers": (fw.get("toolServers"), a.get("toolServers")),
    "the inputs": (fw.get("inputs"), [pick(i, "name", "type", "required") for i in a.get("inputs") or []]),
    "the access": ((fw.get("guardrails") or {}).get("access"), pick((a.get("guardrails") or {}).get("access"), *ACCESS)),
    "the limits": (pick(fw.get("execution"), *LIMITS), pick(a.get("execution"), *LIMITS)),
    "the error recovery": (fw.get("onError"), a.get("onError")),
}
for what, (want, got) in same.items():
    check(f"{what}: the framework agent's", want is not None and want == got, {"framework": want, "harness": got})
tools = (a.get("guardrails") or {}).get("tools") or {}
check("it has no shell, web, subagent, Jobs or push tool: only the case-management tools and the relay's",
      tools and not any(tools.get(k) for k in ("bash", "web", "subagents", "jobs", "push")), tools)
alerts = [x["alert_id"] for x in json.loads(text(SEED)).get("alerts") or []] if SEED.is_file() else []
check("its starter prompts triage each alert of the seed", alerts and (a.get("directTrigger") or {}).get("starterPrompts")
      == [f"Triage alert {x}." for x in alerts], ((a.get("directTrigger") or {}).get("starterPrompts"), alerts))

# A task: the Job's start and its spec, as the Job's bootstrapper reads it.
n = len(seam.JOBS)
job, spec = seam.spec_of(a.get("id"), ANALYST, instruction="Triage alert A-1001.") if a.get("id") else (None, "no agent")
check("a task in the project aml-alert-triage starts one Domino Job, as the analyst (the requester's credential)",
      job is not None and len(seam.JOBS) == n + 1 and seam.JOBS[-1]["credential"] == ("bearer", seam.PEOPLE[ANALYST])
      and job.get("projectId") == seam.PROJECT["id"], spec if job is None else seam.JOBS[-1]["credential"])
spec = spec if isinstance(spec, dict) else {}
session = spec.get("session") or {}
check("the Job's spec is the harness lane's, for this agent and the task's instruction",
      spec.get("lane") == "harness" and session.get("agentId") == a.get("id") and spec.get("instruction") == "Triage alert A-1001.",
      {k: spec.get(k) for k in ("lane", "session", "instruction")})
check("the Job's spec has its session's tools route, which reaches the agent's tool server aml",
      str(spec.get("toolsRoute") or "").endswith(f"/tools/sessions/{session.get('id')}/mcp") and session.get("id"), spec.get("toolsRoute"))
mcp = (spec.get("opencodeConfig") or {}).get("mcp") or {}
check("opencode gets one MCP server, domino (the relay), so the tool server's tools are domino_aml_<tool>, as the instructions name them",
      list(mcp) == ["domino"], list(mcp))
check("the Job's spec has the instructions, at the top of the agent's rules (then the platform's operating rules)",
      bool(instructions.strip()) and str(spec.get("operatingRules") or "").startswith(instructions.strip() + "\n\n## Operating rules"),
      str(spec.get("operatingRules"))[:300])
check("the Job's limits: 30 minutes, 20 turns, and no wait (a question ends the Job, and the answer starts a new one)",
      spec.get("limits") == {"maxMinutes": 30, "maxTurns": 20, "idleWaitMin": 0}, spec.get("limits"))

seam.close()
done()
