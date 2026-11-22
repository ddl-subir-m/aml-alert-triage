"""The wizard agent "App validation" (governance/app-validation/), domino-agent-service #529: one wizard agent that a person makes and
runs only in the App, and that does the work of the three checks of the App validation demo in one task. The folder is its reference
copy in git: the two new store skills, the instructions, the settings as the wizard saves them, the subscription, the schedule, a
helper that fills and compares them, and a README with the wizard steps. Its first store skill is check 1's purpose-and-data, as it is.

With no service, it checks the files, with the stdlib only:
  - the two store skills: their YAML, at most 120 lines, the evidence item by the names of governance/checks.json, no ID search,
    the order of their tools, no own tool and no custom subagent (a wizard agent can't have them), the shell that only reads and
    the built-in subagent (architecture-and-access), the scan in a Domino Job (vulnerability-scan), and the schedule part, which
    looks only at the bundles of the task's own project;
  - the instructions: the three skills in order, one result in three parts, and the same rule of the task's own project;
  - each value of agent.json, the subscription's and the schedule's files, compare.py (run with no site-packages);
  - the README's steps (one row for each key, with the wizard's own label) and its other rules;
  - no Domino host, ID or token, no em dash and no word "lane" in the folder's text (the repo is public).
With AGENT_SERVICE_REPO (a domino-agent-service checkout, any OS), it also checks each tool name against the service's gateway and
relay, the longest wait of wait_job for a harness agent, the built-in subagent's name, and each label in quotes in the README's
tables against the wizard's code. No Domino host.

  python tests/check_app_validation.py
  AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_app_validation.py
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import three_checks as shared   # the shared parts of the three checks' checks, next to this file (stdlib only)
from three_checks import ROOT, check, done, text

FOLDER = ROOT / "governance" / "app-validation"
CHECKS, _ = shared.load_checks("")
BY_FOLDER = {c.get("folder"): c for c in CHECKS.get("checks") or [] if isinstance(c, dict)}
PD = BY_FOLDER.get("governance/check-purpose-and-data") or {}
AA = BY_FOLDER.get("governance/check-architecture-and-access") or {}
VS = BY_FOLDER.get("governance/check-vulnerability-scan") or {}
check("governance/checks.json names the three checks whose work this agent does",
      [c.get("name") for c in (PD, AA, VS)] == ["Purpose and data", "Architecture and access", "Vulnerability scan"],
      [c.get("name") for c in (PD, AA, VS)])
LABELS = CHECKS.get("fields") or {}
FOUR = [LABELS.get(k) for k in ("verdict", "severity", "summary", "doc")]   # the four fields' labels, in checks.json's order
SKILLS = ["purpose-and-data", "architecture-and-access", "vulnerability-scan"]   # the order of the agent's store skills
BUDGET = 120   # #529: each new store skill has at most 120 lines

# --------------------------------------------------------------------------------------------------------------------- the files
FILES = ("README.md", "instructions.md", "agent.json", "subscription.json", "schedule.json", "compare.py",
         "skills/architecture-and-access/SKILL.md", "skills/vulnerability-scan/SKILL.md")
every = {p.relative_to(FOLDER).as_posix(): p.read_text() for p in sorted(FOLDER.rglob("*")) if p.is_file()
         and not any(part == "__pycache__" for part in p.relative_to(FOLDER).parts)} if FOLDER.is_dir() else {}
check(f"{FOLDER.relative_to(ROOT)}/ holds the reference copy and nothing else: {', '.join(FILES)}", sorted(every) == sorted(FILES),
      sorted(every))
instructions = every.get("instructions.md", "")
aa = every.get("skills/architecture-and-access/SKILL.md", "")
vs = every.get("skills/vulnerability-scan/SKILL.md", "")
pd = text(ROOT / "governance" / "check-purpose-and-data" / "SKILL.md")   # check 1's store skill, as it is


def top_name(skill):
    """The `name` of the skill's YAML on top, or None when it has no YAML with a name and a description."""
    top = re.match(r"---\n(.*?)\n---\n", skill, re.S)
    name = re.search(r"^name: (\S+)$", top.group(1), re.M) if top else None
    return name.group(1) if name and re.search(r"^description: \S.{20,}$", top.group(1), re.M) else None


check("check 1's store skill is purpose-and-data, the first skill of this agent (it does not change)", top_name(pd) == SKILLS[0],
      pd[:200])

