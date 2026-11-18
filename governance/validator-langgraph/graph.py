"""The LangGraph validator of the App validation demo (domino-agent-service spec #260, Implementation Decision 9): a fixed graph. Each
run does the same steps in the same order:

  collect   own tools read the App's code (list_files, read_file, as the probe did); get_bundle, get_policy
  scan      run_job with the shared scan (governance/scan.py), wait_job until the Job is done, get_job_logs: the scan's summary
  analyze   the model (its own, with room to answer: max_tokens 16000) sorts the hits and gives the doc's facts, through one tool
            call (the structured output); the code then applies the shared rules (governance/README.md)
  write     renders the doc from the shared template (governance/validation-doc.md), writes it to the doc dataset's mount,
            write_dataset_snapshot, get_dataset_snapshot until the snapshot is active, write_bundle_attachment (DatasetSnapshotFile)
  findings  write_governance_finding for each real finding ("[LangGraph] <title>"), then write_policy_result for the evidence item
            "Validation (LangGraph)" only; then the task's result, streamed as the last text: its first lines are "Verdict: ...",
            "Critical vulns: ..." and "Doc location: ...", which the scripted check reads (governance/validation_status.py)

A task validates once. A later run of the same task (a person's message to it) does nothing again, so no finding is filed twice:
its result is the validation's result. A new move of the bundle to Validation starts a new task, so a new validation.

The gateway tools are called from this code through the relay (domino_agui.contract.relay(): a ToolResult with is_error, so a denial
is seen as one), never by the model. The instruction is the event subscription's (subscription.json): the graph reads the bundle ID
and the doc dataset from its lines "Bundle ID: ...", "Doc dataset ID: ..." and "Doc dataset path: ..." (the dataset's mount in the
Job, /mnt/data/<dataset name> in a Git-based project).

The entry point is governance/validator-langgraph/graph.py:build_graph. The definition is agent.json, next to this file. The data is
fake.
"""
import asyncio
import json
import operator
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from domino_agui import contract
from domino_agui.langgraph import State, system_prompt

ROOT = Path(__file__).resolve().parents[2]   # the project's root: this file is governance/validator-langgraph/graph.py
HERE = Path(__file__).resolve().parent
SKIP = {".git", "__pycache__", ".venv", "node_modules"}
LIMIT = 200
APP = ("app.sh", "case_server")   # the App under validation: its start script and its server
EVIDENCE = "Validation (LangGraph)"   # the evidence item this validator fills, and no other
FIELDS = ("Verdict", "Critical vulns", "Summary", "Doc location")   # its fields' labels (governance/app-deployment-policy.yaml)
SCAN = "python governance/scan.py"   # the shared scan, as both validators run it (governance/README.md)
SUMMARY = ("== scan summary ==", "== end of scan summary ==")   # its summary's markers: Domino adds lines after it, so not the last line
WAITS = 30   # wait_job calls before the graph stops waiting for the scan: each one waits up to 45 s, so about 20 minutes
MAX_TOKENS = 16000   # the model's output limit (domino-agui#1: the ready-made model sets none, and an alias then gets 4,096)
VERDICTS = ("approve", "approve after fixes", "do not approve")   # the policy's Verdict values, exactly
SEVERITIES = ("S0", "S1", "S2", "S3")   # write_governance_finding's scale (governance/README.md)
PREFIX = "[LangGraph]"   # each finding's name starts with the validator's short name
RULES = ("## The severity scale", "## Finding names", "## Critical vulns")   # the shared rules: sections of governance/README.md
README_CHARS = 15000   # the start of the project's README: the App's own part
SNAPSHOT_EVERY, SNAPSHOTS = 5, 36   # get_dataset_snapshot every 5 s, at most 36 times (3 minutes), until the snapshot is active
SNAPSHOT_ENDED = ("active", "failed", "markForDeletion", "deletionInProgress", "deleted")   # Domino's snapshot statuses that end the wait
COMMENT = re.compile(r"<!--.*?-->\n?", re.S)   # the template's guidance (governance/README.md: a renderer strips it)

