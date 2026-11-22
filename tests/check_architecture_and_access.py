"""Check 2, Architecture and access (governance/check-architecture-and-access/): a registered agent (opencode),
an agent folder that `domino-agent deploy` registers (domino-agent-service spec #388, Implementation Decision 9, ticket #394). It is
the folder validator of spec #260 (the tag app-validation-two-ways keeps it), narrowed to its part: no scan, Run a Job off. Seen from
outside: its files as `domino-agent deploy` uploads them, its checklist skill as the agent reads it, the templates of its event
subscription (its file in the folder, ADR 0049 of domino-agent-service, ticket #398), and the agent that a local agent service
registers from it.

The names come from governance/checks.json (the check's name, its evidence item, the field labels, the verdicts and the severities),
and the rules from governance/rules.md (the rules that the three checks share, spec #499, ticket #508: the checklist says to read
it) and governance/validation-doc.md (the doc's template).

With no service, it checks the folder's files: the ones that deploy uploads (with the own tool's file, tools/route_table.py, and the
custom subagent's file, subagents/route-reviewer.md, and not the unit test or the README), the settings of definition.md, the
checklist's rules and the order of its tools (the own tool own_route_table, then one task call of the custom subagent route-reviewer,
both before the writes), the instructions' rules, the tool names (as opencode names them: domino_<name> and own_route_table), the own
tool's file (the standard library only, and no code that it imports or runs), the custom subagent's file (its settings: the agent's
model, read only, Project files read; its instructions and its answer form), the subscription's file
(subscriptions/bundle-enters-validation.md: its filter on the demo project's name and its two templates, which name the bundle ID), no
Domino host or ID (the repo is public), no em dash, the glossary's words (spec #459: the folder is demo text), and the folder's
README.

With domino_agent (the domino-agent package of this Python, or the package of the AGENT_SERVICE_REPO checkout), it runs the own tool's
unit test, test_route_table.py (python -m unittest in the folder, spec #459 seam 1). With neither, that part prints a SKIP line.

With the service (AGENT_SERVICE_REPO, the path of a domino-agent-service checkout), it checks each tool name against the service's
gateway and relay (agent_runtime/gateway.py and proxies.py: stdlib, any OS), and the service's own tool reader reads the tool file
(domino_agent/own_tools.py: stdlib, any OS). On Linux, it also starts that service over real HTTP with a fake Domino (the service's
seam helper, tests/agent_folder_seam.py), with the folder committed in a temporary clone:
  - `domino-agent deploy --dry-run` passes the service's folder rules, and its Changed line names the tool file and subagents;
    `deploy` registers the agent, which can't run yet, with its own tool and its custom subagent, and adds the subscription from its
    file (with the seam's project name in place of the demo project's name in the temporary clone).
  - A stage move (the audit poller's payload) starts no task before the service account's token, nor for an analyst who may not use
    the agent; then one task, as the service account, and its Job.
  - The Job's spec (the skill, the own tool, the custom subagent as opencode gets it, read only, with the built-in subagent off, the
    access rows, Run a Job off, Git push on, the permissions, the limits) and the gateway's decisions for that task on the event's
    bundle: the attachment, the findings and the evidence are allowed by the row "Other resources
    attached to the task", and run_job is denied. The evidence by names (spec #499) reaches a fake Domino as the IDs of its item
    and its fields.
  - A stage move to another stage, or in another project, starts nothing. A second deploy of the same commit keeps the subscription.
With AGENT_SERVICE_REPO unset, or not on Linux, those parts print a SKIP line. No Domino host: the live run is domino-agent-service
#397.

  python tests/check_architecture_and_access.py                                                   # the files only
  AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_architecture_and_access.py   # on Linux: everything (README)
"""
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from functools import partial
from pathlib import Path

import three_checks as shared   # the shared parts of the three checks' checks, next to this file (stdlib only)
from three_checks import ROOT, check, done, text

PATH = "governance/check-architecture-and-access"   # the folder, as checks.json names it
FOLDER = ROOT / PATH


def known(rel):
    """Is `rel` (a path in the folder) a file that deploy uploads? definition.md, instructions.md, skills/<name>/<file>,
    subagents/<file>.md, tools/<file> and a file in schedules/ or subscriptions/ (the service's domino_agent/folder_format.is_known).
    A hidden part or __pycache__ is not one."""
    parts = rel.split("/")
    if any(not p or p.startswith(".") or p == "__pycache__" for p in parts):
        return False
    return rel in ("definition.md", "instructions.md") or (len(parts) >= 3 and parts[0] == "skills") \
        or (len(parts) == 2 and parts[0] == "subagents" and rel.endswith(".md")) \
        or (len(parts) >= 2 and parts[0] in ("tools", "schedules", "subscriptions"))


# ------------------------------------------------------------------------------------------------- the names, from checks.json
# governance/checks.json is the one source of the names and labels of the three checks (ticket #392)
CHECKS, me = shared.load_checks(PATH)
check(f"governance/checks.json has this check, with its folder {PATH}, its name and its evidence item",
      bool(me.get("name") and me.get("evidenceItem")), CHECKS.get("checks"))
NAME = me.get("name") or "(no name in checks.json)"   # the agent's title, the findings' prefix, the doc's {{check}}
EVIDENCE = me.get("evidenceItem") or "(no evidence item in checks.json)"   # its evidence item in the policy
LABELS = [(CHECKS.get("fields") or {}).get(k) or f"(no {k} label)" for k in ("verdict", "severity", "summary", "doc")]
VERDICTS = list(CHECKS.get("verdicts") or ["(no verdicts)"])
SEVERITIES = list(CHECKS.get("severities") or ["(no severities)"])
OTHERS = [c.get("name") for c in CHECKS.get("checks") or [] if isinstance(c, dict) and c.get("folder") != PATH]
SLUG = NAME.lower().replace(" ", "-")   # architecture-and-access: the Registration's name, the skill's name, the doc's file name
SKILL = f"skills/{SLUG}/SKILL.md"
SUB_NAME = "bundle-enters-validation"   # the trigger name of the three checks' form, "Bundle enters Validation", as a file name
SUB = f"subscriptions/{SUB_NAME}.md"    # the event subscription (ADR 0049): the file name is the trigger's name and its identity
TOOL_NAME = "route_table"               # the own tool (spec #459, decision 4): the agent sees it as own_route_table
TOOL = f"tools/{TOOL_NAME}.py"
OWN = f"own_{TOOL_NAME}"
UNIT_TEST = f"test_{TOOL_NAME}.py"      # its unit test, next to definition.md: deploy does not upload it
SUBAGENT_NAME = "route-reviewer"        # the custom subagent (spec #459, decision 5): the main agent starts it with the task tool
SUBAGENT = f"subagents/{SUBAGENT_NAME}.md"
UPLOADED = ("definition.md", "instructions.md", SKILL, SUB, TOOL, SUBAGENT)   # what deploy uploads of the folder

# --------------------------------------------------------------------------------------------------------------------- the files
every = {p.relative_to(FOLDER).as_posix(): p.read_text() for p in sorted(FOLDER.rglob("*")) if p.is_file()} if FOLDER.is_dir() else {}
files = {k: v for k, v in every.items() if known(k)}
check(f"{PATH}/ uploads definition.md, instructions.md, one own skill, {SLUG}, one subscription file, {SUB}, one own tool "
      f"file, {TOOL}, and one custom subagent's file, {SUBAGENT}, and nothing else", sorted(files) == sorted(UPLOADED), sorted(files))
check(f"...the own tool's unit test, {UNIT_TEST}, and README.md are in the folder, next to definition.md, and deploy does not upload "
      "them", all(f in every and not known(f) for f in (UNIT_TEST, "README.md")), sorted(every))
check("the repo's .gitignore has __pycache__/: a run of the unit test writes it, and deploy refuses a folder with changes that are "
      "not committed", "__pycache__/" in text(ROOT / ".gitignore").splitlines())
settings, instructions, skill, subscription, tool_file, subagent = (files.get(k, "") for k in UPLOADED)
check("definition.md holds only the settings, between its two --- lines: the instructions are instructions.md",
      settings.startswith("---\n") and settings.rstrip().endswith("\n---") and settings.count("\n---") == 1, settings[-200:])
top = re.match(r"---\n(.*?)\n---\n", skill, re.S)
check("the skill's SKILL.md has YAML on top with its folder's name and a description (else opencode never offers it)",
      bool(top) and re.search(rf"^name: {re.escape(SLUG)}$", top.group(1), re.M)
      and re.search(r"^description: \S.{20,}$", top.group(1), re.M), skill[:300])


def fields_of(definition):
    """definition.md's settings as {"field" or "group.field": its value}, with the comments removed. Stdlib only, so a plain reading:
    a field at the start of a line, or a field of a group (tools, access, limits) two spaces in. Enough for the values below; the
    service's own reading is the deploy on Linux."""
    got, group = {}, None
    for ln in definition.split("\n---")[0].splitlines():
        m = re.match(r"^( {0,2})([a-z][a-z-]*):(?:\s+([^#]*?))?\s*(?:#.*)?$", ln)
        if not m:
            continue
        indent, key, value = m.group(1), m.group(2), (m.group(3) or "").strip()
        if not indent:
            group = key if not value else None
            got[key] = value
        elif group:
            got[f"{group}.{key}"] = value
    return got