# ------------------------------------------------------------------------------------------------------- the two new store skills
# Each one is check 2's or check 3's checklist, for a wizard agent: it fills its evidence item by names, searches for no ID, and
# names only the tools that a wizard agent has. A wizard agent can't have an own tool or a custom subagent.
for slug, skill, mine in (("architecture-and-access", aa, AA), ("vulnerability-scan", vs, VS)):
    doc = f"docs/validation/{slug}-<bundleId>.md"
    evidence = mine.get("evidenceItem")
    check(f"{slug}: the store skill has YAML on top with the name {slug} and a description (else opencode never offers it)",
          top_name(skill) == slug, skill[:300])
    lines = len(skill.splitlines())
    check(f"{slug}: it has at most {BUDGET} lines (#529)", 0 < lines <= BUDGET, f"{lines} lines")
    called, keys = shared.result_call(skill)
    check(f"{slug}: it fills its evidence item by names: {evidence!r} and the four fields by their labels, in checks.json's order",
          called == evidence and keys == FOUR, (called, keys))
    check(f"{slug}: ...so it searches for no ID (the gateway finds the IDs in the bundle's policy)", not shared.id_search(skill),
          shared.id_search(skill))
    steps = [int(n) for n in re.findall(r"^## (\d+)\. ", skill, re.M)]
    check(f"{slug}: it is numbered steps, in order, and each one ends with a 'Done when' line",
          len(steps) >= 7 and steps == list(range(1, len(steps) + 1))
          and all("Done when:" in part for part in re.split(r"^## (?:\d+\. |The schedule part)", skill, flags=re.M)[1:]), steps)
    rule = shared.rules(f"{slug} says", skill)
    rule("read the rules file first, and follow it in each step", "read `governance/rules.md` first", "each step")
    rule("the doc follows the shared template, at its own file name", "governance/validation-doc.md", doc.lower())
    rule("...trimmed to this check as the rules file says: its middle part is the check's", "governance/rules.md", "trim",
         mine.get("name", "").lower())
    rule("the doc's own Doc location, by the rules file, with its own file", "`doc_location`", "governance/rules.md", doc.lower())
    rule("push the doc with git_push, and keep its branch, commit and dryRun", "domino_git_push", "branch", "commit", "dryrun")
    rule("attach the doc: a Report from GBP, with the task branch and the push's commit", "domino_write_bundle_attachment",
         '"report"', '"gbp"', "branch", "commit", doc.lower())
    rule("...only when the push is on the remote (dryRun false)", "only when", "dryrun", "false")
    rule("a dry-run push: attach nothing, and say so under what this check could not check", "dryrun", "true", "attach nothing",
         "could not check")
    rule("file each real finding with the name and the severity of the doc's table", "domino_write_governance_finding", "name",
         "severity", "doc's table")
    rule("file no false hit", "no false hit")
    rule("fill only its own evidence item, by its name", "fill only your own evidence item", "domino_write_policy_result",
         f'evidencename="{evidence}"')
    rule("its part of the result is the rules file's result: its four lines first", "governance/rules.md", "four lines",
         "same values")
    rule("...and it calls no report_result: the system prompt reports one result", "do not call `domino_report_result`",
         "system prompt")
    order = ["domino_git_push", "domino_write_bundle_attachment", "domino_write_governance_finding", "domino_write_policy_result"]
    at = [skill.find(t) for t in order]
    check(f"{slug}: its writes come in order: push, attachment, findings, evidence",
          all(i >= 0 for i in at) and at == sorted(at), dict(zip(order, at)))
    check(f"{slug}: no own tool and no custom subagent (a wizard agent can't have them)",
          not re.search(r"own_route_table|own tool|route-reviewer|custom subagent", skill, re.I),
          sorted(set(re.findall(r"own_route_table|own tool|route-reviewer|custom subagent", skill, re.I))))

# architecture-and-access: the shell in place of the own tool route_table, the built-in subagent in place of route-reviewer
arule = shared.rules("architecture-and-access says", aa)
arule("read the bundle and the policy with the bundle's ID", "domino_get_bundle(bundleid)")
arule("...and the Intake's fields by their labels", "domino_get_policy(bundleid)", 'stage named "intake"', "details.label")
arule("read the routes with the shell, with commands that only read", "shell", "only read", "grep")
arule("...and run no command that writes, installs or starts the App", "run no command", "writes", "installs", "starts the app")
arule("find the servers and the ways into the App with grep", "grep -rn", "fastmcp(", ".tool", ".custom_route", "domino-username")
arule("the route table: one row for each MCP tool and each custom route", "route table", "one row", ".tool", ".custom_route")
arule("an MCP tool's row: POST /mcp (tool: <name>)", "mcp tool", "`post`", "/mcp (tool: <name>)")
arule("each row has the handler, its file and line, reads_identity and changes_state", "handler", "`file`", "`line`",
      "reads_identity", "changes_state")
arule("a write: the rule of the own tool (SQL, open with a write mode, a write call, global)", "insert into", "delete from",
      "write_text", "unlink", "`global`")
arule("what it can't read goes under what this check could not check", "not valid python", "could not check")
arule("give the route table to the built-in subagent, once, with the task tool", "built-in subagent", "once", "`task` tool",
      "`subagent_type` `general`")
arule("the brief: the subagent only reads, with the read tools only", "you only read", "read, glob, grep")
arule("...runs no shell command and calls no Domino tool", "no shell command", "no domino tool")
arule("...writes no file and files no finding: the main agent files the findings", "write no file", "file no finding",
      "main agent files")
arule("...judges only access", "judge only access")
arule("...one JSON object in a json block, with a verdict for each route", "one json object", "json block")
check("architecture-and-access: the brief ends with the Intake's Users and Data class, the access rules and the route table",
      all(re.search(rf"^{w}", aa, re.M) for w in ("Users: <", "Data class: <", "Access rules:$", "Route table:$")))
check("architecture-and-access: the brief's answer has the fields of route-reviewer's answer",
      all(f'"{k}"' in aa for k in ("routes", "method", "path", "who_can_call", "what_it_changes", "problem", "severity",
                                   "severity_reason", "evidence", "not_reviewed")))
for n, words in {1: ("domino access setting", "anyone who can open the app"), 2: ("access check", "domino-username"),
                 3: ("changes state", "no access check"), 4: ("record who made it", "no identity"),
                 5: ("severity", "governance/rules.md"), 6: ("judge only access", "vulnerability scan", "purpose and data")}.items():
    arule(f"access rule {n}", f"{n}. ", *words)
arule("a failed task call or no usable answer: judge the routes yourself, and the check goes on", "no usable answer",
      "do not call it again", "judge the routes yourself")
arule("the subagent files nothing: the main agent files the findings", "subagent files nothing")
arule("it runs no scan and starts no Job", "runs no scan", "starts no job")
check("architecture-and-access: it starts no Domino Job (domino_run_job is the scan's)", "domino_run_job" not in aa)
check("architecture-and-access: its middle part of the doc has the route table: method, path, who can call it, what it changes",
      re.search(r"table of each route: method, path, who can call it, what it changes", aa) is not None)

