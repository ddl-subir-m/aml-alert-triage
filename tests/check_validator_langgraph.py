"""The LangGraph validator (governance/validator-langgraph/, domino-agent-service spec #260, Implementation Decision 9), seen from
outside: its definition as the wizard makes it, and its event subscription's templates.

  python tests/check_validator_langgraph.py
"""
import json
import re
import runpy
import sys
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

done()