MODEL = "google/gemini-3.8-flash"   # spec #388 decision 7: the same model for the three checks (sonnet is refused: domino-agent-service#270)
WANT = {"name": SLUG, "title": NAME, "model": MODEL, "identity": "service-account", "on-error": "fail",
        "tools.subagents": "false", "tools.jobs": "false", "tools.push": "true",
        "access.project": "write", "access.datasets": "none", "access.attached": "write", "access.other": "none",
        "limits.minutes": "45", "limits.turns": "120", "limits.wait-minutes": "0"}
got = fields_of(settings)
check(f"definition.md: the title {NAME} (Validation status finds the task by its agent's name), the model {MODEL}, the service "
      "account, Run a Job off, Git push on, and the other settings as the folder validator of spec #260",
      {k: got.get(k) for k in WANT} == WANT, {k: (got.get(k), v) for k, v in WANT.items() if got.get(k) != v})

# ------------------------------------------------------------------------------------------------------- the checklist (the skill)
DOC = f"docs/validation/{SLUG}-<bundleId>.md"   # the doc's file on the task branch (governance/README.md, "The three checks")
V = (VERDICTS + ["(no verdict)"] * 3)[:3]       # approve, do not approve, could not check (checks.json's order)
PURPOSE, SCAN_CHECK = (OTHERS + ["(no check)"] * 2)[:2]   # the other two checks, in checks.json's order
rule = shared.rules("the skill says", skill)   # one line of the skill says the rule: it holds every one of the words (case aside)
rule("the project folder's shared rules: the rules file, governance/rules.md", "`governance/rules.md`",
     "rules that the three checks share")
rule("...and the doc's template, governance/validation-doc.md", "`governance/validation-doc.md`", "template of the doc")
rule("read the rules file first, and follow it in each step", "read `governance/rules.md` first", "each step")
rule("read the bundle first", "domino_get_bundle", "bundleid")
rule("read the policy with the bundle's ID", "domino_get_policy", "bundleid")
SAMPLE = dict(zip(LABELS, [V[1], "S1", "One S1 finding: anyone who can open the App can delete all state in POST /reset.",
                           f"agent/AGT-1 at {'0' * 40}, {DOC}"]))   # a result as the checklist fills it, by label
CALLED, CALLED_KEYS = shared.result_call(skill)   # the evidence item and the content keys that it names
check(f"the checklist fills its evidence item by names (spec #499): {EVIDENCE!r} and the four fields by their labels, as "
      "governance/checks.json names them, in its order", CALLED == EVIDENCE and CALLED_KEYS == LABELS, (CALLED, CALLED_KEYS))
check("...so it searches for no ID: no evidenceId, no artifact ID (the gateway finds them in the bundle's policy)",
      not shared.id_search(skill), shared.id_search(skill))
rule("find the Intake values with get_policy: the stage Intake, its item Intake, and each field by its label", 'stage named "intake"',
     '"purpose"', '"users"', '"data class"', "details.label")
rule("...each field's value is its result.artifactContent, and a field with no result is not filled", "result.artifactcontent",
     "no `result`", "not filled")
rule("read the App's code and its start script", "app.sh", "code", "read")
rule("find who can call each route or tool, and what it changes", "who can call", "each route", "what it changes")
rule("find which identity each write records", "which identity", "each write", "records")
rule("find the tech stack: the language, the frameworks, the server and the storage", "tech stack", "frameworks", "storage")
rule("find the design: the parts, the routes and where the state is", "design", "routes", "state")
rule("find each dependency, how it is pinned, and how and when it is installed", "each dependency", "pinned", "installed")

# Its part only (governance/README.md, "The three checks"): no scan, and nothing filed in the other two checks' parts
SCAN = re.compile(r"domino_run_job|domino_wait_job|domino_get_job_logs|governance/scan\.py|pip-audit|bandit")
check("the checklist and the instructions have no scan step: no Job, no scan script, no scanner (Run a Job is off)",
      not SCAN.search(skill + instructions), sorted(set(SCAN.findall(skill + instructions))))
rule("file findings only in its own part, never in the other two checks' parts", "only in", "own part", f'"{PURPOSE}"',
     f'"{SCAN_CHECK}"')
rule("...a known vulnerability (a CVE, PYSEC or GHSA ID) is the Vulnerability scan's part: file none", "known vulnerability", "cve",
     f'"{SCAN_CHECK}"', "file none")
rule("...the data class is the Purpose and data part: file none; who can read the data through the App is its part", "data class",
     f'"{PURPOSE}"', "file none", "who can read")

# The evidence values, by the shared rules (governance/rules.md, "The evidence fields" and "The severity scale")
rule("the severity scale is the rules file's, with its examples for this check", "governance/rules.md", "scale", "examples")
rule("a real finding's name follows the finding names of the rules file", "name", "finding names", "governance/rules.md")
rule("the Highest severity and the Verdict follow the rules file", "highest severity", "verdict", "governance/rules.md")
rule(f"...the cases of this check that give `{V[2]}`: the App's code not read, or get_policy denied", f"`{V[2]}`", "app's code",
     "`domino_get_policy`")
rule("a false hit is not filed", "false hit", "no false hit")

# The doc: governance/validation-doc.md's shared top part and this check's middle part (the template is the source of the fields)
TEMPLATE = re.sub(r"<!--.*?-->", "", text(ROOT / "governance" / "validation-doc.md"), flags=re.S)
names = [c.get("name") for c in CHECKS.get("checks") or [] if isinstance(c, dict)]
heads = {n: m.start() for n in names for m in [re.search(rf"^## {re.escape(n)}$", TEMPLATE, re.M)] if m}   # each middle part
starts = sorted(heads.values())


def middle(n):
    """The template's middle part of the check `n`: from its heading to the next middle part."""
    return TEMPLATE[heads[n]:next((s for s in starts if s > heads[n]), len(TEMPLATE))] if n in heads else ""


FIELD = r"\{\{(\w+)\}\}"
mine = set(re.findall(FIELD, TEMPLATE[:starts[0]] + middle(NAME))) if starts else set()   # the top part and its own middle part
theirs = set(re.findall(FIELD, "".join(middle(o) for o in OTHERS))) - mine
check(f"governance/validation-doc.md has a shared top part and this check's middle part, ## {NAME}, with their fields",
      bool(middle(NAME)) and {"verdict", "doc_location", "real_findings"} <= mine, sorted(mine))
rule("the doc follows the shared template, at its file name", "governance/validation-doc.md", DOC)
rule("...trimmed to this check as the rules file says: its middle part is its own", "governance/rules.md", "trim", f"`## {NAME}`")
unsaid = sorted(f for f in mine if f"`{f}`" not in skill)
check("the skill says how to fill each field of the top part and of its own middle part (the template's fields)", mine and not unsaid,
      unsaid)
said = sorted(f for f in theirs if f"`{f}`" in skill)
check("...and names no field of the other two middle parts only", not said, said)
rule("the doc's check is the check's name", "`check`", f"`{NAME}`")
rule("the doc's own Doc location: the form of the rules file, with its own file", "`doc_location`", "governance/rules.md", DOC)
rule("the doc says what the check could not check, always the default branch", "`could_not_check`", "default branch")
rule("the doc's Architecture section has a table of each route: method, path, who can call it, what it changes",
     "architecture section", "table of each route", "method", "path", "who can call it", "what it changes")

# The own tool (spec #459, decision 6): the main agent calls it once, itself (a custom subagent's own-tool calls are not in the
# transcript and get no Activity log row), in the step that reads the App, and the doc's route table comes from its rows
rule(f"call the own tool {OWN} once, yourself, with the folder of the App's Python code", f"`{OWN}", "once", "yourself",
     "`folder`", "relative to the project folder")
rule("...its rows: the method, the path, the handler with its file and line, the identity and the writes", "row", "`method`",
     "`path`", "`file`", "`line`", "`reads_identity`", "`changes_state`")
rule("...read the handler of each row at its file and line: changes_state false means only that the rule found no write",
     "handler of each row", "file and line", "`changes_state`", "`false`", "found no write")
rule(f"when {OWN} fails (an exception, a timeout): do not call it again, and read the routes from the code", f"`{OWN}`", "fails",
     "exception", "timeout", "do not call it again", "from the code")
rule("...name the failed call under what the check could not check", "failed call", '"what this check could not check"')
rule(f"...this alone does not make the Verdict `{V[2]}`", "alone does not make", f"`{V[2]}`")
rule("each item of the tool's not_read goes under what the check could not check", "`not_read`", '"what this check could not check"')
rule("the doc's route table has one line for each row of the tool, with its method and path exactly as the tool gives them",
     "route table", "each row", f"`{OWN}`", "`method`", "`path`", "exactly")