# vulnerability-scan: check 3's steps, with the scan in a Domino Job and the doc pushed to the task branch
SCAN = text(ROOT / "governance" / "scan.py")
start, end, ran = (m.group(1) if (m := re.search(rf'{k} = "([^"]+)"', SCAN)) else None for k in ("START", "END", "RAN"))
start, end = ((m.group(1), m.group(2)) if (m := re.search(r'START, END = "([^"]+)", "([^"]+)"', SCAN)) else (start, end))
check("governance/scan.py has the summary's two marker lines and its result line", start and end and ran, (start, end, ran))
vrule = shared.rules("vulnerability-scan says", vs)
vrule("run the shared scan in a Domino Job", 'domino_run_job(command="python governance/scan.py"')
vrule("...then wait_job, again until finished, with the harness's longest wait", "domino_wait_job(jobid, seconds=45)", "finished")
vrule("...at most about 20 minutes", "about 20 minutes")
vrule("read the summary between its two marker lines", f"`{start}`", f"`{end}`", "log")
vrule("...and get_job_logs when a marker is not in the log", "domino_get_job_logs(jobid)", "marker")
vrule("the scan ran only when the Job succeeded and both tools ran", "`succeeded`", f"`{ran}`")
vrule("...else a failed scan, by governance/README.md: no finding from the scan", "a failed scan", "governance/readme.md",
      "no finding from the scan")
vrule("a real hit: the code makes it reachable", "reachable", "false hit")
vrule("look for known vulnerabilities that no scanner shows", "no scanner shows")
vrule("each real finding gets a key, from the scan's summary", "key", "scan's summary")
vrule("...a pip-audit hit: its first ID, also for an alias", "first id", "pysec-2021-142", "cve-2020-14343")
vrule("...a bandit hit: its rule ID, then its file and line", "rule id", "b602 case_server/server.py:120")
vrule("...a finding in the code: its file and line", "no scanner hit", "file and line")
vrule("the parts that a tool did not check go under could not check", "- not audited:", "- not scanned:", "could not check")
vrule("the doc's commit is the summary's commit line", "`commit:`", "app_and_version")
vrule("the doc is pushed, so its location is the pushed form, with no dataset and no snapshot", "pushed doc", "no dataset",
      "no snapshot")
vrule("each filed finding's description starts with its key", "domino_write_governance_finding", '"key: <its key>" first')
vrule("only its own part: not access, not the pin, not the data class", "who can call a route", "pinned or installed",
      "kind of data", "file none")
check("vulnerability-scan: it names no doc dataset tool (the doc goes to the task branch, as checks 1 and 2 do)",
      not re.search(r"write_bundle_doc|DatasetSnapshotFile|write_dataset", vs))
part = (re.split(r"^## The schedule part$", vs, maxsplit=1, flags=re.M) + [""])[1]
check("vulnerability-scan: it has a schedule part, after the event steps", bool(part.strip()))
srule = shared.rules("its schedule part says", part)
srule("it scans again with the event steps 2 to 4", "steps 2, 3 and 4")
srule("it looks only at the bundles of the task's own project, by that project's ID", "only at the bundles", "own project",
      "project's id")
srule("...the projectId of 'This task' in the operating rules", "`projectid`", "operating rules", "this task")
srule("...never the ID of another project, and never a bundle that the list did not give", "never pass the id of another project",
      "never read, attach to or file on a bundle that this list did not give")
srule("list the bundles in Approval of that project, page by page", 'domino_list_bundles(projectid=<that id>, stage="approval")',
      "`offset`", "`nextoffset`", "null")
srule("...and each bundle's findings, in the full view, page by page", 'domino_list_bundle_findings(bundleid, view="full")',
      "page by page")
srule("a bundle's keys: the first line of each finding's description", "`key: `", "first line", "description")
srule("new findings by key, never by name, one key once", "compare keys, never names", "once")
srule("one report, pushed, attached as a Report only to each bundle that gets a new finding",
      "docs/validation/vulnerability-scan-scheduled-", "domino_git_push", "`report`", "only to each bundle that gets a new finding")
srule("it fills no evidence item", "fills no evidence item", "never calls `domino_write_policy_result`")
srule("its result's lines", "bundles in approval: <n>", "filed: <n> new findings on <m> bundles")
srule("it files nothing when the scan failed, a list call failed or there is no project ID", "file nothing",
      "scan failed", "list tools failed", "no project id")
check("vulnerability-scan: the schedule part calls no domino_write_policy_result",
      "domino_write_policy_result(" not in part, part[:200])

# --------------------------------------------------------------------------------------------------- the instructions (the system prompt)
irule = shared.rules("the instructions say", instructions, shared.blocks)
names = [c.get("name") for c in (PD, AA, VS)]
irule("it does the work of the three checks in one task", "three checks", "one task", *[f'"{n}"' for n in names])
skill_at = [instructions.find(f"skill {s}") for s in SKILLS]
check("the instructions do the three store skills in order: purpose-and-data, architecture-and-access, vulnerability-scan",
      all(i >= 0 for i in skill_at) and skill_at == sorted(skill_at), dict(zip(SKILLS, skill_at)))
irule("...each one to its end, with the skill tool", "each one to its end", "skill tool")
irule("in purpose-and-data's last step, no report_result: its result waits for the end", "purpose-and-data",
      "do not call domino_report_result", "keep its result for the end")
irule("the rules that the three checks share are in the rules file: follow them", "governance/rules.md",
      "rules that the three checks share", "follow")
irule("one result in three parts, in the order of the skills, with report_result once, last", "one result in three parts",
      "domino_report_result once, last")
irule("...each part starts with the line ## <check name>, then the rules file's result, its four lines first", '"## <check name>"',
      "governance/rules.md", "four lines first")
irule("a task of the schedule: only the schedule part of vulnerability-scan, no other skill, no evidence item", "schedule",
      "only the schedule part", "vulnerability-scan", "load no other skill", "fill no evidence item")
irule("fill only the three evidence items, each with its own skill", "only the three evidence items",
      *[f'"{c.get("evidenceItem")}"' for c in (PD, AA, VS)])
irule("in each part, only that part's real findings, named by the rules file", "only the real findings", "governance/rules.md")
irule("a false hit goes in the doc with its reason", "false hit", "doc", "reason")
irule("say what it could not check, as the rules file says, and a dry-run push too", "could not check", "governance/rules.md",
      "dry-run push")
