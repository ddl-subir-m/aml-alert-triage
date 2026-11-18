"""The LangGraph validator of the App validation demo (domino-agent-service spec #260, Implementation Decision 9): a fixed graph. Each
run does the same steps in the same order:

  collect   own tools read the App's code (list_files, read_file, as the probe did); get_bundle, get_policy
  findings  the task's result, streamed as the last text: the verdict, critical vulns and the doc's location

The gateway tools are called from this code through the relay (domino_agui.contract.relay(): a ToolResult with is_error, so a denial
is seen as one), never by the model. The instruction is the event subscription's (subscription.json): the graph reads the bundle ID
from its line "Bundle ID: ...".

The entry point is governance/validator-langgraph/graph.py:build_graph. The definition is agent.json, next to this file. The data is
fake.
"""
import json
import re
import uuid
from pathlib import Path

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from domino_agui import contract
from domino_agui.langgraph import State

ROOT = Path(__file__).resolve().parents[2]   # the project's root: this file is governance/validator-langgraph/graph.py
SKIP = {".git", "__pycache__", ".venv", "node_modules"}
LIMIT = 200
APP = ("app.sh", "case_server")   # the App under validation: its start script and its server
EVIDENCE = "Validation (LangGraph)"   # the evidence item this validator fills, and no other


def list_files(folder: str = ".") -> str:
    """The files under a folder of the project, as paths relative to the project's root, one on each line (at most 200)."""
    base = _inside(folder)
    files = sorted(str(p.relative_to(ROOT)) for p in base.rglob("*")
                   if p.is_file() and not SKIP & set(p.relative_to(ROOT).parts))
    if not files:
        return f"No files under {folder}"
    more = f"\n... and {len(files) - LIMIT} more" if len(files) > LIMIT else ""
    return "\n".join(files[:LIMIT]) + more


def read_file(path: str, max_chars: int = 20000) -> str:
    """The text of one project file, by its path relative to the project's root (at most max_chars characters)."""
    text = _inside(path).read_text(errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... cut at {max_chars} of {len(text)} characters"
    return text


def _inside(path):
    p = (ROOT / path).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise ValueError(f"{path!r} is outside the project folder")
    return p


class Validation(State, total=False):
    """The graph's state: the messages and the bridge's keys (State), and what each step found."""
    bundle_id: str
    bundle: dict      # get_bundle's answer
    evidence: dict    # this validator's evidence item: {"id", "fields": {label: artifact ID}}
    code: dict        # {path: text}: the App's files
    problems: list    # what a step could not do, for the result and the doc
    result: str


def setting(instruction, label):
    """The value of the instruction's line "<label>: <value>", or None (also for a placeholder that the live script didn't fill)."""
    m = re.search(rf"^{re.escape(label)}:[ \t]*(\S.*?)[ \t]*$", instruction or "", re.M)
    value = m.group(1) if m else None
    return None if not value or re.fullmatch(r"__[A-Z_]+__", value) else value


def answer(text):
    """A gateway tool's JSON answer as a dict (a note may follow the JSON: run_job adds one), else None."""
    try:
        got, _ = json.JSONDecoder().raw_decode((text or "").strip())
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


async def call(name, **args):
    """One gateway tool call through the relay. -> (ok, the answer's text). A denial or Domino's error is not ok."""
    got = await contract.relay().call(name, args)
    return not got.is_error, got.text


def instruction_of(state):
    return next((str(m.content) for m in state["messages"] if isinstance(m, HumanMessage)), "")


async def collect(state):
    """The App's code with the own tools, then the bundle and its policy, with this validator's evidence item and its fields."""
    bundle_id = setting(instruction_of(state), "Bundle ID")
    if not bundle_id:
        raise ValueError("The instruction names no bundle: it needs a line \"Bundle ID: <the bundle's ID>\", as the event subscription's "
                         "instruction template has it (governance/validator-langgraph/subscription.json)")
    problems = []
    files = [f for part in APP for f in list_files(part).splitlines() if not f.startswith(("No files", "..."))]
    code = {f: read_file(f) for f in files}
    ok, text = await call("get_bundle", bundleId=bundle_id)
    bundle = answer(text) if ok else None
    if not bundle:
        problems.append(f"get_bundle: {text[:300]}")
    ok, text = await call("get_policy", bundleId=bundle_id)
    policy = answer(text) if ok else None
    if not policy:
        problems.append(f"get_policy: {text[:300]}")
    return {"bundle_id": bundle_id, "bundle": bundle or {}, "code": code, "problems": problems, "evidence": evidence_item(policy)}


def evidence_item(policy):
    """This validator's evidence item in the policy (get_policy's answer), found by its name, with each field's artifact ID by its label
    (the policy file sets no IDs: Domino gives them). {} when the policy has none."""
    for stage in (policy or {}).get("stages") or []:
        for item in stage.get("evidenceSet") or []:
            if item.get("name") == EVIDENCE:
                return {"id": item.get("id"), "fields": {(a.get("details") or {}).get("label"): a.get("id")
                                                         for a in item.get("artifacts") or [] if a.get("id")}}
    return {}


async def findings(state, config):
    """The task's result, streamed as the run's last text (the task's result is the run's last text: a message in the state is not
    sent)."""
    result = f"Validated bundle {state['bundle_id']}."
    message_id = f"msg-{uuid.uuid4().hex[:16]}"
    await adispatch_custom_event("manually_emit_message", {"message_id": message_id, "message": result}, config=config)
    return {"result": result, "messages": [AIMessage(result, id=message_id)]}


def build_graph(checkpointer):
    """The compiled graph, with the checkpointer that the platform's adapter gives (the thread lives in the state folder)."""
    g = StateGraph(Validation)
    g.add_node("collect", collect)
    g.add_node("findings", findings)
    g.add_edge(START, "collect")
    g.add_edge("collect", "findings")
    g.add_edge("findings", END)
    return g.compile(checkpointer=checkpointer)
