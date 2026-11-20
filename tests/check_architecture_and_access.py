"""Check 2, Architecture and access (governance/check-architecture-and-access/): a registered agent of the harness lane (opencode),
an agent folder that `domino-agent deploy` registers (domino-agent-service spec #388, Implementation Decision 9, ticket #394). It is
the folder validator of spec #260 (the tag app-validation-two-ways keeps it), narrowed to its part: no scan, Run a Job off. Seen from
outside: its files as `domino-agent deploy` uploads them, its checklist skill as the agent reads it, the templates of its event
subscription (its file in the folder, ADR 0049 of domino-agent-service, ticket #398), and the agent that a local agent service
registers from it.

The names come from governance/checks.json (the check's name, its evidence item, the field labels, the verdicts and the severities),
and the rules from governance/README.md and governance/validation-doc.md (the shared rules of the three checks).

With no service, it checks the folder's files: the ones that deploy uploads, the settings of definition.md, the checklist's rules and
the order of its tools, the instructions' rules, the tool names (as a harness agent sees them: domino_<name>), the subscription's file
(subscriptions/bundle-enters-validation.md: its filter on the demo project's name and its two templates, which name the bundle ID), no
Domino host or ID (the repo is public), and the folder's README.

With the service (AGENT_SERVICE_REPO, the path of a domino-agent-service checkout), it checks each tool name against the service's
gateway and relay (agent_runtime/gateway.py and proxies.py: stdlib, any OS). On Linux, it also starts that service over real HTTP with
a fake Domino (the service's seam helper, tests/agent_folder_seam.py), with the folder committed in a temporary clone:
  - `domino-agent deploy --dry-run` passes the service's folder rules; `deploy` registers the agent, which can't run yet, and adds
    the subscription from its file (with the seam's project name in place of the demo project's name in the temporary clone).
  - A stage move (the audit poller's payload) starts no task before the service account's token, nor for an analyst who may not use
    the agent; then one task, as the service account, and its Job.
  - The Job's spec (the skill, the access rows, Run a Job off, Git push on, the permissions, the limits) and the gateway's decisions
    for that task on the event's bundle: the attachment, the findings and the evidence are allowed by the row "Other resources
    attached to the task", and run_job is denied.
  - A stage move to another stage, or in another project, starts nothing. A second deploy of the same commit keeps the subscription.
With AGENT_SERVICE_REPO unset, or not on Linux, those parts print a SKIP line. No Domino host: the live run is domino-agent-service
#397.

  python tests/check_architecture_and_access.py                                                   # the files only
  AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_architecture_and_access.py   # on Linux: everything (README)
"""
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = "governance/check-architecture-and-access"   # the folder, as checks.json names it
FOLDER = ROOT / PATH
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
try:
    CHECKS = json.loads(text(ROOT / "governance" / "checks.json"))
except ValueError as e:
    CHECKS = {"error": str(e)}
CHECKS = CHECKS if isinstance(CHECKS, dict) else {}
me = next((c for c in CHECKS.get("checks") or [] if isinstance(c, dict) and c.get("folder") == PATH), {})
check(f"governance/checks.json has this check, with its folder {PATH}, its name and its evidence item",
      bool(me.get("name") and me.get("evidenceItem")), CHECKS.get("error") or CHECKS.get("checks"))
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
UPLOADED = ("definition.md", "instructions.md", SKILL, SUB)   # what deploy uploads of the folder

# --------------------------------------------------------------------------------------------------------------------- the files
every = {p.relative_to(FOLDER).as_posix(): p.read_text() for p in sorted(FOLDER.rglob("*")) if p.is_file()} if FOLDER.is_dir() else {}
files = {k: v for k, v in every.items() if known(k)}
check(f"{PATH}/ uploads definition.md, instructions.md, one own skill, {SLUG}, and one subscription file, {SUB}, and nothing else",
      sorted(files) == sorted(UPLOADED), sorted(files))
settings, instructions, skill, subscription = (files.get(k, "") for k in UPLOADED)
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
lines = [ln.lower() for ln in skill.splitlines()]


def rule(name, *words):
    """One line of the skill says the rule: it holds every one of `words` (case aside)."""
    check(f"the skill says: {name}", any(all(w.lower() in ln for w in words) for ln in lines), words)