irule("the docs are the only files that it writes, and the shell only reads", "only files that you write", "shell only")
irule("a Domino Job only for the scan", "domino job only for the scan", "python governance/scan.py")
irule("the built-in subagent only reviews: the agent makes each write", "built-in subagent only reviews", "you make each write")
irule("only the bundles of the task's own project, by its ID: never a bundle of another project",
      "only at the bundles of the task's own project", "project's id", "never list, read, attach to or file on a bundle of another project")
irule("nobody answers: no question and no access request", "nobody answers", "domino_ask_user", "domino_request_access")
irule("the skills' writes are the task's work: no asking first", "pushes", "attachments", "findings", "evidence", "without asking")

# --------------------------------------------------------------------------------------------------------------- the tool names
# opencode names a tool of the relay's MCP server `domino` as domino_<name> (the service's agent_runtime/gateway.py). The skill tool and
# the task tool are opencode's own.
NAMES = {"domino_get_bundle", "domino_get_policy", "domino_git_push", "domino_write_bundle_attachment",
         "domino_write_governance_finding", "domino_write_policy_result", "domino_report_result", "domino_ask_user",
         "domino_request_access", "domino_run_job", "domino_wait_job", "domino_get_job_logs", "domino_list_bundles",
         "domino_list_bundle_findings"}
named = set(re.findall(r"\bdomino_[a-z_]+", aa + vs + instructions))
check("the skills and the instructions name the Domino tools of the work, and no other", named == NAMES, sorted(named ^ NAMES))
bare = sorted(set(re.findall(r"(?<![a-z_`])(?:get_bundle|get_policy|run_job|wait_job|git_push|list_bundle\w*|write_[a-z_]+|"
                             r"report_result)\(", aa + vs + instructions)))
check("they call no tool by its plain name (a framework agent's name): a harness agent has only the domino_ names", not bare, bare)

# ---------------------------------------------------------------------------------------------------- the reference settings
MODEL = "google/gemini-3.8-flash"   # the model of the three checks; not sonnet: Anthropic's cyber safeguards refuse this work (#270)
try:
    ref = json.loads(every.get("agent.json", ""))
except ValueError as e:
    ref = {"error": str(e)}
ref = ref if isinstance(ref, dict) else {}
g = ref.get("guardrails") or {}
check("agent.json is the agent's settings, in the order of the wizard's steps (the shape of check 1's), with no other key",
      list(ref) == ["lane", "name", "description", "tags", "scope", "inputs", "model", "execution", "systemPrompt", "directTrigger",
                    "skills", "completion", "onError", "identity", "access", "guardrails"], list(ref))
check("its name is App validation (no clash with a check's name), with a description",
      ref.get("name") == "App validation" and ref.get("name") not in names and ref.get("description"), ref.get("name"))
check("it is a harness agent (the card Domino Agent Harness), for any project, with a required project input, and no tags",
      ref.get("lane") == "harness" and ref.get("scope") == {"type": "global"} and ref.get("tags") == []
      and ref.get("inputs") == [{"name": "project", "type": "project", "required": True, "multiple": False, "description": ""}],
      {k: ref.get(k) for k in ("lane", "scope", "tags", "inputs")})
check(f"its model is the LLM Gateway alias {MODEL}, with the grants of the identity that it acts as",
      ref.get("model") == {"source": "gateway", "models": [MODEL], "access": "acting"}, ref.get("model"))
check("its Environment is the harness's, by name, with 60 minutes, 300 turns and no wait for an answer",
      ref.get("execution") == {"environment": {"name": "Domino Agent Runtime (opencode)"}, "maxRuntimeMin": 60, "maxTurns": 300,
                               "idleWaitMin": 0}, ref.get("execution"))
check("its system prompt is instructions.md (a placeholder that compare.py fills)", ref.get("systemPrompt") == "__INSTRUCTIONS__",
      ref.get("systemPrompt"))
check("its skills are the three store skills, in order, as the wizard's picker names them (IDs and versions from the store)",
      ref.get("skills") == [{"id": f"__{p}_SKILL_ID__", "name": s, "version": f"__{p}_SKILL_VERSION__"}
                            for p, s in zip(("PD", "AA", "VS"), SKILLS)], ref.get("skills"))
check("a person closes the task, a failure ends it with a report, with no plan and no check-ins",
      ref.get("completion") == "review" and ref.get("onError") == "fail" and g.get("planFirst") is False
      and g.get("checkInOften") is False, (ref.get("completion"), ref.get("onError"), g.get("planFirst"), g.get("checkInOften")))
check("no suggested prompt and no notification", ref.get("directTrigger") == {"starterPrompts": [], "writeBack": []},
      ref.get("directTrigger"))
check("it acts as the service account of the three checks (a placeholder: no user name in the public repo)",
      ref.get("identity") == {"mode": "service_account", "serviceAccount": {"userName": "__SERVICE_ACCOUNT__"}}, ref.get("identity"))
check("it is shared with the analyst (People) and the approver (Editors)",
      ref.get("access") == {"mode": "restricted", "users": ["__ANALYST__"], "editors": ["__APPROVER__"]}, ref.get("access"))
check("its tools: Shell on, Web fetch off, Subagents on (the built-in subagent), Start Domino jobs on (the scan), Git push on",
      g.get("tools") == {"bash": True, "web": False, "subagents": True, "jobs": True, "push": True}, g.get("tools"))
check("its Resource access: Project files Read & write, Project datasets No access, Other resources attached to the task Read & "
      "write, Resources not attached to the task No access (no bundle of another project)",
      g.get("access") == {"project": "write", "data": "none", "inputs": {}, "named": "write", "other": "none"}, g.get("access"))
check("its outbound traffic: Domino services only", g.get("network") == {"mode": "domino", "domains": []}, g.get("network"))
check("guardrails has the wizard's five parts and no other", sorted(g) == ["access", "checkInOften", "network", "planFirst", "tools"],
      sorted(g))