TEXT = {"type": "string"}
ANALYSIS = {   # the model's structured output: the one tool it calls
    "title": "validation_analysis",
    "description": "The analysis of the validation: the doc's facts, the real findings, the false hits and the verdict. Call it once.",
    "type": "object",
    "properties": {
        "app": {**TEXT, "description": "The App's name, as its code and README name it"},
        "purpose": {**TEXT, "description": "What the App does, in two or three sentences"},
        "tech_stack": {**TEXT, "description": "The language, the frameworks, the server and the storage"},
        "architecture": {**TEXT, "description": "The parts and how they connect: the entry point, the routes or tools, the state, who can "
                                                "call what"},
        "dependencies": {"type": "array", "items": {"type": "object", "required": ["name", "version", "installed_by"], "properties": {
            "name": TEXT, "version": {**TEXT, "description": "The version or range"},
            "installed_by": {**TEXT, "description": "How it is installed: a requirements file, the start script, the Environment"}}}},
        "real_findings": {"type": "array", "items": {"type": "object", "required": ["title", "severity", "source", "evidence", "fix"],
                                                     "properties": {
            "title": {**TEXT, "description": "A short title, with no prefix"}, "severity": {"enum": list(SEVERITIES)},
            "source": {"enum": ["scan", "code"], "description": "scan: a scanner hit; code: found in the code"},
            "evidence": {**TEXT, "description": "file:line, and the scanner hit or the code that shows it"}, "fix": TEXT,
            "description": {**TEXT, "description": "What a caller can do, and the harm"}}}},
        "false_hits": {"type": "array", "items": {"type": "object", "required": ["hit", "reason"], "properties": {
            "hit": {**TEXT, "description": "The scanner hit, as the summary gives it: its ID, name and file:line"},
            "reason": {**TEXT, "description": "Why it can't do harm, with the file and line that show it"}}}},
        "critical_vulns_reason": {**TEXT, "description": "The S0 findings, or why no finding is S0"},
        "verdict": {"enum": list(VERDICTS)},
        "verdict_reason": {**TEXT, "description": "The findings that decide the verdict"},
        "could_not_check": {"type": "array", "items": TEXT, "description": "The limits of this validation"},
        "summary": {**TEXT, "description": "Two or three sentences for the evidence item's Summary"}},
    "required": ["app", "purpose", "tech_stack", "architecture", "dependencies", "real_findings", "false_hits", "critical_vulns_reason",
                 "verdict", "verdict_reason", "could_not_check", "summary"]}


def list_files(folder: str = ".") -> str:
    """The files under a folder of the project, as paths relative to the project's root, one on each line (at most 200). A file's
    path gives that file (rglob on a file gives nothing)."""
    base = _inside(folder)
    found = [base] if base.is_file() else base.rglob("*")
    files = sorted(str(p.relative_to(ROOT)) for p in found if p.is_file() and not SKIP & set(p.relative_to(ROOT).parts))
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
    analysis: dict    # the model's analysis, after the shared rules: with "findings" (named) and "critical_vulns"
    doc: dict         # {"location", "filename", "datasetId", "snapshotId", "attached"}: where the doc is
    problems: Annotated[list, operator.add]   # what a step could not do, for the result and the doc
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