rule("read the bundle first", "domino_get_bundle", "bundleid")
rule("read the policy with the bundle's ID", "domino_get_policy", "bundleid")
rule("find its evidence item by its exact name (checks.json), and keep its ID", f'"{EVIDENCE}"', "evidence item", "exact", "id")
rule("find each of the four fields by its label (checks.json)", "details.label", *(f'"{label}"' for label in LABELS))
rule("a radio field takes one of its options' values", "radio", "details.options", "value")
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

# The evidence values, by the shared rules (governance/README.md, "The evidence fields" and "The severity scale")
rule("the severity scale is governance/README.md's, S0 to S3, with its examples for each check", "governance/readme.md", "s0", "s3",
     "examples")
rule("a real finding's name is [Architecture and access] <what> in <where>", f"`[{NAME}] <what> in <where>`")
rule("Highest severity is the highest severity of its real findings, or none", "highest severity", "real findings", "`none`")
rule(f"the verdict is `{V[1]}` when a real finding is S0 or S1", f"`{V[1]}`", "real finding", "s0 or s1")
rule(f"...`{V[0]}` when the highest severity is S2, S3 or none", f"`{V[0]}`", "s2, s3 or `none`")
rule(f"...`{V[2]}` when the check could not do its work", f"`{V[2]}`", "could not do its work")
rule("false hits never count, and none is filed", "false hit", "never count", "no false hit")

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
rule("...keeps the shared top part and only its own middle part, and deletes the other two", f"`## {NAME}`", "delete",
     *(f"`## {o}`" for o in OTHERS))
rule("...with every field replaced and every comment deleted", "{{field}}", "<!--")
unsaid = sorted(f for f in mine if f"`{f}`" not in skill)
check("the skill says how to fill each field of the top part and of its own middle part (the template's fields)", mine and not unsaid,
      unsaid)
said = sorted(f for f in theirs if f"`{f}`" in skill)
check("...and names no field of the other two middle parts only", not said, said)
rule("the doc's check is the check's name", "`check`", f"`{NAME}`")
rule("the doc's own doc location names only the file and the task branch, with no commit (it is written before the push)",
     "`doc_location`", "no commit")
rule("the doc says what the check could not check, always the default branch", "`could_not_check`", "default branch")

# The push, the attachment, the findings, the evidence and the result
rule("push the doc with git_push, and keep its ok, branch, commit and dryRun", "domino_git_push", "`ok`", "branch", "commit", "dryrun")
rule("attach the doc: a Report from GBP, with the task branch and the push's commit", "domino_write_bundle_attachment", '"report"',
     '"gbp"', "branch", "commit", DOC)
rule("...only when the push is on the remote (ok true, dryRun false)", "only when", "`ok` true", "dryrun", "false")
rule("a dry-run push: attach nothing, and say so under what the check could not check", "dryrun", "true", "attach nothing",
     "could not check")
rule("a failed push (ok false): attach nothing, and say why", "`ok` is false", "attach nothing", "why")
rule("file each real finding with its name and severity, and no false hit", "domino_write_governance_finding",
     f'"[{NAME}] <what> in <where>"', "severity", "no false hit")
rule("fill only its own evidence item, by the IDs from get_policy", "domino_write_policy_result", "only", f'"{EVIDENCE}"', "evidenceid")
rule("...with its four fields, by their IDs", "domino_write_policy_result", *(f"<{label} id>" for label in LABELS))
rule("the doc location: the task branch at the push's commit, and the doc's file", f"`<branch> at <commit>, {DOC}`")
rule("...or 'Not in the repo', with why", "`not in the repo: <why>. the doc is in the task's result.`")
rule("a failed or denied call: go on with the other steps, and name it under what the check could not check", "fail", "denied",
     "go on", "could not check")
rule("the result goes to report_result, once, last", "domino_report_result", "once", "last")

order = ["domino_get_bundle", "domino_get_policy", "domino_git_push", "domino_write_bundle_attachment",
         "domino_write_governance_finding", "domino_write_policy_result", "domino_report_result"]