# ------------------------------------------------------------------------------------------------------------- the trigger files
PAYLOAD = set(shared.PAYLOAD)   # the fields of a governance.bundle.stage_changed payload, as the service's audit poller builds it
SCHEDULE_VALUES = {"schedule.name", "schedule.cron", "schedule.timezone", "schedule.scheduledFor"}   # what a fire fills
KEYS = ["type", "name", "enabled", "event", "titleTemplate", "instructionTemplate", "defaultResources", "writeBack"]


def load(name):
    try:
        got = json.loads(every.get(name, ""))
    except ValueError as e:
        got = {"error": str(e)}
    return got if isinstance(got, dict) else {}


sub, sch = load("subscription.json"), load("schedule.json")
event = sub.get("event") or {}
check("subscription.json: an event subscription to governance.bundle.stage_changed, on, named Bundle enters Validation",
      list(sub) == KEYS and sub.get("type") == "event" and event.get("eventType") == "governance.bundle.stage_changed"
      and sub.get("enabled") is True and sub.get("name") == "Bundle enters Validation", list(sub))
check("...its filter: toStage Validation, in the second project (a placeholder for its ID)",
      event.get("filter") == [{"field": "toStage", "op": "equals", "value": "Validation"},
                              {"field": "project.id", "op": "equals", "value": "__WIZARD_PROJECT_ID__"}], event.get("filter"))
title, instruction = sub.get("titleTemplate") or "", sub.get("instructionTemplate") or ""
check("...its title: App validation and the bundle ID", title == "App validation: bundle {{bundle.id}}", title)
check("...its instruction names the bundle, the three skills in order and the three evidence items, and ends with the bundle ID",
      "{{bundle.id}}" in instruction and "{{bundle.name}}" in instruction
      and [instruction.find(s) for s in SKILLS] == sorted(instruction.find(s) for s in SKILLS) and all(s in instruction for s in SKILLS)
      and all(f'"{c.get("evidenceItem")}"' in instruction for c in (PD, AA, VS))
      and instruction.splitlines()[-1:] == ["Bundle ID: {{bundle.id}}"], instruction)
fields = set(re.findall(r"\{\{([^}]+)\}\}", title + instruction))
check("...each placeholder of its templates is a field of the stage-change payload", fields and fields <= PAYLOAD,
      sorted(fields - PAYLOAD))
check("...it pins no resource and writes nothing back", sub.get("defaultResources") == [] and sub.get("writeBack") == [])
check("schedule.json: a schedule, on, named Weekly re-scan of approved Apps, each Monday at 06:00 UTC, in the second project by name",
      list(sch) == ["type", "name", "enabled", "schedule", "project", *KEYS[4:]] and sch.get("type") == "schedule"
      and sch.get("enabled") is True and sch.get("name") == "Weekly re-scan of approved Apps"
      and sch.get("schedule") == {"cron": "0 6 * * 1", "timezone": "UTC"} and sch.get("project") == {"name": "aml-validation-wizard"},
      {k: sch.get(k) for k in ("type", "name", "enabled", "schedule", "project")})
stitle, sinstr = sch.get("titleTemplate") or "", sch.get("instructionTemplate") or ""
check("...its title: App validation and the time of the fire", stitle == "App validation: weekly re-scan, {{schedule.scheduledFor}}",
      stitle)
check("...its instruction: the schedule part of vulnerability-scan, the bundles in Approval, no evidence item, and no bundle line",
      all(w in sinstr for w in ("schedule part of the skill vulnerability-scan", "Approval", "Fill no evidence item"))
      and "Bundle ID" not in sinstr, sinstr)
check("...and only the bundles of the task's own project, by its ID, never a bundle of another project",
      "this task's own project" in sinstr and "by that project's ID" in sinstr and "Never look at a bundle of another project" in sinstr,
      sinstr)
sfields = set(re.findall(r"\{\{([^}]+)\}\}", stitle + sinstr))
check("...each placeholder of its templates is a value of a fire", sfields and sfields <= SCHEDULE_VALUES, sorted(sfields - SCHEDULE_VALUES))
check("...it pins no resource and writes nothing back", sch.get("defaultResources") == [] and sch.get("writeBack") == [])

# ------------------------------------------------------------------------------------------------------------- the compare helper
HELPER = FOLDER / "compare.py"
VALUES = {"__SERVICE_ACCOUNT__": "sa-one", "__ANALYST__": "ana", "__APPROVER__": "abe", "__PD_SKILL_ID__": "skl_pd",
          "__PD_SKILL_VERSION__": "0.1.0", "__AA_SKILL_ID__": "skl_aa", "__AA_SKILL_VERSION__": "0.2.0", "__VS_SKILL_ID__": "skl_vs",
          "__VS_SKILL_VERSION__": "0.3.0", "__WIZARD_PROJECT_ID__": "proj-two"}
SETS = [x for k, v in VALUES.items() for x in ("--set", f"{k}={v}")]
work = Path(tempfile.mkdtemp(prefix="check-app-validation-"))
atexit.register(shutil.rmtree, work, ignore_errors=True)


def helper(*args):
    """compare.py with `args`, as `python3 -I -S` runs it (no site-packages, no current folder). -> (exit code, stdout + stderr)"""
    p = subprocess.run([sys.executable, "-I", "-S", str(HELPER), *args], capture_output=True, text=True, timeout=60, cwd=work)
    return p.returncode, p.stdout + p.stderr


def filled(*args):
    code, out = helper("fill", *args)
    try:
        return code, json.loads(out) if code == 0 else {}
    except ValueError:
        return code, {}


def diff(reference, got, sets=SETS):
    path = work / "read-back.json"
    path.write_text(json.dumps(got))
    return helper("diff", reference, str(path), *sets)


code, body = filled("agent.json", *SETS)
check("compare.py fill agent.json gives the body to send, with each placeholder filled and the system prompt from instructions.md",
      code == 0 and "__" not in json.dumps(body) and body.get("systemPrompt") == instructions.strip()
      and body.get("skills") == [{"id": "skl_pd", "name": SKILLS[0], "version": "0.1.0"},
                                 {"id": "skl_aa", "name": SKILLS[1], "version": "0.2.0"},
                                 {"id": "skl_vs", "name": SKILLS[2], "version": "0.3.0"}]
      and body.get("access") == {"mode": "restricted", "users": ["ana"], "editors": ["abe"]}, (code, json.dumps(body)[:300]))