async def call(tool, /, **args):
    """One gateway tool call through the relay. -> (ok, the answer's text). A denial or Domino's error is not ok. (`tool` is positional
    only: write_governance_finding has an argument `name`.)"""
    got = await contract.relay().call(tool, args)
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
    done, waiting = None, False
    for _ in range(WAITS):
        ok, text = await call("wait_job", jobId=job_id)
        done = re.match(r"Job (\S+) finished: (\w+)\.", text) if ok else None
        waiting = ok and not done and text.startswith("Job ")   # "Job N is still <status> ...": call it again
        if not waiting:
            break
    if not done:
        why = f"the scan Job {job_id} didn't finish within {WAITS} calls of wait_job" if waiting else f"wait_job: {text[:300]}"
        return {"scan": {"ok": False, "jobId": job_id, "why": why}}
    number, status = done.groups()
    ok, logs = await call("get_job_logs", jobId=job_id)
    summary = scan_summary(logs if ok else "") or scan_summary(text)
    result = next((ln for ln in (summary or "").splitlines() if ln.startswith("result:")), "")
    ran = status == "Succeeded" and result == "result: both tools ran"
    why = None if ran else (f"the scan Job {number} ended {status}" + (f": {result[len('result: '):]}" if result else "")
                            + ("" if summary else ", and its log has no scan summary"))
    return {"scan": {"ok": ran, "jobId": job_id, "number": number, "status": status, "summary": summary, "why": why}}


def scan_summary(log):
    """The scan's summary in a Job's log: the last block between its two markers, with them. None when there is none."""
    end = (log or "").rfind(SUMMARY[1])
    start = log.rfind(SUMMARY[0], 0, end) if end >= 0 else -1
    return log[start:end + len(SUMMARY[1])] if start >= 0 else None


def validator_model():
    """The model, with room to answer: the alias in AGENT_MODEL, in the format of AGENT_MODEL_FORMAT, as the ready-made model, with
    max_tokens set (domino-agui#1). Made when it is called: a graph builds with no model variables."""
    if contract.alias_format() == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=contract.model_alias(), max_tokens=MAX_TOKENS)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=contract.model_alias(), use_responses_api=False, max_tokens=MAX_TOKENS)


async def analyze(state):
    """One model call, which gives the analysis through the validation_analysis tool. Its stream stays out of the task's: the result is
    the last step's. The tool is offered, not forced: Claude's newest models refuse a forced tool choice, which langchain-anthropic's
    with_structured_output sends. An answer that can't be used is asked again once; then the analysis says why it failed."""
    model = validator_model().bind_tools([ANALYSIS]).with_config(metadata={"emit-messages": False, "emit-tool-calls": False})
    system = "\n\n".join([m.content for m in system_prompt(state)] + [(HERE / "analyze.md").read_text()])
    asked, why = facts(state), None
    for _ in range(2):
        got = await model.ainvoke([SystemMessage(system), HumanMessage(asked + (f"\n\nYour last answer could not be used: {why}. Call "
                                                                                 f"{ANALYSIS['title']} once, with every field." if why else ""))])
        analysis, why = read_analysis(got)
        if analysis:
            return {"analysis": ruled(analysis, state.get("scan") or {})}
    return {"analysis": ruled(unanalyzed(state, why), state.get("scan") or {}), "problems": [f"analyze: {why}"]}


def facts(state):
    """What the model reads: the task, the bundle, the scan, the App's code, the start of the README, the shared rules and the doc's
    template."""
    scan, bundle = state.get("scan") or {}, state.get("bundle") or {}
    if scan.get("ok"):
        scanned = scan["summary"]
    else:
        scanned = (f"The scan did not run to its end: {scan.get('why')}. Give no finding with the source scan."
                   + (f" What its log says:\n{scan['summary']}" if scan.get("summary") else ""))
    code = "\n\n".join(f"### {path}\n\n```\n{text}\n```" for path, text in (state.get("code") or {}).items())
    readme = read_file("README.md", README_CHARS) if (ROOT / "README.md").is_file() else "(none)"
    shared = (ROOT / "governance" / "README.md").read_text()
    rules = "\n\n".join(section(shared, heading) for heading in RULES)
    template = (ROOT / "governance" / "validation-doc.md").read_text()
    about = {k: bundle.get(k) for k in ("id", "name", "projectName", "stage", "policyName") if bundle.get(k)}
    return "\n\n".join([f"## The task\n\n{instruction_of(state)}", f"## The bundle\n\n{json.dumps(about) if about else '(not read)'}",
                         f"## The scan\n\n{scanned}", f"## The App's code\n\n{code}", f"## The project's README (its start)\n\n{readme}",
                         f"## The rules (governance/README.md)\n\n{rules}", f"## The doc's template (governance/validation-doc.md)\n\n{template}"])