at = [skill.find(t) for t in order]
check("the checklist's tools come in order: bundle and policy, push, attachment, findings, evidence, result",
      all(i >= 0 for i in at) and at == sorted(at), dict(zip(order, at)))
steps = [int(n) for n in re.findall(r"^## (\d+)\. ", skill, re.M)]
check("the checklist is numbered steps, in order", len(steps) >= 8 and steps == list(range(1, len(steps) + 1)), steps)
check("each step ends with its completion criterion (a 'Done when' line)",
      steps and all("Done when:" in part for part in re.split(r"^## \d+\. ", skill, flags=re.M)[1:]), steps)
result = [ln.strip() for ln in re.split(r"^## \d+\. ", skill, flags=re.M)[-1].splitlines()]
want = [f"{LABELS[0]}: {' | '.join(VERDICTS)}", f"{LABELS[1]}: {' | '.join(SEVERITIES)}", f"{LABELS[2]}: ", f"{LABELS[3]}: "]
got = [next((ln for ln in result if ln.startswith(w.split(":")[0] + ":")), None) for w in want]
check("the last step gives the result's four lines, in order, with the labels of checks.json and its exact verdicts and severities",
      all(got) and got[:2] == want[:2] and all(g.startswith(w) for g, w in zip(got, want))
      and [result.index(g) for g in got] == sorted(result.index(g) for g in got), got)
rule("...as plain text, with no Markdown on those lines", "no markdown")

# ------------------------------------------------------------------------------------------------------------- the instructions
ilines = [ln.lower() for ln in instructions.splitlines()]


def irule(name, *words):
    """One line of instructions.md says the rule: it holds every one of `words` (case aside)."""
    check(f"the instructions say: {name}", any(all(w.lower() in ln for w in words) for ln in ilines), words)


irule(f"load the skill {SLUG} first, and do its checklist in order", "first", f"skill {SLUG}", "in order")
irule("fill only its own evidence item", "only", "own evidence item", f'"{EVIDENCE}"')
irule(f"file only the real findings of its own part, each name starting with [{NAME}]", "only the real findings", "own part",
      f'"[{NAME}] "')
irule("...none for a known vulnerability nor for the data class: the other two checks' parts", "known vulnerability",
      f'"{SCAN_CHECK}"', "data class", f'"{PURPOSE}"', "file none")
irule("it runs no scan and starts no Job", "no scan", "no job")
irule("a false hit goes in the doc with its reason", "false hit", "doc", "reason")
irule("say what it could not check, in the doc and in the result", "could not check", "doc", "result")
irule("nobody answers an event task: no question and no access request", "nobody answers", "domino_ask_user", "domino_request_access")
irule("the checklist's writes are the task's work: no asking first", "push", "attachment", "findings", "evidence", "without asking")
irule("end with report_result, once, last, with the skill's four lines on top", "domino_report_result", "once", "last", "four lines")

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

# ------------------------------------------------------------------------------------------------- the event subscription's file
# subscriptions/bundle-enters-validation.md (domino-agent-service ADR 0049, ticket #398): `domino-agent deploy` (0.4.0 or later)
# makes the agent's subscription from it, and changes or removes it at each deploy. The settings on top are the service's
# domino_agent/triggers.py fields (event, filter, title, notify), and the text below them is the instruction template. The repo is
# public, so the filter names the demo project by its name, not by its Domino ID: any project with that name matches.
# This part and subscribe() below are the two places of the subscription.
DEMO_PROJECT = "aml-validation-demo"   # the demo project's name (the seam part puts the seam's project name in its place)
# The fields of a governance.bundle.stage_changed payload, as the service's audit poller builds it (agent_service/audit_source.py)
PAYLOAD = ("source", "triggeredBy", "occurredAt", "auditTraceId", "bundle.id", "bundle.name", "fromStage", "toStage", "policy.id",
           "policy.name", "project.id", "project.name")


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
leaks = sorted({f"{rel}: {m.group(0)}" for rel, body in every.items()
                for m in re.finditer(r"[0-9a-f]{24}|agt_[0-9a-z]{6,}|[\w.-]+\.domino\.tech|apps-internal/[0-9a-f]+|eyJ[\w-]{20,}", body)})