code, out = helper("fill", "agent.json", *SETS[:-6])
check("...and refuses, naming it, when a placeholder has no value", code == 2 and "__VS_SKILL_VERSION__" in out and "{" not in out,
      (code, out[:300]))
if body:
    stored = json.loads(json.dumps(body))   # as GET /api/agents/{id} answers: the service adds the deployment's keys
    stored.update(id="agt_x", owner={"userName": "someone"}, createdAt="2026-11-22T00:00:00Z", enabled=True,
                  identityCredential={"status": "active", "account": "sa-one", "last4": "abcd"}, stats={"tasks": 0})
    stored["execution"].update(hardwareTier="small-k8s", environment={"id": "env-1", "name": "Domino Agent Runtime (opencode)"})
    stored["systemPrompt"] = instructions.strip() + "\n"   # a paste can end with a new line
    code, out = diff("agent.json", stored)
    check("compare.py diff agent.json <read-back> finds no difference in the agent as the service stores it",
          code == 0 and out.strip().splitlines()[-1:] == ["Same as agent.json."], (code, out[:400]))
    stored["guardrails"]["tools"]["subagents"] = False
    stored["skills"] = stored["skills"][:2]
    code, out = diff("agent.json", stored)
    check("...and names each setting that differs, and exits 1", code == 1 and "guardrails.tools.subagents: wants true, has false" in out
          and "skills: wants 3 items, has 2" in out, (code, out[:400]))
code, sbody = filled("subscription.json", *SETS)
check("compare.py fill subscription.json puts the second project's ID in its filter",
      code == 0 and ((sbody.get("event") or {}).get("filter") or [{}, {}])[1:] == [{"field": "project.id", "op": "equals",
                                                                                    "value": "proj-two"}], (code, sbody))
code, schbody = filled("schedule.json")
check("compare.py fill schedule.json needs no value: the schedule names its project by name", code == 0 and schbody == sch,
      (code, schbody))
if sbody and schbody:   # GET /api/agents/{id}/triggers: the direct trigger, the subscription and the schedule, as the service stores them
    listed = [{"id": "trg_dir_agt_x", "type": "direct", "name": "Direct runs", "enabled": True},
              {**sbody, "id": "trg_1", "agentId": "agt_x", "fireCount": 0, "lastFiredAt": None, "description": None},
              {**schbody, "id": "trg_2", "agentId": "agt_x", "nextFireAt": "2026-11-23T06:00:00Z", "description": None}]
    code, out = diff("subscription.json", listed)
    check("compare.py diff subscription.json <triggers> compares the subscription, and finds no difference",
          code == 0 and out.strip().endswith("Same as subscription.json."), (code, out[:300]))
    code, out = diff("schedule.json", listed, [])
    check("compare.py diff schedule.json <triggers> compares the schedule, and finds no difference",
          code == 0 and out.strip().endswith("Same as schedule.json."), (code, out[:300]))
    listed[2]["schedule"] = {"cron": "0 9 * * 1", "timezone": "UTC"}
    code, out = diff("schedule.json", listed, [])
    check("...and names a schedule at another time", code == 1 and 'schedule.cron: wants "0 6 * * 1", has "0 9 * * 1"' in out,
          (code, out[:300]))
    code, out = diff("schedule.json", listed[:2], [])
    check("...and says when the read-back has no schedule of that name", code == 1 and "No schedule trigger named" in out, (code, out))

# ------------------------------------------------------------------------------------------------------- the README's wizard steps
# The person makes the agent from the README's tables: one row for each setting, with the wizard's own label (in quotes), the value to
# set, and the setting's key in the reference file (in backticks). The words are the wizard's (the service's static/js).
WIZARD = {
    "lane": ("What runs the agent?", ("Domino Agent Harness (opencode)",)),
    "name": ("Name", ("App validation",)),
    "description": ("Description", ("`description`", "agent.json")),
    "tags": ("Tags", ("none",)),
    "scope": ("Where can it work?", ("Any project",)),
    "inputs": ("Project required as trigger input", ("checked",)),
    "guardrails.access.inputs": ("Inputs", ("only the project",)),
    "model.access": ("Model access", ("Whoever triggers it", "Agent identity")),
    "model.source": ("Custom endpoint", ("off",)),
    "model.models": ("LLM Gateway models", (MODEL, "only")),
    "execution.environment": ("Environment", ("Domino Agent Runtime (opencode)",)),
    "execution.maxRuntimeMin": ("Max minutes per round", ("60",)),
    "execution.maxTurns": ("Max turns per round", ("300",)),
    "execution.idleWaitMin": ("Wait for answers (min)", ("0",)),
    "systemPrompt": ("System prompt", ("instructions.md",)),
    "directTrigger.starterPrompts": ("Suggested prompts (optional)", ("none",)),
    "skills": ("Skills", tuple(SKILLS) + ("in this order",)),
    "guardrails.planFirst": ("Planning", ("Start right away",)),
    "completion": ("Task completion", ("A person closes the task",)),
    "onError": ("Error recovery", ("Fail and report",)),
    "guardrails.checkInOften": ("Check-ins", ("Only when needed",)),
    "directTrigger.writeBack": ("Notifications", ("none",)),
    "identity.mode": ("Acts as", ("A service account",)),
    "identity.serviceAccount.userName": ("Service account", ("service account",)),
    "access.mode": ("Who can use it", ("Specific people",)),
    "access.users": ("People", ("analyst",)),
    "access.editors": ("Editors", ("approver",)),
    "guardrails.access.project": ("Project files", ("Read & write",)),
    "guardrails.access.data": ("Project datasets", ("No access",)),
    "guardrails.access.named": ("Other resources attached to the task", ("Read & write",)),
    "guardrails.access.other": ("Resources not attached to the task", ("No access",)),
    "guardrails.tools.bash": ("Shell", ("on",)),
    "guardrails.tools.web": ("Web fetch", ("off",)),
    "guardrails.tools.subagents": ("Subagents", ("on", "built-in subagent")),
    "guardrails.tools.jobs": ("Start Domino jobs", ("on",)),
    "guardrails.tools.push": ("Git push", ("on",)),
    "guardrails.network": ("Outbound traffic", ("Domino services only",)),
}
SUBSCRIPTION_FORM = {
    "type": ("Event subscriptions", ("Add subscription",)),
    "name": ("Name", ("Bundle enters Validation",)),
    "enabled": ("Create trigger", ("on",)),
    "event.eventType": ("Event", ("Governance: Bundle stage changed",)),
    "event.filter": ("Only when (optional)", ("Add condition", "toStage", "Validation", "project.id", "second project")),
    "titleTemplate": ("Task title (optional)", ("`titleTemplate`",)),
    "instructionTemplate": ("Instruction to the agent (optional)", ("`instructionTemplate`",)),
    "defaultResources": ("Pin resources to every task", ("none",)),
    "writeBack": ("Notifications", ("none",)),
}
SCHEDULE_FORM = {
    "type": ("Schedules", ("Add schedule",)),
    "name": ("Name", ("Weekly re-scan of approved Apps",)),
    "enabled": ("Create trigger", ("on",)),
    "schedule.cron": ("Cron schedule", ("0 6 * * 1",)),
    "schedule.timezone": ("Time zone", ("UTC",)),
    "project": ("Project (optional)", ("aml-validation-wizard",)),
    "titleTemplate": ("Task title (optional)", ("`titleTemplate`",)),
    "instructionTemplate": ("Instruction to the agent (optional)", ("`instructionTemplate`", "own project")),
    "defaultResources": ("Pin resources to every task", ("none",)),
    "writeBack": ("Notifications", ("none",)),
}
readme = every.get("README.md", "")