# The custom subagent (spec #459, decisions 5 and 6): the main agent gives it the table, once, and decides; it files the findings
rule(f"give the table to the custom subagent {SUBAGENT_NAME}, once: one call of the task tool, with its name as subagent_type",
     f"`{SUBAGENT_NAME}`", "once", "`task`", "`subagent_type`")
prompt_block = next((b for b in re.findall(r"```\n(.*?)\n```", skill, re.S) if "Route table:" in b), "")
heads_of_prompt = [ln.split(":")[0] for ln in prompt_block.splitlines() if re.match(r"^[A-Z][a-z ]+:", ln)]
check(f"...its prompt has the Intake's Users and Data class, the access rules and the table of {OWN}, as the tool gave it",
      heads_of_prompt == ["Users", "Data class", "Access rules", "Route table"] and OWN in prompt_block
      and "exactly as the tool gave it" in prompt_block, prompt_block or heads_of_prompt)
rule("...the access rules: with no access check in the code, anyone who can open the App can call it", "anyone who can open the app",
     "no access check")
rule("...a write that records no identity is a problem", "each write", "`domino-username`", "records no identity")
rule("...the severity: the scale of governance/rules.md, with the Intake's Users and Data class", "severity", "governance/rules.md",
     "users", "data class")
rule("...judge only access: the other two checks' parts get no verdict", "only access", f'"{SCAN_CHECK}"', f'"{PURPOSE}"')
rule(f"...a row with no verdict of {SUBAGENT_NAME}: judge it yourself, and name it under what the check could not check",
     "no verdict", "yourself", '"what this check could not check"')
rule(f"when {SUBAGENT_NAME} gives no usable answer: do not call it again, judge the routes yourself, and name the failed step, and "
     f"this alone does not make the Verdict `{V[2]}`", f"`{SUBAGENT_NAME}`", "no usable answer", "do not call it again", "yourself",
     "failed step", '"what this check could not check"', "alone does not make", f"`{V[2]}`")
rule("sort each route problem of the review into a real finding or a false hit: the review is an input, the main agent decides",
     "route problem", "review", "you decide")
rule(f"the doc's route table takes who can call it and what it changes from the review of {SUBAGENT_NAME}", "route table",
     "who can call it", "what it changes", f"`{SUBAGENT_NAME}`")
rule(f"the main agent files the findings itself: {SUBAGENT_NAME} files nothing", "you file", f"`{SUBAGENT_NAME}`", "files nothing")
rule("...and a review with no usable answer goes under could_not_check", "`could_not_check`", "no usable answer")

# The push, the attachment, the findings, the evidence and the result
rule("push the doc with git_push, and keep its ok, branch, commit and dryRun", "domino_git_push", "`ok`", "branch", "commit", "dryrun")
rule("attach the doc: a Report from GBP, with the task branch and the push's commit", "domino_write_bundle_attachment", '"report"',
     '"gbp"', "branch", "commit", DOC)
rule("...only when the push is on the remote (ok true, dryRun false)", "only when", "`ok` true", "dryrun", "false")
rule("a dry-run push: attach nothing, and say so under what the check could not check", "dryrun", "true", "attach nothing",
     "could not check")
rule("a failed push (ok false): attach nothing, and say why", "`ok` is false", "attach nothing", "why")
rule("file each real finding with the name and the severity of the doc's table, and no false hit", "domino_write_governance_finding",
     "name", "severity", "doc's table", "no false hit")
rule("fill only its own evidence item, by its name", "fill only your own evidence item", "domino_write_policy_result",
     f'evidencename="{EVIDENCE}"')
rule("the evidence's Doc location: the line of the rules file, with the push's branch and commit and the doc's file",
     "doc location", "governance/rules.md", "branch and commit", DOC)
rule("the result goes to report_result, once, last", "domino_report_result", "once", "last")
rule("...and it is the result of the rules file: its four lines first, with the evidence item's values", "governance/rules.md",
     "four lines", "same values")

TASK_CALL = f"`subagent_type` `{SUBAGENT_NAME}`"   # the task call of step 3 (step 2 names route-reviewer before it)
order = ["domino_get_bundle", "domino_get_policy", OWN, TASK_CALL, "domino_git_push", "domino_write_bundle_attachment",
         "domino_write_governance_finding", "domino_write_policy_result", "domino_report_result"]
at = [skill.find(t) for t in order]
check(f"the checklist's tools come in order: bundle and policy, the own tool {OWN}, the task call of the custom subagent "
      f"{SUBAGENT_NAME} (both before the writes), push, attachment, findings, evidence, result",
      all(i >= 0 for i in at) and at == sorted(at), dict(zip(order, at)))
steps = [int(n) for n in re.findall(r"^## (\d+)\. ", skill, re.M)]
check("the checklist is numbered steps, in order", len(steps) >= 8 and steps == list(range(1, len(steps) + 1)), steps)
check("each step ends with its completion criterion (a 'Done when' line)",
      steps and all("Done when:" in part for part in re.split(r"^## \d+\. ", skill, flags=re.M)[1:]), steps)
BUDGET = 110   # spec #499: the checklist shows only the check (the rules are in governance/rules.md)
check(f"the checklist has at most {BUDGET} lines (spec #499)", len(skill.splitlines()) <= BUDGET, f"{len(skill.splitlines())} lines")

# ------------------------------------------------------------------------------- the rules that the checklist applies (the rules file)
# These were lines of the checklist before spec #499. The checklist now says to read the rules file, so the rules are read from it.
# tests/check_validator_parts.py checks the whole file, and that it agrees with checks.json.
rules_md = text(shared.RULES)
frule = shared.rules("the rules file says", rules_md, shared.blocks)   # one paragraph, list item or table row of it says the rule
frule("the severity scale, S0 to S3", "| s0 (critical) |")
frule(f"...with its examples for {NAME}", f"| {NAME.lower()} |", "`post /reset`", "| s1 |")
frule("a real finding's name is [<check name>] <what> in <where>", "`[<check name>] <what> in <where>`")
frule(f"...with an example for {NAME}", f"| {NAME.lower()} |", f"`[{NAME.lower()}] ")
frule("Highest severity is the highest severity of its real findings, or none", "highest severity", "real findings", "`none`")
frule(f"the verdict is `{V[1]}` when a real finding is S0 or S1", f"`{V[1]}`", "real finding", "s0 or s1")
frule(f"...`{V[0]}` when the highest severity is S2, S3 or none", f"`{V[0]}`", "s2, s3 or `none`")
frule(f"...`{V[2]}` when the check could not do its work, before the other two", f"`{V[2]}`", "could not do its work",
      "before the other two")
frule("false hits never count", "false hits never count")
frule("the template: keep the shared top part and only the middle part with the check's name", "shared top part",
      "only the middle part", "check's name")
frule("...delete the other two middle parts, with all their text", "delete the other two middle parts", "all their text")
frule("...with every field replaced and every comment deleted", "{{field}}", "<!--")
frule("the Doc location of checks 1 and 2: the task branch at the push's commit, and the doc's file",
      "`<task branch> at <commit>, docs/validation/<file>`")
frule("...or 'Not in the repo', with why", "`not in the repo: <why>. the doc is in the task's result.`")
frule("the doc's own Doc location of checks 1 and 2: the task branch and the file, with no commit (it is written before the push)",
      "before its push", "`<task branch>, docs/validation/<file>`", "`agent/<task key>`")
frule("a failed or denied call: go on with the other steps, and try it again at most once", "fails or is denied", "go on",
      "at most once")
frule("...and name it under what the check could not check, with Domino's answer", '"what this check could not check"',
      "with domino's answer")
result = shared.result_block(rules_md, LABELS[0] if LABELS else "Verdict")
want = [f"{LABELS[0]}: {' | '.join(VERDICTS)}", f"{LABELS[1]}: {' | '.join(SEVERITIES)}", f"{LABELS[2]}: ", f"{LABELS[3]}: "]
got = [next((ln for ln in result if ln.startswith(w.split(":")[0] + ":")), None) for w in want]
check("the rules file gives the result's four lines, in order, with the labels of checks.json and its exact verdicts and severities",
      all(got) and got[:2] == want[:2] and all(g.startswith(w) for g, w in zip(got, want))
      and [result.index(g) for g in got] == sorted(result.index(g) for g in got), got)
frule("...as plain text, with no Markdown on those lines", "no markdown")

# ------------------------------------------------------------------------------------------------------------- the instructions
irule = shared.rules("the instructions say", instructions)   # one line of instructions.md says the rule
irule(f"load the skill {SLUG} first, and do its checklist in order", "first", f"skill {SLUG}", "in order")
irule("fill only its own evidence item", "only", "own evidence item", f'"{EVIDENCE}"')
irule("the rules that the three checks share are in the rules file, governance/rules.md: follow them", "governance/rules.md",
      "rules that the three checks share", "follow")
irule("file only the real findings of its own part, each named as the rules file says", "only the real findings", "own part",
      "governance/rules.md")
irule("...none for a known vulnerability nor for the data class: the other two checks' parts", "known vulnerability",
      f'"{SCAN_CHECK}"', "data class", f'"{PURPOSE}"', "file none")