def section(text, heading):
    """One section of a Markdown text: from its heading to the next heading of the same level."""
    start = text.find(heading + "\n")
    if start < 0:
        return ""
    end = text.find("\n## ", start + len(heading))
    return text[start:end if end >= 0 else len(text)].strip()


def read_analysis(message):
    """The model's answer -> (the analysis, None), or (None, why it can't be used). An answer cut at its output limit has stop_reason
    max_tokens (the Anthropic format) or finish_reason length (the OpenAI format)."""
    meta = message.response_metadata or {}
    if meta.get("stop_reason") == "max_tokens" or meta.get("finish_reason") == "length":
        return None, f"the model's answer stopped at its output limit ({MAX_TOKENS} tokens)"
    call = next((c for c in message.tool_calls or [] if c.get("name") == ANALYSIS["title"]), None)
    if not call:
        return None, f"the model's answer has no {ANALYSIS['title']} call"
    a = call.get("args") or {}
    missing = [k for k in ANALYSIS["required"] if k not in a]
    verdict = str(a.get("verdict") or "").strip().lower()
    if missing or verdict not in VERDICTS:
        return None, f"its {ANALYSIS['title']} call " + (f"lacks {', '.join(missing)}" if missing else f"has the verdict {verdict!r}")
    out = {k: str(a.get(k) or "").strip() for k in ("app", "purpose", "tech_stack", "architecture", "critical_vulns_reason",
                                                    "verdict_reason", "summary")}
    out["verdict"] = verdict
    out["dependencies"] = [{k: str(d.get(k) or "").strip() for k in ("name", "version", "installed_by")}
                           for d in a.get("dependencies") or [] if isinstance(d, dict)]
    out["false_hits"] = [{k: str(h.get(k) or "").strip() for k in ("hit", "reason")} for h in a.get("false_hits") or [] if isinstance(h, dict)]
    out["could_not_check"] = [str(x).strip() for x in a.get("could_not_check") or [] if str(x).strip()]
    found = []
    for f in a.get("real_findings") or []:
        f = f if isinstance(f, dict) else {}
        severity, source = str(f.get("severity") or "").strip().upper(), str(f.get("source") or "").strip().lower()
        if severity not in SEVERITIES or source not in ("scan", "code") or not str(f.get("title") or "").strip():
            return None, f"a real finding of its {ANALYSIS['title']} call has no title, or no severity S0 to S3, or no source"
        found.append({"title": str(f["title"]).strip(), "severity": severity, "source": source,
                      **{k: str(f.get(k) or "").strip() for k in ("evidence", "fix", "description")}})
    out["real_findings"] = found
    return out, None


def unanalyzed(state, why):
    """The analysis when the model's answers couldn't be used: no hit sorted, and no finding filed."""
    return {"app": (state.get("bundle") or {}).get("name") or "the App", "purpose": "Not analyzed.", "tech_stack": "Not analyzed.",
            "architecture": "Not analyzed.", "dependencies": [], "real_findings": [], "false_hits": [],
            "critical_vulns_reason": "Not analyzed: no hit was sorted.", "verdict": "do not approve",
            "verdict_reason": f"The validator's analysis failed ({why}), so it sorted no hit: run the validation again.",
            "could_not_check": [f"The analysis: {why}."], "summary": f"The validator's analysis failed: {why}."}