def section(title, level="##"):
    """The text of the README's `<level> <title>` part, up to the next heading of that level or higher."""
    stop = "|".join("#" * n + " " for n in range(1, len(level) + 1))
    m = re.search(rf"^{level} {re.escape(title)}\n(.*?)(?=^(?:{stop})|\Z)", readme, re.S | re.M)
    return m.group(1) if m else ""


def rows(part):
    """The table rows of `part` with three cells: [(label, value, [keys])]. The label is the text in quotes, the keys are the texts in
    backticks of the third cell."""
    out = []
    for ln in part.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")] if ln.startswith("|") else []
        if len(cells) == 3 and not set(cells[0]) <= set("-: ") and cells[0] != "Setting":
            out.append((cells[0].strip('"'), cells[1], re.findall(r"`([^`]+)`", cells[2])))
    return out


def keys(v, path="", leaf=True):
    """The keys of a JSON object, dotted: its leaves (leaf=True), or every key (leaf=False)."""
    if isinstance(v, dict) and v:
        return ([] if leaf or not path else [path]) + [p for k, x in v.items() for p in keys(x, f"{path}.{k}" if path else k, leaf)]
    return [path] if path else []


def has(cell, word):
    return re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", cell, re.I) is not None


def steps_case(what, part, reference, name, words):
    got = rows(part)
    by_key = {k: (label, value) for label, value, ks in got for k in ks}
    every_key = set(keys(reference, leaf=False))
    covered = {leaf: [k for k in by_key if leaf == k or leaf.startswith(k + ".")] for leaf in keys(reference)}
    check(f"the README's {what} have one row for each setting of {name}, with its key",
          got and all(len(v) == 1 for v in covered.values()) and set(by_key) <= every_key and set(by_key) == set(words),
          {"not one row": sorted(k for k, v in covered.items() if len(v) != 1), "not a key": sorted(set(by_key) - every_key),
           "not in this check": sorted(set(by_key) ^ set(words))})
    wrong = sorted(k for k, (label, value) in by_key.items() if k in words and (
        label != words[k][0] or not all(has(value, w) for w in words[k][1])
        or (words[k][1][:1] in (("on",), ("off",)) and not value.lower().startswith(words[k][1][0]))))
    check(f"...and each row has the wizard's label of its setting, and its value", got and not wrong,
          [(k, by_key.get(k), words[k]) for k in wrong])
    return got


wizard_rows = steps_case("wizard steps", section("Make it in the wizard"), ref, "agent.json", WIZARD)
wsteps = re.findall(r"^### (\d)\. (.+)$", section("Make it in the wizard"), re.M)
check("...in the wizard's six steps, in order: Basics, Model & runtime, Instructions & behaviors, Identity & sharing, Tools & "
      "permissions, Review", wsteps == [("1", "Basics"), ("2", "Model & runtime"), ("3", "Instructions & behaviors"),
                                       ("4", "Identity & sharing"), ("5", "Tools & permissions"), ("6", "Review")], wsteps)
sub_rows = steps_case("steps for the subscription", section("The subscription", "###"), sub, "subscription.json", SUBSCRIPTION_FORM)
sch_rows = steps_case("steps for the schedule", section("The schedule", "###"), sch, "schedule.json", SCHEDULE_FORM)
check("the README's Triggers tab has the subscription and the schedule", bool(section("The Triggers tab")))

rrule = shared.rules("the README says", readme, shared.blocks)
rrule("one wizard agent does the work of the three checks, for a person who writes no code", "writes no code", "one wizard agent",
      "three checks")
rrule("a wizard agent can't have an own tool or a custom subagent: the shell, the built-in subagent, Start Domino jobs",
      "can't have an own tool or a custom subagent", "shell", "built-in subagent", '"start domino jobs"')
rrule("the first skill is check 1's purpose-and-data, as it is", "purpose-and-data", "as it is", "does not change it")
rrule("before you make it: the second project, a copy of the demo project, with the demo branch as its default branch",
      "aml-validation-wizard", "copy of the demo project", "aml-validation-demo", "demo branch", "default branch")