irule("it runs no scan and starts no Job", "no scan", "no job")
irule("a false hit goes in the doc with its reason", "false hit", "doc", "reason")
irule("say what it could not check, as the rules file says, and a dry-run push too", "could not check", "governance/rules.md",
      "dry-run push")
irule("nobody answers an event task: no question and no access request", "nobody answers", "domino_ask_user", "domino_request_access")
irule("the checklist's writes are the task's work: no asking first", "push", "attachment", "findings", "evidence", "without asking")
irule("end with report_result, once, last, with the result of the rules file", "domino_report_result", "once", "last",
      "governance/rules.md")
irule(f"call the own tool {OWN} yourself, once, as the checklist says: the doc's route table comes from its rows", OWN,
      "yourself", "once", "route table", "rows")
irule("...when it fails, read the routes from the code, and the check goes on", OWN, "fails", "from the code", "goes on")
irule(f"give the route table to the custom subagent {SUBAGENT_NAME}, once, with the task tool, as the checklist says", SUBAGENT_NAME,
      "once", "task tool", "route table")
irule("...it only reviews: the main agent decides each finding and makes each write", "only reviews", "you decide", "each write")
irule("...when it gives no usable answer, judge the routes yourself: the check goes on", "no usable answer", "yourself", "goes on")
irule(f"the rules and the checklist are the main agent's: {SUBAGENT_NAME} follows only its own instructions and loads no skill (the "
      "operating rules reach each subagent too)", SUBAGENT_NAME, "main agent", "own instructions", "no skill")

# --------------------------------------------------------------------------------------------------------------- the tool names
# opencode names a tool of the relay's MCP server `domino` as domino_<name> (the service's agent_runtime/gateway.py)
NAMES = {"domino_get_bundle", "domino_get_policy", "domino_git_push", "domino_write_bundle_attachment",
         "domino_write_governance_finding", "domino_write_policy_result", "domino_report_result", "domino_ask_user",
         "domino_request_access"}   # the instructions name the last two only to forbid them
named = set(re.findall(r"\bdomino_[a-z_]+", skill + instructions))
check("the skill and the instructions name the checklist's Domino tools, and no other", named == NAMES, sorted(named ^ NAMES))
bare = sorted(set(re.findall(r"(?<![a-z_`])(?:get_bundle|get_policy|run_job|wait_job|git_push|write_[a-z_]+|report_result)\(",
                             skill + instructions)))
check("they call no tool by its plain name (a framework agent's name): a harness agent has only the domino_ names", not bare, bare)
owns = set(re.findall(r"\bown_[a-z_]+", skill + instructions))
check(f"they name one own tool, {OWN}: own_ and the name of the function with @tool in {TOOL}", owns == {OWN}, sorted(owns))

# ------------------------------------------------------------------------------------------------------------------ the own tool
# tools/route_table.py (spec #459, decision 4): a function with @tool from domino_agent. The service's own tool reader reads it in
# full below (with AGENT_SERVICE_REPO), and the unit test next to definition.md checks what it gives. This part checks what neither
# of them does: the tool uses the standard library only, and never imports or runs the App's code (it parses it with ast).
try:
    tree = ast.parse(tool_file)
except SyntaxError as e:
    tree = ast.Module(body=[], type_ignores=[])
    check(f"{TOOL} is valid Python", False, e)
marked = [n for n in tree.body if isinstance(n, ast.FunctionDef)
          and any(ast.unparse(d) in ("tool", "domino_agent.tool") for d in n.decorator_list)]
check(f"{TOOL} has one own tool, {TOOL_NAME}, with one argument, folder (a str): the agent sees it as {OWN}",
      [(n.name, [(a.arg, ast.unparse(a.annotation) if a.annotation else None) for a in n.args.args]) for n in marked]
      == [(TOOL_NAME, [("folder", "str")])], [ast.unparse(n.args) for n in marked])
imported = sorted({(n.module or "") if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(tree)
                   if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names})
tops = {m.split(".")[0] for m in imported}
RUNS = {"subprocess", "importlib", "runpy", "multiprocessing", "ctypes"}   # modules that import or run other code
check("...it imports only the standard library and domino_agent, and no module that imports or runs other code",
      tops <= (set(sys.stdlib_module_names) | {"domino_agent"}) - RUNS, imported)