def ruled(analysis, scan):
    """The shared rules on the model's analysis (governance/README.md): each finding's name starts with the validator's short name, and
    critical vulns is yes when a real finding is S0. When the scan did not run to its end, no finding comes from it (one that says so is
    left out), and the verdict is do not approve: the dependencies' known vulnerabilities were not checked."""
    a = dict(analysis)
    if not scan.get("ok"):
        a["real_findings"] = [f for f in a["real_findings"] if f["source"] != "scan"]
        a["verdict"] = "do not approve"
        a["verdict_reason"] = (f"The scan did not run to its end ({scan.get('why')}). So the dependencies' known vulnerabilities were "
                               f"not checked: run the validation again. {a['verdict_reason']}").strip()
        a["could_not_check"] = [f"The scan: {scan.get('why')}."] + a["could_not_check"]
        a["summary"] = f"The scan did not run to its end: {scan.get('why')}. {a['summary']}".strip()
    a["findings"] = [{**f, "name": PREFIX + " " + f["title"].removeprefix(PREFIX).strip()} for f in a["real_findings"]]
    a["critical_vulns"] = "yes" if any(f["severity"] == "S0" for f in a["findings"]) else "no"
    return a


async def write(state):
    """The doc: the shared template filled, written to the doc dataset's mount, snapshot, and attached to the bundle once the snapshot
    is active. A step that can't be done is said in the doc's location and in the problems, and the graph goes on."""
    instruction, bundle_id = instruction_of(state), state["bundle_id"]
    dataset_id, mount = setting(instruction, "Doc dataset ID"), setting(instruction, "Doc dataset path")
    now = datetime.now(timezone.utc)
    filename = f"validation-{bundle_id}-{now:%Y%m%dT%H%M%SZ}.md"
    if not dataset_id or not mount:
        why = "the instruction names no doc dataset (its lines Doc dataset ID and Doc dataset path)"
        return {"doc": {"location": f"not written: {why}"}, "problems": [f"write: {why}"]}
    try:
        (Path(mount) / filename).write_text(render_doc(state, now))
    except OSError as e:
        return {"doc": {"location": f"not written: {e}"}, "problems": [f"write: the doc could not be written to {mount}: {e}"]}
    ok, text = await call("write_dataset_snapshot", datasetId=dataset_id)
    snapshot_id = ((answer(text) or {}).get("snapshot") or {}).get("id") if ok else None
    if not snapshot_id:
        return {"doc": {"location": f"written to {mount}/{filename}, with no snapshot"}, "problems": [f"write_dataset_snapshot: {text[:300]}"]}
    doc = {"location": f"dataset {dataset_id}, snapshot {snapshot_id}, file {filename}", "filename": filename, "datasetId": dataset_id,
           "snapshotId": snapshot_id, "attached": False}
    status, text = await snapshot_ready(dataset_id, snapshot_id)
    if status != "active":
        doc["location"] += f" (the snapshot is {status or 'not known'}: not attached)"
        return {"doc": doc, "problems": [f"get_dataset_snapshot: the snapshot is {status or 'not known'} ({text[:200]}), so the doc isn't "
                                         "attached"]}
    ok, text = await call("write_bundle_attachment", bundleId=bundle_id, type="DatasetSnapshotFile",
                          identifier={"datasetId": dataset_id, "snapshotId": snapshot_id, "filename": filename})
    return {"doc": {**doc, "attached": ok}, **({} if ok else {"problems": [f"write_bundle_attachment: {text[:300]}"]})}


async def snapshot_ready(dataset_id, snapshot_id):
    """get_dataset_snapshot until the snapshot is active, failed or gone, or the wait is over. -> (its status or None, the last answer)"""
    status, text = None, ""
    for n in range(SNAPSHOTS):
        if n:
            await asyncio.sleep(SNAPSHOT_EVERY)
        ok, text = await call("get_dataset_snapshot", datasetId=dataset_id, snapshotId=snapshot_id)
        status = ((answer(text) or {}).get("snapshot") or {}).get("status") if ok else None
        if not ok or status in SNAPSHOT_ENDED:
            break
    return status, text


def intake(state):
    """The doc's fields from the bundle's Intake evidence (users, data class). No gateway tool reads a bundle's results yet, so they
    are not read: the doc says so, and lists it under what the validator could not check."""
    return {"users_and_data_class": "Not read: the gateway tools give no read of the bundle's evidence results, so this validator did not "
                                    "read the Intake evidence (users, data class).",
            "could_not_check": "The Intake evidence (users, data class): no gateway tool reads a bundle's results."}