rrule("...the three checks never see its bundles", "three checks never see its bundles")
rrule("...the service account is a Contributor of the second project", "service account", "contributor of the second project")
rrule("...and maps its Git credential to the second project's repository", "git credential", "maps it to the second project",
      "credentialmapping")
rrule("...the two store skills by hand on the Skills library page", "skills library", '"new skill"', '"edit"', '"save new version"')
rrule("...the model: the wizard lists only the models that you can call", "lists only the models", "you can call")
rrule("...the platform App polls the audit trail and pushes for real", "smoke_audit_poll_seconds", "smoke_push_dry_run=0")
rrule("do not apply a preset: it changes the access rows", '"apply preset"', "project datasets")
rrule("the token: Create one for me, a pasted token as the fallback, 24 hours", '"create one for me"', '"paste access token"',
      "24 hours")
rrule("the schedule part looks only at the bundles of the task's own project", "schedule", "task's own project",
      "never a bundle of another project")
rrule("...and the gateway refuses a bundle of another project too", "gateway also refuses", '"resources not attached to the task"')
rrule("Validation status does not show this agent: it finds each check's task by its agent's name", '"validation status"',
      "agent's name", '"not started"')
rrule("...the approver reads the three evidence items on the bundle page", "approver reads the three evidence items", "bundle page")
rrule("the live script compares the agent with compare.py diff", "compare.py diff agent.json", "get /api/agents/{id}")
rrule("...and the two triggers too", "compare.py diff subscription.json", "compare.py diff schedule.json",
      "get /api/agents/{id}/triggers")
rrule("...and checks the stored token's status", "identitycredential.status", "active")
check("the README says what one task leaves: the three docs, each with its file name",
      all(f"`docs/validation/{s}-<bundle ID>.md`" in readme for s in SKILLS), [s for s in SKILLS if s not in readme])
rrule("...pushed to the task branch, each one attached as a Report from GBP", "task branch", "`report`", "`gbp`")
rrule("...one result in three parts, each starting with ## <check name>", "three parts", "`## <check name>`")
rrule("how to run this check", "python tests/check_app_validation.py")
hub = text(ROOT / "governance" / "README.md")
check("governance/README.md (the hub of the three checks) names this folder, in its own section",
      f"`{FOLDER.relative_to(ROOT)}/`" in hub and "\n## One wizard agent for the three checks\n" in hub)
check("the root README's policy section lists this folder", f"| `{FOLDER.relative_to(ROOT)}/` |" in text(ROOT / "README.md"))

# ----------------------------------------------------------------------------------------- the public repo: no leak, no dash, no lane
leaks = shared.leaks(every)
check("no file of the folder has a Domino host, the ID of a Domino object or a token", not leaks, leaks)
dashed = sorted(rel for rel, body in [*every.items(), ("tests/check_app_validation.py", text(Path(__file__)))] if chr(0x2014) in body)
check("no file of the folder, and not this check, has an em dash", not dashed, dashed)
laned = sorted(f"{rel}: {m.group(0)}" for rel, body in every.items() if rel.endswith(".md")
               for m in re.finditer(r"\blanes?\b", re.sub(r"`[^`\n]*`", "", body), re.I))
check("the folder's Markdown says no 'lane' (the demo's words), but for the key `lane` of agent.json", not laned, laned)

service = os.environ.get("AGENT_SERVICE_REPO", "").strip()
if not service:
    done("AGENT_SERVICE_REPO is not set, so the tool names, the longest wait, the built-in subagent and the wizard's labels weren't "
         "checked against the service. Set it to a domino-agent-service checkout (governance/app-validation/README.md, \"The check\")")
service = Path(service).expanduser().resolve()
if not (service / "agent_runtime" / "gateway.py").is_file() or not (service / "static" / "js" / "pages" / "wizard.js").is_file():
    check(f"AGENT_SERVICE_REPO ({service}) is a domino-agent-service checkout (agent_runtime/gateway.py and static/js/pages/wizard.js)",
          False)
    done()
sys.path.insert(0, str(service))
from agent_runtime import gateway, proxies  # noqa: E402  (stdlib only, so any OS)

offered = {f"domino_{n}" for n in gateway.TOOLS} | {f"domino_{n}" for n in proxies.RELAY_TOOLS}
check("each tool that they name is a gateway tool or a relay tool of this service, as opencode names it (domino_<name>)",
      named and named <= offered, sorted(named - offered))
waits = [int(n) for n in re.findall(r"domino_wait_job\(jobId, seconds=(\d+)\)", vs)]
check("the skill's wait is the longest wait of wait_job for a harness agent (opencode's call stops at 60 s)",
      waits and all(w == gateway.WAIT_MAX["harness"] for w in waits), (waits, gateway.WAIT_MAX))
SUBAGENTS = text(service / "agent_service" / "custom_subagents.py")
check("the built-in subagent's name, general, is one of opencode's built-in subagents (the Subagents switch)",
      re.search(r'BUILTIN_OFF = \{"general":', SUBAGENTS) is not None)

# Each text in quotes in the README's tables is in the wizard's code, as a string. A few labels are built from parts (check 1's check).
JS = "\n".join(p.read_text() for p in sorted((service / "static" / "js").rglob("*.js")))
CATALOG = text(service / "agent_service" / "catalog.py")
BUILT = {"LLM Gateway models": ("'LLM Gateway'" in JS and "gatewayName()} models`" in JS),
         "<account>'s token": "idAccount()}'s token`" in JS,
         "Governance: Bundle stage changed": '"source": "Governance",\n        "name": "Bundle stage changed"' in CATALOG}
quoted = sorted({q for label, value, _ in wizard_rows + sub_rows + sch_rows for q in [label, *re.findall(r'"([^"]+)"', value)]})
unknown = [q for q in quoted if not BUILT.get(q) and not any(form in JS for form in (f"'{q}'", f'"{q}"', f"`{q}`", f"`{q}$" + "{"))]
check("each label and choice in quotes in the README's tables is the wizard's own text (its code in static/js)",
      len(quoted) > 40 and not unknown, unknown)
done()