runs_code = sorted({ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
                   & {"exec", "eval", "compile", "__import__", "os.system", "os.popen"})
check("...and it calls no exec, eval, compile, __import__, os.system or os.popen: it parses the App's code with ast.parse",
      not runs_code and "ast.parse" in tool_file, runs_code)

# ------------------------------------------------------------------------------------------------------- the custom subagent
# subagents/route-reviewer.md (spec #459, decision 5): the fields of domino-agent-service's docs/custom-subagents.md on top, its
# instructions below them. It reads only (tools [read], project read): no Domino tools, no shell, no own tool, no edit, no push. The
# service's own reading (domino_agent/subagents.py) is the deploy on Linux below, which also refuses a field that asks for more than
# the agent has.
sub_settings = fields_of(subagent)   # the same plain reading as definition.md's: `access.project` is a field of the group access
below = re.match(r"---\n.*?\n---\n(.*)", subagent, re.S)
sub_text = below.group(1).strip() if below else ""   # its instructions
SUB_WANT = {"name": SUBAGENT_NAME, "model": MODEL, "tools": "[read]", "access": "", "access.project": "read"}
check(f"{SUBAGENT}: the custom subagent {SUBAGENT_NAME}, with the agent's only model, {MODEL}, the tool read only, and Project "
      "files read (no domino, shell, own, edit or push: it can't call Domino, run a command, call the own tool or write a file)",
      {k: sub_settings.get(k) for k in SUB_WANT} == SUB_WANT, {k: (sub_settings.get(k), v) for k, v in SUB_WANT.items()
                                                              if sub_settings.get(k) != v})
check("...with a description (the main agent reads it to decide when to start it), the fields of a custom subagent only, and its "
      "instructions below them", re.search(r"^description: \S.{40,}$", subagent, re.M)
      and set(sub_settings) == {*SUB_WANT, "description"} and len(sub_text) > 200, sorted(sub_settings))
srule = shared.rules("the custom subagent's instructions say", sub_text)
srule("it reads the handler of each row at its file and line", "read", "handler of each row", "file and line")
srule("...one verdict for each row, with its method and path exactly as the table has them", "one verdict", "each row",
      "`method`", "`path`", "exactly")
srule("...the severity is on the shared scale of governance/rules.md, with its examples for this check", "governance/rules.md",
      "s0", "s3", "examples", f'"{NAME}"')
srule("...it judges only access: a known vulnerability and the data class are the other two checks' parts", "only access",
      "known vulnerability", f'"{SCAN_CHECK}"', "data class", f'"{PURPOSE}"')
srule("...it only reads: it files no finding, writes no file and changes nothing", "only read", "file no finding", "write no file")
srule("...the agent's rules and the checklist are the main agent's: it loads no skill", "main agent", "no skill")
answer = re.search(r"```json\n(.*?)\n```", sub_text, re.S)
try:
    form = json.loads(answer.group(1)) if answer else {}
except ValueError as e:
    form = {"not JSON": str(e)}
route_form = ((form.get("routes") or [{}])[0] if isinstance(form.get("routes"), list) else {}) if isinstance(form, dict) else {}
ROUTE_KEYS = ["method", "path", "who_can_call", "what_it_changes", "problem", "severity", "severity_reason", "evidence"]
check("...its answer is one JSON object, in a json block: for each route its method and path, who can call it, what it changes, a "
      "problem or none, a severity and its reason, and the evidence (each a file and line), and what it could not review",
      isinstance(form, dict) and sorted(form) == ["not_reviewed", "routes"] and list(route_form) == ROUTE_KEYS
      and isinstance(route_form.get("evidence"), list), form)
check("...a severity is one of S0, S1, S2, S3 or none", all(s in str(route_form.get("severity")) for s in [*SEVERITIES]),
      route_form.get("severity"))
sub_names = sorted(set(re.findall(r"\b(?:domino|own)_[a-z_]+", subagent)))
check("...it names no Domino tool and no own tool: it has none", not sub_names, sub_names)

# ------------------------------------------------------------------------------------------------- the event subscription's file
# subscriptions/bundle-enters-validation.md (domino-agent-service ADR 0049, ticket #398): `domino-agent deploy` (0.4.0 or later)
# makes the agent's subscription from it, and changes or removes it at each deploy. The settings on top are the service's
# domino_agent/triggers.py fields (event, filter, title, notify), and the text below them is the instruction template. The repo is
# public, so the filter names the demo project by its name, not by its Domino ID: any project with that name matches.
# This part and deployed_subscription() below are the two places of the subscription.
DEMO_PROJECT = "aml-validation-demo"   # the demo project's name (the seam part puts the seam's project name in its place)
PAYLOAD = shared.PAYLOAD   # the fields of a governance.bundle.stage_changed payload, as the service's audit poller builds it


def unquoted(value):
    """A YAML value as text: one in double quotes without them (JSON reads that form), else as it is."""
    try:
        return json.loads(value) if value.startswith('"') else value
    except ValueError:
        return value


def trigger_file(body):
    """A trigger file -> ({setting: value}, [condition of `filter` as {"field", "equals" or "contains"}], the instruction). Stdlib only,
    so a plain reading of the forms that this file uses: `key: value` lines on top (a comment line is skipped), and `filter:` with a
    `- field: ...` line and an `equals: ...` line below it for each condition. The service's own reading is the deploy on Linux."""
    m = re.match(r"---\n(.*?)\n---\n(.*)", body, re.S)
    if not m:
        return {}, [], ""
    top, conditions = {}, []
    for ln in m.group(1).splitlines():
        item, pair = re.match(r"^(  - |    )([a-z]+):\s*(.*?)\s*$", ln), re.match(r"^([a-z]+):\s*(.*?)\s*$", ln)
        if item:
            if item.group(1) == "  - ":
                conditions.append({})
            if conditions:
                conditions[-1][item.group(2)] = unquoted(item.group(3))
        elif pair:
            top[pair.group(1)] = unquoted(pair.group(2))
    return top, conditions, m.group(2).strip()


sub, conditions, instruction = trigger_file(subscription)
check(f"the folder has no subscription.json: its subscription is the file {SUB}, and deploy owns it (ADR 0049)",
      "subscription.json" not in every, sorted(every))
check(f"{SUB} is a subscription to governance.bundle.stage_changed, with the settings event, filter and title only (no notify: it "
      "writes nothing back)", sub.get("event") == "governance.bundle.stage_changed" and sorted(sub) == ["event", "filter", "title"],
      sub)
policy_yaml = text(ROOT / "governance" / "app-deployment-policy.yaml")
check(f"its filter: the bundle moved to the policy's stage named Validation (exact: the filter compares strings), in the project "
      f"named {DEMO_PROJECT} (a name, not a Domino ID)",
      conditions == [{"field": "toStage", "equals": "Validation"}, {"field": "project.name", "equals": DEMO_PROJECT}]
      and re.search(r"^  - name: Validation$", policy_yaml, re.M), conditions)
title = sub.get("title") or ""
check("its title template is the three checks' form, the check's name and the bundle ID (Validation status searches the title)",
      title == f"{NAME}: bundle {{{{bundle.id}}}}" and re.search(r'^title: "', subscription, re.M), title)
check("its instruction template, below the settings, names the bundle ID, the evidence item to fill, and the skill",
      "{{bundle.id}}" in instruction and f'"{EVIDENCE}"' in instruction and f"skill {SLUG}" in instruction, instruction)
fields = set(re.findall(r"\{\{([^}]+)\}\}", title + instruction))
check("each placeholder of the two templates is a field of the stage-change payload (a field that isn't stays as {{...}})",
      fields and fields <= set(PAYLOAD), sorted(fields - set(PAYLOAD)))

# The AML repo is public: no Domino host, no ID of a Domino object, no token in the folder (the live script fills the placeholder)
leaks = shared.leaks(every)   # the one leak pattern of the three checks (tests/three_checks.py, LEAK)
check("no file of the folder has a Domino host, the ID of a Domino object or a token", not leaks, leaks)
dashed = sorted(rel for rel, body in [*every.items(), (f"tests/{Path(__file__).name}", text(Path(__file__)))] if chr(0x2014) in body)
check("no file of the folder, and not this check, has an em dash", not dashed, dashed)
# The folder and its pull request are demo text (spec #459, scene 3b): the words of the two glossaries, never "lane"
laned = sorted(rel for rel, body in [*every.items(), ("this check's docstring", __doc__ or "")] if re.search(r"\blanes?\b", body, re.I))
check('no file of the folder, and not the docstring of this check, has the word "lane" (it is "a registered agent (opencode)")',
      not laned, laned)

# ------------------------------------------------------------------------------------------------------------ the folder's README
# The folder holds no user names and no trigger: its README says what the owner adds before the agent can run.
readme = every.get("README.md", "")
rrule = shared.rules("the folder's README says", readme)   # one line of the folder's README.md says it
rrule("it is the folder validator of spec #260 (the tag app-validation-two-ways keeps it), narrowed to its part", "#260",
      "app-validation-two-ways", "narrowed")
rrule("it links to the shared rules of the three checks, the rules file", "[governance/rules.md](../rules.md)")
rrule("it fills its own evidence item", f'"{EVIDENCE}"')
rrule("it runs no scan and no Job (Run a Job is off): known vulnerabilities are the Vulnerability scan's part", "no scan",
      "run a job", "off", f'"{SCAN_CHECK}"')
rrule("its doc's file on the task branch", f"`{DOC}`")
rrule("a task reads the Intake values that the analyst filled, with get_policy", "intake values", "analyst", "domino_get_policy")
check('the folder\'s README has the section "Before it can run"', "\n## Before it can run\n" in readme)
rrule("deploy it with a dry run first", f"domino-agent deploy --dry-run {PATH}")
rrule("the owner adds the service account and its token, else it can't run yet", "service account", "token", "can't run yet")
rrule("...and stores a new token before the old one expires", "token", "expires")
rrule("the service account's rights: Contributor on the demo project, the model, the bundle", "service account", "contributor",
      "llm gateway", "bundle")
rrule("the service account's Git credential, with write access to the repo (the push)", "git credential", "write access", "push")
rrule("the access rows, with attached Read & write for the event's bundle", "other resources attached to the task", "read & write",
      "bundle")
rrule("share it with the analyst who moves the stage", "share", "analyst", "moves the stage")
rrule("...and with the approver as an owner or an editor", "approver", "owner or an editor")
rrule(f"its file table names the subscription's file, {SUB}, and deploy uploads it", f"| `{SUB}` |", "| yes |")
rrule("domino-agent deploy, 0.4.0 or later, makes the subscription from its file (ADR 0049)", "domino-agent deploy", "0.4.0",
      "subscription", "adr 0049")
rrule("...an older command sends no trigger file: the agent gets no subscription", "before 0.4.0", "no subscription")
rrule(f"the filter names the demo project by its name, {DEMO_PROJECT}, so any project with that name matches", f"`{DEMO_PROJECT}`",
      "any project", "that name")
rrule("the first deploy prints the subscription's Trigger line", f"trigger: added subscription {SUB_NAME} ({SUB})")
rrule("a subscription of this agent made with the API before: delete it after the deploy, else each stage move starts two tasks",
      "api", "delete", "two tasks")
gone = [w for w in ("subscription.json", "__DEMO_PROJECT_ID__", "/api/agents/{id}/triggers") if w in readme]
check("the folder's README names no subscription.json, no project ID placeholder and no create through the API (deploy owns it)",
      not gone, gone)
rrule("the platform App polls the audit trail", "smoke_audit_poll_seconds")
rrule("...and pushes for real, else the push is a dry run and the doc isn't attached", "smoke_push_dry_run=0", "dry run", "attach")
rrule("the demo project's default branch has the shared rules", "default branch", "governance/rules.md", "governance/readme.md",
      "governance/validation-doc.md")
rrule("how to run this check", f"python tests/{Path(__file__).name}")
brule = shared.rules("the folder's README says", readme, units=shared.blocks)   # one paragraph, list item or table row says it
brule(f"its file table names the own tool's file, {TOOL}, and deploy uploads it", f"| `{TOOL}` |", "| yes |")
brule(f"...and the own tool's unit test, {UNIT_TEST}, which deploy does not upload", f"| `{UNIT_TEST}` |", "| no |")
check('the folder\'s README has the section "Its own tool"', "\n## Its own tool\n" in readme)
brule(f"the agent sees the own tool as {OWN}, a function with @tool from domino_agent", f"`{OWN}`", "`@tool`", "`domino_agent`")
brule("...it uses the standard library only (ast), and never imports or runs the App's code", "standard library", "`ast`",
      "never imports or runs")
brule("...its argument is the folder of the App's Python code, relative to the project folder", "`folder`",
      "relative to the project folder", "`case_server`")
brule("...each row: the kind, the method, the path, the handler with its file and line, the identity and the writes", "row",
      "method", "path", "handler", "file and line", "`reads_identity`", "`changes_state`")
brule("...not_read: each file that is not valid Python, and each decorator that the tool does not know", "`not_read`",
      "not valid python", "decorator")
brule("the main agent calls it once, itself, and the doc's route table comes from its rows", "once", "itself", "route table",
      "rows")
brule("...when the call fails, the agent reads the routes from the code, and that alone does not make the Verdict could not check",
      "fails", "from the code", "alone", "`could not check`")
brule("the unit test runs in the folder with python -m unittest", f"cd {PATH}", "python -m unittest")
brule("...it needs the domino-agent package or a domino-agent-service checkout on PYTHONPATH, and no network",
      "`domino-agent`", "`pythonpath`", "no network")
brule("...its run writes __pycache__/, which the repo's .gitignore ignores, else deploy refuses the folder", "`__pycache__/`",
      "`.gitignore`", "refuses")
brule(f"its file table names the custom subagent's file, {SUBAGENT}, and deploy uploads it", f"| `{SUBAGENT}` |", "| yes |")
check('the folder\'s README has the section "Its custom subagent"', "\n## Its custom subagent\n" in readme)
brule(f"the custom subagent {SUBAGENT_NAME} has the agent's model, the tool read only and Project files read", f"`{SUBAGENT_NAME}`",
      f"`{MODEL}`", "`tools: [read]`", "`project: read`")
brule("...so it can't call Domino, run a command, call the own tool or write a file", "can't call domino", "run a command",
      "own tool", "write a file")
brule("...the main agent gives it the route table, the Intake's Users and Data class and the access rules, in one task call",
      "one `task` call", "route table", "users", "data class", "access rules")
brule("...its answer is one JSON object with a verdict for each route", "json", "each route", "who can call it", "what it changes",
      "severity")
brule("...the main agent calls the own tool itself: a custom subagent's own-tool calls are not in the transcript and get no Activity "
      "log row", "itself", "own tool", "not in the transcript", "activity log")
brule(f"...the main agent decides and files the findings: {SUBAGENT_NAME} files nothing", "main agent", "decides", "files nothing")
brule(f"...with no usable answer, the main agent judges the routes itself, and that alone does not make the Verdict could not check",
      "no usable answer", "itself", '"what this check could not check"', "alone", "`could not check`")
brule("...the built-in subagent is off (subagents: false), and the custom subagent works with it off", "built-in subagent",
      "`subagents: false`", "works with it off")
brule("...the rules and the checklist reach the subagent too, so its instructions say that they are the main agent's",
      "operating rules", "main agent", "no skill")
check('the folder\'s README says "no subagents" nowhere: the built-in subagent is off, and it has a custom subagent',
      "no subagents" not in readme.lower())
brule("the check reads the custom subagent's file: its settings, its instructions and its answer form", f"`{SUBAGENT}`",
      "settings", "answer form")
brule("...and on Linux, deploy registers the custom subagent, and the Job's spec has it, read only", "deploy", "registers",
      "custom subagent", "job's spec", "read only")

# --------------------------------------------------------------------------------------------- the own tool's unit test
# test_route_table.py, as the README says to run it (python -m unittest, in the folder). It needs domino_agent: the domino-agent
# package of this Python, or the package of the AGENT_SERVICE_REPO checkout. -B: no __pycache__ (the folder can be read only).
SERVICE_REPO = os.environ.get("AGENT_SERVICE_REPO", "").strip()   # the one read of it: the unit test, and the service parts below
service = Path(SERVICE_REPO).expanduser().resolve() if SERVICE_REPO else None   # the domino-agent-service checkout, or None
env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
package = importlib.util.find_spec("domino_agent") is not None
if not package and service and (service / "domino_agent" / "__init__.py").is_file():
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(service), env.get("PYTHONPATH")) if p)
    package = True