def render_doc(state, now):
    """The validation doc: the shared template (governance/validation-doc.md), each {{field}} filled and each comment removed."""
    fields = doc_fields(state, now)
    text = COMMENT.sub("", (ROOT / "governance" / "validation-doc.md").read_text())
    return re.sub(r"{{(\w+)}}", lambda m: fields.get(m.group(1), m.group(0)), text).lstrip()


def doc_fields(state, now):
    a, scan, bundle = state.get("analysis") or {}, state.get("scan") or {}, state.get("bundle") or {}
    commit = next((ln.split(":", 1)[1].strip() for ln in (scan.get("summary") or "").splitlines() if ln.startswith("commit:")), None)
    app = a.get("app") or bundle.get("name") or "the App"
    known = intake(state)
    return {"app": app, "validator": f"App validator (LangGraph), the framework lane, task {os.environ.get('TASK_KEY') or 'unknown'}",
            "bundle_id": state["bundle_id"], "written_at": f"{now:%Y-%m-%d %H:%M}",
            "app_and_version": f"{app}" + (f", the bundle {bundle['name']}" if bundle.get("name") else "")
                               + (f". Commit {commit}: the commit that the scan read (the project's default branch)." if commit else
                                  ". The commit is not known: the scan did not give it."),
            "purpose": a.get("purpose") or "", "users_and_data_class": known["users_and_data_class"],
            "tech_stack": a.get("tech_stack") or "", "architecture": a.get("architecture") or "",
            "dependencies": table(["Dependency", "Version or range", "How it is installed"],
                                  [[d["name"], d["version"], d["installed_by"]] for d in a.get("dependencies") or []]),
            "scan_results": scan_results(scan),
            "real_findings": table(["Name", "Severity", "Evidence", "Fix"],
                                   [[f["name"], f["severity"], f["evidence"], f["fix"]] for f in a.get("findings") or []]),
            "false_hits": table(["Hit", "Why it is false"], [[h["hit"], h["reason"]] for h in a.get("false_hits") or []]),
            "critical_vulns": a.get("critical_vulns") or "no", "critical_vulns_reason": a.get("critical_vulns_reason") or "",
            "verdict": a.get("verdict") or "do not approve", "verdict_reason": a.get("verdict_reason") or "",
            "could_not_check": "\n".join(f"- {x}" for x in [*(a.get("could_not_check") or []), known["could_not_check"]])}


def table(head, rows):
    """A Markdown table, or "None." when it has no row."""
    if not rows:
        return "None."
    cell = lambda v: " ".join(str(v or "").split()).replace("|", "\\|")
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows])


def scan_results(scan):
    """The scan's table (each tool, its version and its hits, from the summary) and its Job; or why the scan did not run to its end."""
    tools = []   # [tool, version, what it said, [its hits]]
    for ln in (scan.get("summary") or "").splitlines():
        m = re.match(r"(pip-audit|bandit) (\S+) on .+?: (.*)$", ln)
        if m:
            tools.append([*m.groups(), []])
        elif ln.startswith("- ") and tools:
            tools[-1][3].append(ln[2:])
    rows = [[name, version, said + (": " + "; ".join(hits) if hits else "")] for name, version, said, hits in tools]
    job = f"Scan Job {scan['number']}: {scan.get('status')}." if scan.get("number") else ""
    head = "" if scan.get("ok") else f"The scan did not run to its end: {scan.get('why')}. No finding comes from it.\n\n"
    return (head + (table(["Tool", "Version", "Hits"], rows) + "\n\n" if rows else "") + job).strip()