check("no file of the folder has a Domino host, the ID of a Domino object or a token", not leaks, leaks)
dashed = sorted(rel for rel, body in [*every.items(), (f"tests/{Path(__file__).name}", text(Path(__file__)))] if chr(0x2014) in body)
check("no file of the folder, and not this check, has an em dash", not dashed, dashed)

# ------------------------------------------------------------------------------------------------------------ the folder's README
# The folder holds no user names and no trigger: its README says what the owner adds before the agent can run.
readme = every.get("README.md", "")
rlines = [ln.lower() for ln in readme.splitlines()]


def rrule(name, *words):
    """One line of the folder's README.md says it: it holds every one of `words` (case aside)."""
    check(f"the folder's README says: {name}", any(all(w.lower() in ln for w in words) for ln in rlines), words)


rrule("it is the folder validator of spec #260 (the tag app-validation-two-ways keeps it), narrowed to its part", "#260",
      "app-validation-two-ways", "narrowed")
rrule("it links to the shared rules of the three checks", "(../readme.md)")
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
rrule("make the subscription from subscription.json, with the demo project's ID", "subscription.json", "__DEMO_PROJECT_ID__",
      "post /api/agents/{id}/triggers")
rrule("the platform App polls the audit trail", "smoke_audit_poll_seconds")
rrule("...and pushes for real, else the push is a dry run and the doc isn't attached", "smoke_push_dry_run=0", "dry run", "attach")
rrule("the demo project's default branch has the shared rules", "default branch", "governance/readme.md",
      "governance/validation-doc.md")
rrule("how to run this check", f"python tests/{Path(__file__).name}")
check(f"governance/README.md (the shared rules, the hub of the three checks) names this folder, {PATH}/",
      f"`{PATH}/`" in text(ROOT / "governance" / "README.md"))

service = os.environ.get("AGENT_SERVICE_REPO", "").strip()
if not service:
    done("AGENT_SERVICE_REPO is not set, so the tool names, the deploy and the event's task weren't checked against the service. Set "
         f"it to a domino-agent-service checkout ({PATH}/README.md, \"The check\")")
service = Path(service).expanduser().resolve()
if not (service / "agent_runtime" / "gateway.py").is_file() or not (service / "agent_runtime" / "proxies.py").is_file():
    check(f"AGENT_SERVICE_REPO ({service}) is a domino-agent-service checkout (agent_runtime/gateway.py and proxies.py)", False)
    done()
sys.path.insert(0, str(service))
from agent_runtime import gateway, proxies  # noqa: E402  (stdlib only, so any OS)