if not package:
    print("SKIP: this Python has no domino_agent (no domino-agent package and no AGENT_SERVICE_REPO), so the own tool's unit test, "
          f"{UNIT_TEST}, did not run ({PATH}/README.md, \"Its unit test\")", flush=True)
elif UNIT_TEST in every:
    ran = subprocess.run([sys.executable, "-B", "-m", "unittest", "-v"], cwd=FOLDER, env=env, capture_output=True, text=True,
                         timeout=120)
    count = re.search(r"^Ran (\d+) tests? in", ran.stderr, re.M)
    result_lines = [ln for ln in ran.stderr.splitlines() if ln.startswith(("FAIL:", "ERROR:", "Ran ", "OK", "FAILED"))]
    check(f"the own tool's unit test passes ({UNIT_TEST}, python -m unittest in the folder): on the App's code, the demo branch's "
          "POST /upload and small sample files", ran.returncode == 0 and count and int(count.group(1)) > 0
          and ran.stderr.rstrip().endswith("OK"), result_lines or ran.stderr[-600:])
check(f"governance/README.md (the shared rules, the hub of the three checks) names this folder, {PATH}/",
      f"`{PATH}/`" in text(ROOT / "governance" / "README.md"))

if not service:
    done("AGENT_SERVICE_REPO is not set, so the tool names, the deploy and the event's task weren't checked against the service. Set "
         f"it to a domino-agent-service checkout ({PATH}/README.md, \"The check\")")
if not (service / "agent_runtime" / "gateway.py").is_file() or not (service / "agent_runtime" / "proxies.py").is_file():
    check(f"AGENT_SERVICE_REPO ({service}) is a domino-agent-service checkout (agent_runtime/gateway.py and proxies.py)", False)
    done()
sys.path.insert(0, str(service))
from agent_runtime import gateway, proxies  # noqa: E402  (stdlib only, so any OS)

offered = {f"domino_{n}" for n in gateway.TOOLS} | {f"domino_{n}" for n in proxies.RELAY_TOOLS}
check("each tool that they name is a gateway tool or a relay tool of this service, as opencode names it (domino_<name>)",
      named and named <= offered, sorted(named - offered))
from domino_agent import own_tools  # noqa: E402  (the service's own tool reader: stdlib only, so any OS)

found = own_tools.read({TOOL: tool_file})
TOOL_ENTRY = {"name": TOOL_NAME, "args": [{"name": "folder", "type": "str", "optional": False}], "file": TOOL}
check(f"the service's own tool reader reads {TOOL} with no refusal: one own tool, {TOOL_NAME}, with one argument, folder (a str), "
      "and its docstring as its description", not found.problems and [{k: x.get(k) for k in TOOL_ENTRY} for x in found.tools]
      == [TOOL_ENTRY] and found.tools[0].get("description", "").startswith("The table of the ways into a Python App"),
      found.problems or [{k: v for k, v in x.items() if k != "description"} for x in found.tools])

# --------------------------------------------------------------------------------------------------------------- the deploy
if not files:
    done()   # the first part said why: there is no folder to deploy
if not (service / "tests" / "agent_folder_seam.py").is_file() or not (service / "domino_agent" / "deploy.py").is_file():
    check(f"AGENT_SERVICE_REPO ({service}) has the agent folder (tests/agent_folder_seam.py and domino_agent/)", False)
    done()
if not sys.platform.startswith("linux"):
    done("needs Linux for the deploy and the event's task: the service's app imports agent_runtime/sandbox.py. On a Mac, run it "
         f"with Docker, in the image of the service's checks ({PATH}/README.md, \"The check\")")
sys.path.insert(0, str(service / "tests"))
import agent_folder_seam as seam  # noqa: E402  (the service's seam helper, from AGENT_SERVICE_REPO)

seam.GATEWAY.append({"id": MODEL, "providerType": "openai", "capabilities": ["chat", "tools"]})   # an OpenAI-format alias, not in the seam
seam.start()
OWNER, ANALYST, APPROVER, SA = "olivia", "rita", "bob", "check-sa"   # people the seam's fake Domino knows, and the service account
TITLE = NAME   # the agent's title is the check's name (spec #388 decision 5)
REMOTE = "https://github.com/ddl-subir-m/aml-alert-triage.git"
LOCAL = seam.PROJECT["name"]   # the seam's one project: a task resolves its project by ID, and refuses a payload with another name
# The whole folder, as git has it (deploy uploads only the known paths), with the seam's project name in place of the demo project's
# name in the subscription's filter: the files part above checks the literal value of the file in git
repo = seam.Repo({k: v.replace(DEMO_PROJECT, LOCAL) if k == SUB else v for k, v in every.items()}, path=PATH, remote=REMOTE)


def registered():
    """The agent that the folder's `name` registered, as its owner sees it, or None."""
    agents = seam.api("GET", "/api/agents", OWNER).json()
    return next((a for a in agents if (a.get("registration") or {}).get("name") == SLUG), None)


def trigger_lines(out):
    """The lines of deploy's output that name a trigger (the service's domino_agent/triggers.line)."""
    return [x for x in out.splitlines() if x.startswith("  Trigger: ")]


ran = seam.command("deploy", "--dry-run", PATH, cwd=repo.root, person=OWNER)
check("deploy --dry-run passes the service's folder rules: it would create the agent, and registers nothing",
      ran.code == 0 and f"Dry run: would create {TITLE}" in ran.out and "Dry run: nothing was registered." in ran.out
      and registered() is None, ran)
changed = re.search(r"^  Changed: (.*)$", ran.out, re.M)
check(f"...its Changed line names the own tool's file, {TOOL}, and the custom subagents, subagents (the service names the folder, "
      "not the file), and not the unit test or the README",
      changed and {TOOL, "subagents"} <= set(changed.group(1).split(", "))
      and not {UNIT_TEST, "README.md"} & set(changed.group(1).split(", ")), changed.group(0) if changed else ran.out)
check(f"...and it says that it would add the subscription from its file, {SUB}",
      trigger_lines(ran.out) == [f"  Trigger: would add subscription {SUB_NAME} ({SUB})"], trigger_lines(ran.out) or ran.out)
