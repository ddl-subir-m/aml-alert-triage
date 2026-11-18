"""The LangGraph validator of the App validation demo (domino-agent-service spec #260, Implementation Decision 9): a fixed graph. Each
run does the same steps in the same order:

  collect   own tools read the App's code (list_files, read_file, as the probe did); get_bundle, get_policy
  scan      run_job with the shared scan (governance/scan.py), wait_job until the Job is done, get_job_logs: the scan's summary
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
SCAN = "python governance/scan.py"   # the shared scan, as both validators run it (governance/README.md)
SUMMARY = ("== scan summary ==", "== end of scan summary ==")   # its summary's markers: Domino adds lines after it, so not the last line
WAITS = 30   # wait_job calls before the graph stops waiting for the scan: each one waits up to 45 s, so about 20 minutes


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
    scan: dict        # {"ok", "jobId", "number", "status", "summary", "why"}: the scan Job and its summary
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


async def scan(state):
    """The shared scan in a Domino Job: run_job, then wait_job until the Job is done, then get_job_logs for its summary. The scan ran
    only when the Job succeeded and its summary says that both tools ran."""
    ok, text = await call("run_job", command=SCAN, title="App validation scan (LangGraph)")
    job_id = ((answer(text) or {}).get("job") or {}).get("id") if ok else None
    if not job_id:
        return {"scan": {"ok": False, "why": f"the scan Job didn't start: {text[:300]}"}}
    done = None
    for _ in range(WAITS):
        ok, text = await call("wait_job", jobId=job_id)
        done = re.match(r"Job (\S+) finished: (\w+)\.", text) if ok else None
        if done or not ok or not text.startswith(f"Job "):
            break
    if not done:
        why = f"wait_job: {text[:300]}" if not ok else f"the scan Job {job_id} didn't finish within {WAITS} calls of wait_job"
        return {"scan": {"ok": False, "jobId": job_id, "why": why}}
    number, status = done.groups()
    ok, logs = await call("get_job_logs", jobId=job_id)
    summary = scan_summary(logs if ok else "") or scan_summary(text)
    result = next((ln for ln in (summary or "").splitlines() if ln.startswith("result:")), "")
    ran = status == "Succeeded" and result == "result: both tools ran"
    why = None if ran else (f"the scan Job {number} ended {status}" + (f" ({result})" if result else "")
                            + ("" if summary else ", and its log has no scan summary"))
    return {"scan": {"ok": ran, "jobId": job_id, "number": number, "status": status, "summary": summary, "why": why}}


def scan_summary(log):
    """The scan's summary in a Job's log: the last block between its two markers, with them. None when there is none."""
    end = (log or "").rfind(SUMMARY[1])
    start = log.rfind(SUMMARY[0], 0, end) if end >= 0 else -1
    return log[start:end + len(SUMMARY[1])] if start >= 0 else None


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
    g.add_node("scan", scan)
    g.add_node("findings", findings)
    g.add_edge(START, "collect")
    g.add_edge("collect", "scan")
    g.add_edge("scan", "findings")
    g.add_edge("findings", END)
    return g.compile(checkpointer=checkpointer)