offered = {f"domino_{n}" for n in gateway.TOOLS} | {f"domino_{n}" for n in proxies.RELAY_TOOLS}
check("each tool that they name is a gateway tool or a relay tool of this service, as opencode names it (domino_<name>)",
      named and named <= offered, sorted(named - offered))

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
check("it runs no Job and pushes its task branch, with no subagent (Run a Job: off, Git push: on)",
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

# ------------------------------------------------------------------------------------- the subscription and the event's task
# The deploy made the subscription from its file (subscribe() below reads it back), with the seam's project name in its filter. A
# stage move reaches it as the audit poller publishes it: Domino's audit row (AuditEvent, as the service's tests/check_phase3.py
# audit_event() copies a real stage move), made into the payload by the poller's own audit_source.to_payload, then published through
# the subscription's test route, which runs the same fan-out (service.emit_event) as the person who calls it.
import requests  # noqa: E402  (the service's checks image has it)
from agent_service import audit_source, domino  # noqa: E402

BUNDLE = {"id": "4f2b7c1e-0d3a-4e5f-9a8b-7c6d5e4f3a21", "name": "aml-case-management v7"}
real_get = domino.get


def bundle_get(path, params=None, cache=True, token=None, credential=None):
    """The fake Domino also answers the event bundle's GET (GET /api/governance/v1/bundles/{id}: guardrails.Bundle of the service's
    reference_materials/domino-api-specs/api-governance.swagger.json), a bundle of the task's project."""
    if path == f"/api/governance/v1/bundles/{BUNDLE['id']}":
        return {"id": BUNDLE["id"], "name": BUNDLE["name"], "projectId": seam.PROJECT["id"], "projectName": seam.PROJECT["name"],
                "policyId": "pol-app-deployment", "policyName": "App deployment policy", "stage": "Validation", "state": "Active"}
    return real_get(path, params, cache=cache, token=token, credential=credential)


domino.get = bundle_get


def stage_move(to="Validation", project=None, by=ANALYST):
    """The payload of one stage move of BUNDLE, from Intake to `to`, in `project` (the seam's project by default)."""
    ent = lambda kind, id_, name_: {"entityType": kind, "id": id_, "name": name_, "tags": []}
    p = project or (seam.PROJECT["id"], seam.PROJECT["name"])
    row = {"timestamp": 1795000000000, "actor": {"id": f"u-{by}", "name": by},
           "action": {"eventName": "Change Governance Bundle Stage", "using": [ent("eventSource", "Web", None)], "traceId": "tr-267"},
           "targets": [{"entity": ent("governanceBundle", BUNDLE["id"], BUNDLE["name"]),
                        "fieldChanges": [{"fieldType": "scalar", "fieldName": "stage", "before": "Intake", "after": to}]}],
           "affecting": [ent("governancePolicy", "pol-app-deployment", "App deployment policy")], "in": ent("project", *p)}
    return audit_source.to_payload("governance.bundle.stage_changed", row)


def subscribe():
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


trigger = subscribe()


def fire(payload, person):
    """Publish `payload` to the subscription as `person`. -> the event's `fired` list (one entry for each agent it reached)."""
    r = seam.api("POST", f"/api/triggers/{trigger.get('id')}/test", person, json={"payload": payload})
    return r.json().get("fired") if r.status_code == 200 else (r.status_code, r.text[:300])


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
for _ in range(100):   # the Job starts in the background
    if len(seam.JOBS) > n:
        break
    time.sleep(0.1)
job = seam.JOBS[-1] if len(seam.JOBS) == n + 1 else {}
check("its Domino Job starts at once, in the bundle's project, as the service account (its stored token)",
      job.get("credential") == ("bearer", token) and (job.get("body") or {}).get("projectId") == seam.PROJECT["id"],
      (len(seam.JOBS) - n, job.get("credential")))
spec = {}
if job:   # the Job's claim, as its bootstrapper plays it (the seam's spec_of does the same for a direct task)
    tok = requests.post(f"{seam.B}/api/runtime/sessions/{job['sid']}/claim", headers={"authorization": f"Bearer {token}"},
                        json={"runId": f"localjob{len(seam.JOBS)}"}, timeout=30).json().get("token")
    spec = requests.get(f"{seam.B}/api/runtime/sessions/{job['sid']}/spec", headers={"x-agent-session-token": tok}, timeout=30).json()
rules = str(spec.get("operatingRules") or "")
check("the Job's spec has the instructions at the top of the agent's rules, and the access rows as the folder sets them",
      rules.startswith(instructions.strip() + "\n\n## Operating rules") and "Project files: read & write. Project datasets: no access. "
      "Other resources attached to the task: read & write." in rules, rules[:300])
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
    "write_policy_result": {"bundleId": BUNDLE["id"], "evidenceId": "ev-1", "content": {"art-verdict": V[1]}},
}
for name, args in CALLS.items():
    d = gateway.decide(name, args, policy) if policy else {}
    check(f"the gateway allows {name} on the event's bundle, by its own row (named), with no owner check",
          d.get("allow") is True and d.get("row") == "named" and not any(s.get("expect") for s in d.get("steps") or []),
          {k: d.get(k) for k in ("allow", "row", "why")})
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
domino.get = real_get

# A later deploy of the same commit keeps the subscription: the file name is its identity (ADR 0049, decision 4)
ran = seam.command("deploy", PATH, cwd=repo.root, person=OWNER)
kept = [t for t in seam.api("GET", f"/api/agents/{aid}/triggers", OWNER).json() if t.get("file")]
check("a second deploy of the same commit changes nothing: no Trigger line, and the subscription keeps its ID and stays on",
      ran.code == 0 and "No change for" in ran.out and not trigger_lines(ran.out)
      and [(t.get("id"), t.get("enabled")) for t in kept] == [(trigger.get("id"), True)], (ran, kept))

seam.close()
done()