async def findings(state, config):
    """Each real finding on the bundle, then this validator's evidence item, then the task's result. The result is streamed as the
    run's last text: the task's result is the run's last text, and a message that a node only puts in the state is not sent."""
    a, doc, bundle_id = state.get("analysis") or {}, state.get("doc") or {}, state["bundle_id"]
    filed, problems = [], []
    for f in a.get("findings") or []:
        description = "\n\n".join(x for x in [f.get("description"), f"Evidence: {f['evidence']}", f"Fix: {f['fix']}",
                                               f"Filed by the App validator (LangGraph), from {'the scan' if f['source'] == 'scan' else 'the code'}."] if x)
        ok, text = await call("write_governance_finding", bundleId=bundle_id, name=f["name"], severity=f["severity"], description=description)
        if ok:
            filed.append(f["name"])
        else:
            problems.append(f"write_governance_finding ({f['name']}): {text[:200]}")
    summary = " ".join(x for x in [a.get("summary"), f"Real findings filed: {len(filed)}.", f"False hits: {len(a.get('false_hits') or [])}.",
                                   (f"Not done: {'; '.join(state.get('problems') or [])}." if state.get("problems") else "")] if x)
    item, location = state.get("evidence") or {}, doc.get("location") or "not written"
    fields = item.get("fields") or {}
    if item.get("id") and all(fields.get(label) for label in FIELDS):
        content = {fields["Verdict"]: a.get("verdict"), fields["Critical vulns"]: a.get("critical_vulns"), fields["Summary"]: summary,
                   fields["Doc location"]: location}
        ok, text = await call("write_policy_result", bundleId=bundle_id, evidenceId=item["id"], content=content)
        filled = "filled" if ok else "not filled"
        if not ok:
            problems.append(f"write_policy_result: {text[:300]}")
    else:
        filled = "not filled"
        problems.append(f"write_policy_result: the bundle's policy has no evidence item {EVIDENCE!r} with the fields {', '.join(FIELDS)}")
    result = "\n".join([f"Verdict: {a.get('verdict')}", f"Critical vulns: {a.get('critical_vulns')}", f"Doc location: {location}", "",
                        f"Bundle: {bundle_id}. {a.get('summary') or ''}".strip(), "",
                        f"Findings filed ({len(filed)}): {'; '.join(filed) or 'none'}",
                        f"False hits ({len(a.get('false_hits') or [])}): {'; '.join(h['hit'] for h in a.get('false_hits') or []) or 'none'}",
                        f"Evidence item {EVIDENCE}: {filled}."]
                       + ([("Not done:"), *(f"- {x}" for x in (state.get("problems") or []) + problems)]
                          if state.get("problems") or problems else []))
    message_id = f"msg-{uuid.uuid4().hex[:16]}"
    await adispatch_custom_event("manually_emit_message", {"message_id": message_id, "message": result}, config=config)
    return {"result": result, "messages": [AIMessage(result, id=message_id)], "problems": problems}


async def repeat(state, config):
    """A later run of a task that has validated: no step again (each one would file the findings again), only its result."""
    result = (f"{state['result']}\n\nThis task validated bundle {state.get('bundle_id')} already, so it did nothing again. A new move "
              "of the bundle to the Validation stage starts a new validation.")
    message_id = f"msg-{uuid.uuid4().hex[:16]}"
    await adispatch_custom_event("manually_emit_message", {"message_id": message_id, "message": result}, config=config)
    return {"messages": [AIMessage(result, id=message_id)]}


def first(state):
    """The first step: collect, or repeat for a task that has validated (its thread keeps the result)."""
    return "repeat" if state.get("result") else "collect"


def build_graph(checkpointer):
    """The compiled graph, with the checkpointer that the platform's adapter gives (the thread lives in the state folder)."""
    g = StateGraph(Validation)
    g.add_node("repeat", repeat)
    g.add_node("collect", collect)
    g.add_node("scan", scan)
    g.add_node("analyze", analyze)
    g.add_node("write", write)
    g.add_node("findings", findings)
    g.add_conditional_edges(START, first, ["collect", "repeat"])
    g.add_edge("repeat", END)
    g.add_edge("collect", "scan")
    g.add_edge("scan", "analyze")
    g.add_edge("analyze", "write")
    g.add_edge("write", "findings")
    g.add_edge("findings", END)
    return g.compile(checkpointer=checkpointer)