ran = seam.command("deploy", PATH, cwd=repo.root, person=OWNER)
check("deploy registers it, and says that it can't run yet: it acts as a service account, and none is chosen",
      ran.code == 0 and ran.out.startswith(f"Created {TITLE} (agt_") and "Can't run yet" in ran.out and "service account" in ran.out, ran)
check(f"...and it adds the subscription from its file, {SUB} (the line that the live script looks for)",
      trigger_lines(ran.out) == [f"  Trigger: added subscription {SUB_NAME} ({SUB})"], trigger_lines(ran.out) or ran.out)
a = registered() or {}
aid = a.get("id")
check(f"the agent is a harness agent named {TITLE} (the check's name), owned by the person who deployed it",
      a.get("lane") == "harness" and a.get("name") == TITLE and (a.get("owner") or {}).get("userName") == OWNER,
      (a.get("lane"), a.get("name"), a.get("owner")))
rec = a.get("registration") or {}
check("its Registration names the AML repo, the folder's path, the commit and a clean folder",
      rec.get("repo") == REMOTE and rec.get("path") == PATH and rec.get("commit") == repo.head and rec.get("clean") is True, rec)
check("its identity is a service account (the owner chooses which one, and adds its token)",
      (a.get("identity") or {}).get("mode") == "service_account", a.get("identity"))
g = a.get("guardrails") or {}
check("it runs no Job and pushes its task branch, with the built-in subagent off (Run a Job: off, Git push: on, Subagents: off)",
      {k: (g.get("tools") or {}).get(k) for k in ("jobs", "push", "subagents")} == {"jobs": False, "push": True, "subagents": False},
      g.get("tools"))
check("its Resource access: Project files Read & write, Project datasets No access, attached Read & write, not attached No access",
      {k: (g.get("access") or {}).get(k) for k in ("project", "data", "named", "other")}
      == {"project": "write", "data": "none", "named": "write", "other": "none"}, g.get("access"))
check("a failure ends the task with a report (on-error: fail): nobody unblocks an event task", a.get("onError") == "fail", a.get("onError"))
check("its limits: 45 minutes, 120 turns, and no wait for an answer",
      {k: (a.get("execution") or {}).get(k) for k in ("maxRuntimeMin", "maxTurns", "idleWaitMin")}
      == {"maxRuntimeMin": 45, "maxTurns": 120, "idleWaitMin": 0}, a.get("execution"))
check(f"its model is the LLM Gateway alias {MODEL}", (a.get("model") or {}).get("models") == [MODEL], a.get("model"))
check("its system prompt is instructions.md", a.get("systemPrompt") == instructions.strip(), (a.get("systemPrompt") or "")[:200])
own = a.get("ownSkills") or []
check(f"its own skill is {SLUG}, with its description and one file, SKILL.md (the API shows no text: the Job's spec has it)",
      [(s.get("name"), s.get("files")) for s in own] == [(SLUG, ["SKILL.md"])]
      and own[0].get("description") and own[0]["description"] in skill, own)
tools_of = a.get("ownTools") or {}
check(f"deploy registers the own tool {TOOL_NAME} from {TOOL}, with its argument folder, and only that file of tools/ (the API "
      "shows no text)", tools_of.get("files") == [TOOL]
      and [{k: x.get(k) for k in TOOL_ENTRY} for x in tools_of.get("tools") or []] == [TOOL_ENTRY], tools_of)
SUB_DESCRIPTION = sub_settings.get("description")   # one line of plain YAML, as the file part above checks
check(f"deploy registers the custom subagent {SUBAGENT_NAME} from {SUBAGENT}: the agent's model, read only, Project files read, and "
      "its instructions", a.get("customSubagents") == [
          {"name": SUBAGENT_NAME, "file": SUBAGENT, "description": SUB_DESCRIPTION, "model": MODEL, "tools": ["read"],
           "access": {"project": "read"}, "instructions": sub_text}], a.get("customSubagents"))

# ------------------------------------------------------------------------------------- the subscription and the event's task
# The deploy made the subscription from its file (deployed_subscription() reads it back), with the seam's project name in its filter. A
# stage move reaches it as the audit poller publishes it (tests/three_checks.py: stage_move and fire), with the event bundle's GET.
BUNDLE = shared.BUNDLE
put_back_get = shared.serve_bundle(BUNDLE, seam.PROJECT)
stage_move = partial(shared.stage_move, seam, BUNDLE, by=ANALYST)   # stage_move(to, project, by=): the payload of one stage move


def deployed_subscription():
    """The agent's event subscription, as deploy made it from its file: the item of GET /api/agents/{id}/triggers whose `file` is the
    file's path (a trigger with no `file` is a browser trigger; the list also has the direct trigger). -> the stored trigger, or {}."""
    listed = seam.api("GET", f"/api/agents/{aid}/triggers", OWNER).json()
    listed = listed if isinstance(listed, list) else []
    made = next((t for t in listed if t.get("file") == SUB), {})
    check(f"the agent has one subscription, from its file {SUB}, on, with the file name {SUB_NAME} as its name",
          [t.get("file") for t in listed if t.get("type") != "direct"] == [SUB] and made.get("type") == "event"
          and made.get("name") == SUB_NAME and made.get("enabled") is True, listed)
    check(f"...with the file's event type and filter, in the project named {LOCAL} (the seam's, in place of {DEMO_PROJECT})",
          made.get("event") == {"eventType": "governance.bundle.stage_changed",
                                "filter": [{"field": "toStage", "op": "equals", "value": "Validation"},
                                           {"field": "project.name", "op": "equals", "value": LOCAL}]}, made.get("event"))
    check("...with the file's two templates, no pinned resource and no write-back",
          made.get("titleTemplate") == title and made.get("instructionTemplate") == instruction
          and made.get("defaultResources") == [] and made.get("writeBack") == [],
          {k: made.get(k) for k in ("titleTemplate", "instructionTemplate", "defaultResources", "writeBack")})
    return made


trigger = deployed_subscription()
fire = partial(shared.fire, seam, trigger)   # fire(payload, person): the event's fired list


fired = fire(stage_move(by=OWNER), OWNER)
check("before the owner adds the service account and its token, a stage move starts no task: the agent can't run yet",
      isinstance(fired, list) and len(fired) == 1 and "can't run yet" in (fired[0].get("error") or "") and not fired[0].get("taskId"), fired)
token = seam.add_person(SA)
r = seam.api("PUT", f"/api/agents/{aid}", OWNER, json={"identity": {"mode": "service_account", "serviceAccount": {"userName": SA}},
                                                     "identityCredentialToken": token})
check("the owner adds the service account and its token (the wizard's Identity & sharing step, here through the API)",
      r.status_code == 200 and ((registered() or {}).get("identityCredential") or {}).get("status") == "active", (r.status_code, r.text[:300]))
fired = fire(stage_move(), ANALYST)
check("a stage move by an analyst who may not use the agent starts no task: share the agent with the analyst who moves the stage",
      isinstance(fired, list) and len(fired) == 1 and "is not allowed to use agent" in (fired[0].get("error") or ""), fired)
r = seam.api("PUT", f"/api/agents/{aid}", OWNER, json={"access": {"mode": "restricted", "users": [ANALYST], "editors": [APPROVER]}})
check("the owner shares it: the analyst as a user, the approver as an editor", r.status_code == 200, (r.status_code, r.text[:300]))
n = len(seam.JOBS)
fired = fire(stage_move(), ANALYST)
check("then a stage move to Validation in the demo project starts one task, which acts as the service account, not as the analyst",
      isinstance(fired, list) and len(fired) == 1 and fired[0].get("taskId") and fired[0].get("actingAs") == SA, fired)
task_id = fired[0].get("taskId") if isinstance(fired, list) and fired else None
task = seam.api("GET", f"/api/tasks/{task_id}", OWNER).json() if task_id else {}
check("the task's title is the check's name and the bundle ID (so the scripted check finds it), from the title template",
      task.get("title") == f"{TITLE}: bundle {BUNDLE['id']}", task.get("title"))
check("its instruction names the bundle ID and its own evidence item, from the instruction template",
      BUNDLE["id"] in (task.get("instruction") or "") and f'"{EVIDENCE}"' in (task.get("instruction") or "")
      and "{{" not in (task.get("instruction") or ""), task.get("instruction"))
r = seam.api("GET", f"/api/tasks/{task_id}", APPROVER)
check("the approver (an editor) can read the task, as the scripted check does", r.status_code == 200, r.status_code)
job = shared.new_job(seam, n)
check("its Domino Job starts at once, in the bundle's project, as the service account (its stored token)",
      job.get("credential") == ("bearer", token) and (job.get("body") or {}).get("projectId") == seam.PROJECT["id"],
      (len(seam.JOBS) - n, job.get("credential")))
spec = shared.spec_of(seam, job) if job else {}   # the Job's claim and its spec, as its bootstrapper reads them
rules = str(spec.get("operatingRules") or "")
check("the Job's spec has the instructions at the top of the agent's rules, and the access rows as the folder sets them",
      rules.startswith(instructions.strip() + "\n\n## Operating rules") and "Project files: read & write. Project datasets: no access. "
      "Other resources attached to the task: read & write." in rules, rules[:300])
own_spec = spec.get("ownTools") or {}
check(f"the Job's spec has the own tool: the text of {TOOL} and the tool {TOOL_NAME}, with the limits of a call",
      own_spec.get("files") == {TOOL: tool_file} and [x.get("name") for x in own_spec.get("tools") or []] == [TOOL_NAME]
      and own_spec.get("timeoutSeconds") and own_spec.get("maxResultBytes"),
      {k: (sorted(v) if k == "files" else v) for k, v in own_spec.items() if k != "tools"})
oc = spec.get("opencodeConfig") or {}
oc_agents = oc.get("agent") or {}   # opencode's agent block: build (the main agent), the custom subagent, general and explore


def permission_of(name):
    """The permission map of the entry `name` of opencode's agent block, or {}."""
    return (oc_agents.get(name) or {}).get("permission") or {}


check(f"...and opencode gets the own tools' server, own, and the main agent may call {OWN} (own_*: allow)",
      "own" in (oc.get("mcp") or {}) and permission_of("build").get("own_*") == "allow",
      {"mcp": sorted(oc.get("mcp") or {}), "build": oc_agents.get("build")})
provider = next(iter(oc.get("provider") or {}), "(no provider)")
compiled = oc_agents.get(SUBAGENT_NAME) or {}
check(f"the Job's spec has the custom subagent {SUBAGENT_NAME}: a subagent of opencode with its description, the agent's model and "
      "its instructions", {k: compiled.get(k) for k in ("description", "mode", "model", "prompt")}
      == {"description": SUB_DESCRIPTION, "mode": "subagent", "model": f"{provider}/{MODEL}", "prompt": sub_text},
      {k: compiled.get(k) for k in ("description", "mode", "model")})
sub_perm, main_perm = permission_of(SUBAGENT_NAME), oc.get("permission") or {}
# domino_write_project_*: the service denies the project's write tools for `access.project: read` (agent_service/custom_subagents.py,
# WRITES): the proof of Project files read
DENIED = ("edit", "bash", "webfetch", "websearch", "domino_*", "domino_run_job", "domino_git_push", "domino_write_project_*", "task",
          "own_*")
check("...it may read the project's files as the main agent does, and nothing more: no edit, no shell, no web, no Domino tool, no "
      "Job, no push, no write to the project (Project files read), no subagent and no own tool",
      sub_perm.get("read") == main_perm.get("read") and sub_perm.get("read")
      and {k: sub_perm.get(k) for k in DENIED} == dict.fromkeys(DENIED, "deny"), {k: sub_perm.get(k) for k in ("read", *DENIED)})
check("...the main agent may start it (task: allow), and the built-in subagent stays off (opencode's general and explore disabled)",
      main_perm.get("task") == "allow" and {k: oc_agents.get(k) for k in ("general", "explore")}
      == {"general": {"disable": True}, "explore": {"disable": True}}, (main_perm.get("task"), sorted(oc_agents)))
check(f"...and the agent's rules name {SUBAGENT_NAME} with its description, and say that the built-in subagent is off",
      f"`{SUBAGENT_NAME}`: {SUB_DESCRIPTION}" in rules and "The built-in subagent is off" in rules, rules[-600:])
skills = [(s.get("name"), s.get("own"), s.get("content")) for s in spec.get("skills") or []]
check(f"the Job gets the own skill {SLUG} with the checklist's text, at the commit that was deployed",
      skills == [(SLUG, True, skill)] and (spec.get("skills") or [{}])[0].get("commit") == repo.head, [s[:2] for s in skills])
perm = ((spec.get("opencodeConfig") or {}).get("permission")) or {}
check("opencode may call the Domino tools and push, and may not run a Job (the Job's permissions)",
      {k: perm.get(k) for k in ("domino_*", "domino_run_job", "domino_git_push", "skill")}
      == {"domino_*": "allow", "domino_run_job": "deny", "domino_git_push": "allow", "skill": "allow"}, perm)
check("the Job ends a failure with a report (onError fail), pushes to the task branch, runs no Job, and has the folder's limits",
      spec.get("onError") == "fail" and spec.get("tools") == {"push": True, "jobs": False}
      and (spec.get("push") or {}).get("branch") == f"agent/{task.get('key')}"
      and spec.get("limits") == {"maxMinutes": 45, "maxTurns": 120, "idleWaitMin": 0},
      {k: spec.get(k) for k in ("onError", "tools", "push", "limits")})

# What the gateway decides for this task (the same decide() the agent service runs on each call), on the event's bundle
policy = spec.get("gateway") or {}
bundle = next((x for x in policy.get("resources") or [] if x.get("type") == "bundle"), {})
check("the event's bundle is a resource of the task, Read & write (the row 'Other resources attached to the task')",
      bundle.get("id") == BUNDLE["id"] and bundle.get("access") == "write", policy.get("resources"))
CALLS = {
    "write_bundle_attachment": {"bundleId": BUNDLE["id"], "type": "Report", "identifier": {
        "filename": DOC.replace("<bundleId>", BUNDLE["id"]), "commit": "0" * 40, "source": "GBP", "branch": "agent/AGT-1"}},
    "write_governance_finding": {"bundleId": BUNDLE["id"], "name": f"[{NAME}] Anyone who can open the App can delete all state in "
                                 "POST /reset", "severity": "S1", "description": "Evidence."},
    # the checklist's call, by the names that it gives (the files part checks them against checks.json)
    "write_policy_result": {"bundleId": BUNDLE["id"], **({"evidenceName": CALLED} if CALLED else {}),
                            "content": {k: SAMPLE.get(k, "?") for k in CALLED_KEYS}},
}
for name, args in CALLS.items():
    d = gateway.decide(name, args, policy) if policy else {}
    check(f"the gateway allows {name} on the event's bundle, by its own row (named), with no owner check",
          d.get("allow") is True and d.get("row") == "named" and not any(s.get("expect") for s in d.get("steps") or []),
          {k: d.get(k) for k in ("allow", "row", "why")})
d = gateway.decide("write_policy_result", CALLS["write_policy_result"], policy) if policy else {}
out, sent, pol = shared.submit(gateway, d, CHECKS, seam.PROJECT) if d.get("allow") else ({}, [], {})
own_item = next((e for st in pol.get("stages") or [] for e in st["evidenceSet"] if e["name"] == EVIDENCE), {})
ids = {a["details"]["label"]: a["id"] for a in own_item.get("artifacts") or []}
check(f"...and the result by names reaches Domino as IDs: the gateway finds {EVIDENCE!r} and its four fields in the bundle's "
      "policy, and Domino gets their IDs, with the values as they are (the result lands where a result by IDs lands)",
      out.get("ok") is True and own_item and sent == [{"bundleId": BUNDLE["id"], "policyId": pol["id"], "evidenceId": own_item["id"],
                                                       "content": {ids.get(k): SAMPLE[k] for k in LABELS}}], (out, sent))
d = gateway.decide("git_push", {"message": "The doc"}, policy) if policy else {}
check("...and git_push, in the task's project", d.get("allow") is True, {k: d.get(k) for k in ("allow", "row", "why")})
d = gateway.decide("run_job", {"command": "python app.py"}, policy) if policy else {}
check("...but no run_job: Start Domino jobs is off for this agent", d.get("allow") is False
      and "Start Domino jobs is off" in (d.get("why") or ""), {k: d.get(k) for k in ("allow", "row", "why")})
d = gateway.decide("get_dataset", {"datasetId": "ds-of-the-project"}, policy) if policy else {}
check("...but no dataset of the project (Project datasets: No access)", d.get("allow") is False
      and "Project datasets is No access" in (d.get("why") or ""), {k: d.get(k) for k in ("allow", "row", "why")})
listed = {f"domino_{t['name']}" for t in gateway.tool_defs(policy)} | {f"domino_{t}" for t in proxies.RELAY_TOOLS
                                                                        if t != "submit_plan"} if policy else set()
check("each tool that the skill and the instructions name is one that this task's agent is offered, and run_job is not",
      named <= listed and "domino_run_job" not in listed, sorted(named - listed) or sorted(listed))

fired = [fire(stage_move("Approval"), ANALYST), fire(stage_move(project=("p-other", "another-project")), ANALYST)]
check("a stage move to another stage, or to Validation in another project, starts nothing (the filter)", fired == [[], []], fired)
put_back_get()

# A later deploy of the same commit keeps the subscription: the file name is its identity (ADR 0049, decision 4)
ran = seam.command("deploy", PATH, cwd=repo.root, person=OWNER)
kept = [t for t in seam.api("GET", f"/api/agents/{aid}/triggers", OWNER).json() if t.get("file")]
check("a second deploy of the same commit changes nothing: no Trigger line, and the subscription keeps its ID and stays on",
      ran.code == 0 and "No change for" in ran.out and not trigger_lines(ran.out)
      and [(t.get("id"), t.get("enabled")) for t in kept] == [(trigger.get("id"), True)], (ran, kept))

seam.close()
done()
