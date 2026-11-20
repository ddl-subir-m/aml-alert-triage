"""Check 1, "Purpose and data" (governance/check-purpose-and-data/): the wizard agent of the App validation demo, domino-agent-service
spec #388, Implementation Decision 8, ticket #395. A person makes the agent once in the App's wizard. The folder is its reference copy
in git: the store skill's text, the instructions, the settings as the wizard saves them, the event subscription, a helper that fills
and compares them, and a README with the wizard steps. Seen from outside, as check 2's check sees its agent folder.

With no service, it checks the files: the store skill's rules and the order of its tools, the instructions' rules, the reference
settings (each value of decision 8), the subscription's file (its filter and its two templates, which name the bundle ID), the
compare helper, the README's wizard steps (each setting of the reference settings, with the wizard's own label), and no Domino host,
ID or token (the repo is public). The names, the evidence item, the field labels, the verdicts and the severities come from
governance/checks.json.

With the service (AGENT_SERVICE_REPO, the path of a domino-agent-service checkout), it checks each tool name against the service's
gateway and relay (agent_runtime/gateway.py and proxies.py: stdlib, any OS). On Linux, it also starts that service over real HTTP with
a fake Domino (the service's seam helper, tests/agent_folder_seam.py):
  - The store skill is added through the skills API, and the agents API takes the reference settings (as the wizard's Save sends
    them) with that skill and the service account's token. The agent that it stores matches the reference settings.
  - The subscription is made from subscription.json. A stage move to Validation in the demo project starts one task, as the service
    account. A move to another stage, or in another project, starts none.
  - The Job's spec has the store skill, Run a Job off, Git push on and the access rows, and the gateway allows the writes on the
    event's bundle.
With AGENT_SERVICE_REPO unset, or not on Linux, those parts print a SKIP line. No Domino host: the live run is domino-agent-service
#397.

  python tests/check_purpose_and_data.py                                                   # the files only
  AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_purpose_and_data.py   # on Linux: everything (its README)
"""
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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


# ------------------------------------------------------------------------------------------------- the names (governance/checks.json)
try:
    CHECKS = json.loads(text(ROOT / "governance" / "checks.json"))
except ValueError as e:
    CHECKS = {}
    check("governance/checks.json is JSON", False, e)
mine = next((c for c in CHECKS.get("checks") or [] if c.get("name") == "Purpose and data"), {})
check("governance/checks.json names this check: Purpose and data, its evidence item and its folder",
      mine == {"name": "Purpose and data", "evidenceItem": "Validation: Purpose and data", "folder": "governance/check-purpose-and-data"},
      mine)
NAME = mine.get("name") or "Purpose and data"
EVIDENCE = mine.get("evidenceItem") or "Validation: Purpose and data"
FOLDER = ROOT / (mine.get("folder") or "governance/check-purpose-and-data")
LABELS = CHECKS.get("fields") or {}
VERDICTS = CHECKS.get("verdicts") or []
SEVERITIES = CHECKS.get("severities") or []

# --------------------------------------------------------------------------------------------------------------------- the files
FILES = ("README.md", "SKILL.md", "instructions.md", "agent.json", "subscription.json", "compare.py")
every = {p.relative_to(FOLDER).as_posix(): p.read_text() for p in sorted(FOLDER.rglob("*")) if p.is_file()
         and not any(part == "__pycache__" for part in p.relative_to(FOLDER).parts)} if FOLDER.is_dir() else {}
check(f"{FOLDER.relative_to(ROOT)}/ holds the reference copy and nothing else: {', '.join(FILES)}", sorted(every) == sorted(FILES),
      sorted(every))
skill, instructions = every.get("SKILL.md", ""), every.get("instructions.md", "")
top = re.match(r"---\n(.*?)\n---\n", skill, re.S)
check("SKILL.md, the store skill's text, has YAML on top with the name purpose-and-data and a description (else opencode never "
      "offers it)", bool(top) and re.search(r"^name: purpose-and-data$", top.group(1), re.M)
      and re.search(r"^description: \S.{20,}$", top.group(1), re.M), skill[:300])

# --------------------------------------------------------------------------------------------------- the checklist (the store skill)
# The rules of governance/README.md, as this check applies them. The doc's file name is #391's (governance/README.md, The three checks).
DOC = "docs/validation/purpose-and-data-<bundleId>.md"
lines = [ln.lower() for ln in skill.splitlines()]


def rule(name, *words):
    """One line of the skill says the rule: it holds every one of `words` (case aside)."""
    check(f"the skill says: {name}", any(all(w.lower() in ln for w in words) for ln in lines), words)


rule("read the bundle first", "domino_get_bundle", "bundleid")
rule("read the policy with the bundle's ID", "domino_get_policy", "bundleid")
rule("find its own evidence item by its exact name, and keep its ID", f'"{EVIDENCE}"', "evidence item", "exact", "id")
rule("find each field by its label (governance/checks.json)", "details.label",
     *(f'"{LABELS.get(k, k).lower()}"' for k in ("verdict", "severity", "summary", "doc")))
rule("a radio field takes one of its options' values", "radio", "details.options", "value")
rule("find the Intake values with get_policy: the stage Intake, its item Intake, and each field by its label", 'stage named "intake"',
     '"purpose"', '"users"', '"data class"', "details.label")
rule("...each field's value is its result.artifactContent, and a field with no result is not filled", "result.artifactcontent",
     "no `result`", "not filled")
rule("read the App's README, its start script and its code", "readme.md", "app.sh", "code")
rule("...and the sample data that the code loads", "sample data", "loads")
rule("the data classes are the Intake's four: Public, Internal, Confidential, Restricted", "public", "internal", "confidential",
     "restricted")
rule("judge the data class by the kind of data that the App is built to hold", "kind of data", "built to hold")
rule("...not by whether the sample data is fake: the doc can say that it is fake", "not by whether", "fake")
rule("compare the App with the Intake's Purpose, Users and Data class", "compare", "intake", "purpose", "users", "data class")
rule("an Intake data class lower than the data's class is S1 (the shared scale's example)", "data class", "lower", "s1")
rule("the severity scale is governance/README.md's", "governance/readme.md", "severity", "s0", "s3")
rule("the doc follows the shared template, at its own file name", "governance/validation-doc.md", DOC.lower())
rule("...with the shared top part and only its own middle part: delete the other two", "top part", f'"{NAME.lower()}"', "delete",
     "other two")
rule("...with every field replaced and every comment deleted", "{{field}}", "<!--")
rule("the doc says what this check could not check", "could_not_check", "default branch")
rule("the doc's own Doc location names only the file and the task branch (it is written before the push)", "doc_location",
     "before", "push")
FORM = f"agent/<task key>, {DOC}"   # governance/README.md's form for checks 1 and 2: the task branch and the file, with no commit
own = [re.findall(r"`([^`]+)`", ln)[1:] for ln in skill.splitlines() if ln.startswith("- `doc_location`")]
check(f"the doc's own Doc location has the one form of checks 1 and 2 (governance/README.md): `{FORM}`", own == [[FORM]], own)
rule("push the doc with git_push, and keep its branch, commit and dryRun", "domino_git_push", "branch", "commit", "dryrun")
rule("attach the doc: a Report from GBP, with the task branch and the push's commit", "domino_write_bundle_attachment", '"report"',
     '"gbp"', "branch", "commit", DOC.lower())
rule("...only when the push is on the remote (dryRun false)", "only when", "dryrun", "false")
rule("a dry-run push: attach nothing, and say so under what this check could not check", "dryrun", "true", "attach nothing",
     "could not check")
rule("file findings only in its own part, not code security", "only", "own part", "code security")
rule("...and nothing for another check's part: that check files it", "another check", "files it")
rule(f"each finding's name is [{NAME}] <what> in <where>", "domino_write_governance_finding", f'"[{NAME.lower()}] <what> in <where>"',
     "severity")
rule("file no false hit: it goes in the doc, with the reason", "no false hit", "reason")
rule("the verdict: do not approve when a real finding is S0 or S1", "do not approve", "s0 or s1")
rule("...approve when the highest is S2, S3 or none", "approve", "s2, s3 or `none`")
rule("...could not check when the check could not do its work, before the other two", "could not check", "could not do its work",
     "before")
rule("Highest severity is the highest of the real findings, or none", "highest severity", "real findings", "none")
rule("fill only its own evidence item, by the IDs from get_policy", "domino_write_policy_result", "only", f'"{EVIDENCE}"', "evidenceid")
rule("the Doc location is the task branch at the push's commit, with the doc's file", "<branch> at <commit>", DOC.lower())
rule("...or says that the doc is not in the repo", "not in the repo:", "the doc is in the task's result")
rule("a failed or denied call: go on with the other steps, and name it under what this check could not check", "fail", "denied",
     "go on", "could not check")
rule("the result goes to report_result, once, last", "domino_report_result", "once", "last")

order = ["domino_get_bundle", "domino_get_policy", "domino_git_push", "domino_write_bundle_attachment",
         "domino_write_governance_finding", "domino_write_policy_result", "domino_report_result"]
at = [skill.find(t) for t in order]
check("the checklist's tools come in order: bundle and policy, push, attachment, findings, evidence, result",
      all(i >= 0 for i in at) and at == sorted(at), dict(zip(order, at)))
check("the checklist starts no Domino Job (Run a Job is off): it names no domino_run_job", "domino_run_job" not in skill)
steps = [int(n) for n in re.findall(r"^## (\d+)\. ", skill, re.M)]
check("the checklist is numbered steps, in order", len(steps) >= 8 and steps == list(range(1, len(steps) + 1)), steps)
check("each step ends with its completion criterion (a 'Done when' line)",
      steps and all("Done when:" in part for part in re.split(r"^## \d+\. ", skill, flags=re.M)[1:]), steps)
result = [ln.strip() for ln in skill.split("\n## ")[-1].splitlines()]
want = [f"{LABELS.get('verdict')}: {' | '.join(VERDICTS)}", f"{LABELS.get('severity')}: {' | '.join(SEVERITIES)}",
        f"{LABELS.get('summary')}: ", f"{LABELS.get('doc')}: "]
got = [next((ln for ln in result if ln.startswith(w.split(":")[0] + ":")), None) for w in want]
check("the last step gives the result's four lines, in order, with checks.json's labels and the exact Verdict and severity values",
      all(got) and got[0] == want[0] and got[1] == want[1] and [result.index(g) for g in got] == sorted(result.index(g) for g in got),
      got)

# ------------------------------------------------------------------------------------------- the instructions (the system prompt)
ilines = [ln.lower() for ln in instructions.splitlines()]


def irule(name, *words):
    """One line of instructions.md says the rule: it holds every one of `words` (case aside)."""
    check(f"the instructions say: {name}", any(all(w.lower() in ln for w in words) for ln in ilines), words)


irule("load the store skill purpose-and-data first, and do its checklist in order", "first", "skill purpose-and-data", "in order")
irule("fill only its own evidence item", "only", "own evidence item", f'"{EVIDENCE}"')
irule(f"file only the real findings of its own part, each name starting with [{NAME}]", "only the real findings", "own part",
      f'"[{NAME.lower()}] "')
irule("judge the data class by the kind of data that the App is built to hold, not by whether the sample is fake", "kind of data",
      "built to hold", "not by whether", "fake")
irule("a false hit goes in the doc with its reason", "false hit", "doc", "reason")
irule("say what it could not check, in the doc and in the result", "could not check", "doc", "result")
irule("nobody answers an event task: no question and no access request", "nobody answers", "domino_ask_user", "domino_request_access")
irule("the checklist's writes are the task's work: no asking first", "push", "attachment", "findings", "evidence", "without asking")
irule("end with report_result, once, last", "domino_report_result", "once", "last")

# --------------------------------------------------------------------------------------------------------------- the tool names
# opencode names a tool of the relay's MCP server `domino` as domino_<name> (the service's agent_runtime/gateway.py)
NAMES = {"domino_get_bundle", "domino_get_policy", "domino_git_push", "domino_write_bundle_attachment",
         "domino_write_governance_finding", "domino_write_policy_result", "domino_report_result", "domino_ask_user",
         "domino_request_access"}
named = set(re.findall(r"\bdomino_[a-z_]+", skill + instructions))
check("the skill and the instructions name the checklist's Domino tools, and no other", named == NAMES, sorted(named ^ NAMES))
bare = sorted(set(re.findall(r"(?<![a-z_`])(?:get_bundle|get_policy|run_job|git_push|write_[a-z_]+|report_result)\(",
                             skill + instructions)))
check("they call no tool by its plain name (a framework agent's name): a harness agent has only the domino_ names", not bare, bare)

# ---------------------------------------------------------------------------------------------------- the reference settings
# agent.json: the agent as the wizard's Save sends it (POST /api/agents: the draft of the service's static/js/pages/wizard.js), with
# placeholders for the names and IDs of a deployment. Its values are #388 decision 8's. compare.py fills it and compares it.
MODEL = "google/gemini-3.8-flash"   # not sonnet: Anthropic's cyber safeguards refuse this work (domino-agent-service#270)
LIMITS = {"maxRuntimeMin": 45, "maxTurns": 120, "idleWaitMin": 0}   # check 2's (#260's folder validator: 45 minutes, 120 turns, no wait)
SA, ANALYST, APPROVER = "__SERVICE_ACCOUNT__", "__ANALYST__", "__APPROVER__"
try:
    ref = json.loads(every.get("agent.json", ""))
except ValueError as e:
    ref = {"error": str(e)}
ref = ref if isinstance(ref, dict) else {}
g = ref.get("guardrails") or {}
check("agent.json is the agent's settings, in the order of the wizard's steps, with no other key",
      list(ref) == ["lane", "name", "description", "tags", "scope", "inputs", "model", "execution", "systemPrompt", "directTrigger",
                    "skills", "completion", "onError", "identity", "access", "guardrails"], list(ref))
check(f"its title is the check's name, {NAME!r}: Validation status finds the check's task by its agent's name",
      ref.get("name") == NAME and ref.get("description"), (ref.get("name"), ref.get("description")))
check("it is a harness agent (the card Domino Agent Harness), for any project, with a required project input",
      ref.get("lane") == "harness" and ref.get("scope") == {"type": "global"} and ref.get("tags") == []
      and ref.get("inputs") == [{"name": "project", "type": "project", "required": True, "multiple": False, "description": ""}],
      {k: ref.get(k) for k in ("lane", "scope", "tags", "inputs")})
check(f"its model is the LLM Gateway alias {MODEL}, with the grants of the identity that it acts as",
      ref.get("model") == {"source": "gateway", "models": [MODEL], "access": "acting"}, ref.get("model"))
check("its Environment is the harness's, by name, and its limits are check 2's: 45 minutes, 120 turns, no wait for an answer",
      ref.get("execution") == {"environment": {"name": "Domino Agent Runtime (opencode)"}, **LIMITS}, ref.get("execution"))
check2 = text(ROOT / "governance" / "check-architecture-and-access" / "definition.md")
got2 = {k: int(m.group(1)) if (m := re.search(rf"^  {k}: (\d+)", check2, re.M)) else None for k in ("minutes", "turns", "wait-minutes")}
check("...the same limits as check 2's definition.md", got2 == {"minutes": 45, "turns": 120, "wait-minutes": 0}, got2)
check("its system prompt is instructions.md (a placeholder that compare.py fills)", ref.get("systemPrompt") == "__INSTRUCTIONS__",
      ref.get("systemPrompt"))
check("its skill is the store skill purpose-and-data, as the wizard's picker names it (its ID and version come from the store)",
      ref.get("skills") == [{"id": "__SKILL_ID__", "name": "purpose-and-data", "version": "__SKILL_VERSION__"}], ref.get("skills"))
check("a person closes the task, a failure ends it with a report (Error recovery: Fail and report), with no plan and no check-ins",
      ref.get("completion") == "review" and ref.get("onError") == "fail" and g.get("planFirst") is False
      and g.get("checkInOften") is False, (ref.get("completion"), ref.get("onError"), g.get("planFirst"), g.get("checkInOften")))
check("no suggested prompt and no notification for a task started by hand",
      ref.get("directTrigger") == {"starterPrompts": [], "writeBack": []}, ref.get("directTrigger"))
check("it acts as a service account (a placeholder: no user name in the public repo)",
      ref.get("identity") == {"mode": "service_account", "serviceAccount": {"userName": SA}}, ref.get("identity"))
check("it is shared with specific people: the analyst who moves the stage, and the approver as an editor (to read its tasks)",
      ref.get("access") == {"mode": "restricted", "users": [ANALYST], "editors": [APPROVER]}, ref.get("access"))
check("its tools: Shell on, Web fetch off, Subagents off, Start Domino jobs off (Run a Job off), Git push on",
      g.get("tools") == {"bash": True, "web": False, "subagents": False, "jobs": False, "push": True}, g.get("tools"))
check("its Resource access: Project files Read & write (the push needs it), Project datasets No access, Other resources attached "
      "to the task Read & write (the event's bundle), Resources not attached to the task No access",
      g.get("access") == {"project": "write", "data": "none", "inputs": {}, "named": "write", "other": "none"}, g.get("access"))
check("its outbound traffic: Domino services only", g.get("network") == {"mode": "domino", "domains": []}, g.get("network"))
check("guardrails has the wizard's five parts and no other", sorted(g) == ["access", "checkInOften", "network", "planFirst", "tools"],
      sorted(g))

# ------------------------------------------------------------------------------------------------------------- the compare helper
# compare.py runs with the stdlib only, as the live script runs it: `fill` gives the body to send, `diff` compares a read-back.
import atexit  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

HELPER = FOLDER / "compare.py"
VALUES = {"__SERVICE_ACCOUNT__": "sa-one", "__ANALYST__": "ana", "__APPROVER__": "abe", "__SKILL_ID__": "skl_one",
          "__SKILL_VERSION__": "0.1.0", "__DEMO_PROJECT_ID__": "proj-one"}
SETS = [x for k, v in VALUES.items() for x in ("--set", f"{k}={v}")]
work = Path(tempfile.mkdtemp(prefix="check-purpose-and-data-"))
atexit.register(shutil.rmtree, work, ignore_errors=True)


def helper(*args):
    """compare.py with `args`, as `python3 -I -S` runs it (no site-packages, no current folder). -> (exit code, stdout + stderr)"""
    p = subprocess.run([sys.executable, "-I", "-S", str(HELPER), *args], capture_output=True, text=True, timeout=60, cwd=work)
    return p.returncode, p.stdout + p.stderr


code, out = helper("fill", "agent.json", *SETS)
try:
    body = json.loads(out) if code == 0 else {}
except ValueError:
    body = {}
check("compare.py fill agent.json gives the body to send, with each placeholder filled and the system prompt from instructions.md",
      code == 0 and "__" not in json.dumps(body) and body.get("systemPrompt") == instructions.strip()
      and (body.get("identity") or {}).get("serviceAccount") == {"userName": "sa-one"}
      and body.get("access") == {"mode": "restricted", "users": ["ana"], "editors": ["abe"]}
      and body.get("skills") == [{"id": "skl_one", "name": "purpose-and-data", "version": "0.1.0"}], (code, out[:400]))
code, out = helper("fill", "agent.json", *SETS[:-4])
check("...and refuses, naming it, when a placeholder has no value", code != 0 and "__SKILL_VERSION__" in out and "{" not in out,
      (code, out[:300]))


def stored(b):
    """`b` as GET /api/agents/{id} answers for it: the service's app.py _agent_summary adds its own keys, and a stored agent has the
    values of the deployment (the IDs, the hardware tier, the owner, the credential's record)."""
    s = json.loads(json.dumps(b))
    s.update(id="agt_x", owner={"userName": "someone"}, createdAt="2026-11-19T00:00:00Z", enabled=True, harness={"id": "domino-agent"},
             identityCredential={"status": "active", "account": "sa-one", "last4": "abcd"}, stats={"tasks": 0}, canUse=True)
    s["identity"]["serviceAccount"].update(id="u-1", idpId="idp-1")
    s["execution"].update(hardwareTier="small-k8s", environment={"id": "env-1", "name": "Domino Agent Runtime (opencode)"})
    s["skills"][0]["version"] = "0.1.0"
    s["directTrigger"] = {"id": "trg_dir_agt_x", "enabled": True, "starterPrompts": [], "defaultResources": [], "defaultRuntime": None,
                          "writeBack": []}
    s["systemPrompt"] = instructions.strip() + "\n"   # a paste can end with a new line
    return s


def diff(reference, got):
    path = work / "read-back.json"
    path.write_text(json.dumps(got))
    return helper("diff", reference, str(path), *SETS)


if body:
    code, out = diff("agent.json", stored(body))
    check("compare.py diff agent.json <read-back> finds no difference in the agent as the service stores it: it compares only "
          "the keys of the reference (no ID, no owner, no hardware tier), and text with no space at its ends",
          code == 0 and out.strip().splitlines()[-1:] == ["Same as agent.json."], (code, out[:400]))
    wrong = stored(body)
    wrong["guardrails"]["tools"]["subagents"] = True   # the wizard's default for Subagents is on
    wrong["access"]["editors"] = []
    code, out = diff("agent.json", wrong)
    check("...and names each setting that differs, with the wanted and the stored value, and exits 1",
          code == 1 and "guardrails.tools.subagents: wants false, has true" in out and "access.editors: wants [\"abe\"], has []" in out,
          (code, out[:400]))
    gone = stored(body)
    del gone["guardrails"]["tools"]["push"]
    gone["skills"] = []
    code, out = diff("agent.json", gone)
    check("...also a setting that is missing, and a list of another length",
          code == 1 and "guardrails.tools.push: missing" in out and "skills: wants 1 item, has 0" in out, (code, out[:400]))

# ------------------------------------------------------------------------------------------------- the event subscription's file
# The body of `POST /api/agents/{id}/triggers` (the service's agent_write.create_trigger), as the Triggers tab's "New event
# subscription" sends it (static/js/pages/agent_detail.js TriggerModal). Its one placeholder is the demo project's ID: the live script
# fills it (no Domino ID in the public repo).
PROJECT_ID = "__DEMO_PROJECT_ID__"
# The fields of a governance.bundle.stage_changed payload, as the service's audit poller builds it (agent_service/audit_source.py)
PAYLOAD = ("source", "triggeredBy", "occurredAt", "auditTraceId", "bundle.id", "bundle.name", "fromStage", "toStage", "policy.id",
           "policy.name", "project.id", "project.name")
try:
    sub = json.loads(every.get("subscription.json", ""))
except ValueError as e:
    sub = {"error": str(e)}
sub = sub if isinstance(sub, dict) else {}
event = sub.get("event") or {}
check("subscription.json is an event subscription to governance.bundle.stage_changed, on, with the keys of the Triggers tab's form",
      sub.get("type") == "event" and event.get("eventType") == "governance.bundle.stage_changed" and sub.get("enabled") is True
      and sub.get("name") == "Bundle enters Validation" and list(sub) == ["type", "name", "enabled", "event", "titleTemplate", "instructionTemplate",
                                            "defaultResources", "writeBack"], {k: sub.get(k) for k in ("type", "name", "enabled", "error")})
policy_yaml = text(ROOT / "governance" / "app-deployment-policy.yaml")
check("its filter: the bundle moved to the policy's stage named Validation (exact: the filter compares strings), in the demo project",
      event.get("filter") == [{"field": "toStage", "op": "equals", "value": "Validation"},
                              {"field": "project.id", "op": "equals", "value": PROJECT_ID}]
      and re.search(r"^  - name: Validation$", policy_yaml, re.M), event.get("filter"))
title, instruction = sub.get("titleTemplate") or "", sub.get("instructionTemplate") or ""
check("its title template is the check's name and the bundle ID (Validation status's task search matches the title and the key only)",
      title == f"{NAME}: bundle {{{{bundle.id}}}}", title)
check("its instruction template names the bundle ID and name, the store skill, and says to fill only its own evidence item (the "
      "one form of the three checks' subscriptions)", "{{bundle.id}}" in instruction and "{{bundle.name}}" in instruction
      and f'fill only the evidence item "{EVIDENCE}"' in instruction and "purpose-and-data" in instruction, instruction)
fields = set(re.findall(r"\{\{([^}]+)\}\}", title + instruction))
check("each placeholder of the two templates is a field of the stage-change payload (a field that isn't stays as {{...}})",
      fields and fields <= set(PAYLOAD), sorted(fields - set(PAYLOAD)))
check("it pins no resource and writes nothing back: the event names the bundle and the project",
      sub.get("defaultResources") == [] and sub.get("writeBack") == [], {k: sub.get(k) for k in ("defaultResources", "writeBack")})
code, out = helper("fill", "subscription.json", *SETS)
try:
    sbody = json.loads(out) if code == 0 else {}
except ValueError:
    sbody = {}
check("compare.py fill subscription.json puts the demo project's ID in its one placeholder",
      code == 0 and ((sbody.get("event") or {}).get("filter") or [{}, {}])[1:] == [{"field": "project.id", "op": "equals",
                                                                                    "value": "proj-one"}], (code, out[:300]))
if sbody:   # GET /api/agents/{id}/triggers: the direct trigger and the subscription, as the service stores them
    listed = [{"id": "trg_dir_agt_x", "type": "direct", "name": "Direct runs", "enabled": True},
              {**sbody, "id": "trg_1", "agentId": "agt_x", "createdBy": "someone", "fireCount": 0, "lastFiredAt": None, "description": None}]
    code, out = diff("subscription.json", listed)
    check("compare.py diff subscription.json <triggers> compares the subscription with its name, and finds no difference",
          code == 0 and out.strip().endswith("Same as subscription.json."), (code, out[:300]))
    listed[1]["event"] = {**listed[1]["event"], "filter": listed[1]["event"]["filter"][:1]}
    code, out = diff("subscription.json", listed)
    check("...and names a filter that misses the demo project", code == 1 and "event.filter: wants 2 items, has 1" in out, (code, out[:300]))

# ------------------------------------------------------------------------------------------------------- the README's wizard steps
# The person makes the agent once, from the README's tables: one row for each setting, with the wizard's own label (in quotes), the
# value to set, and the setting's key in agent.json (in backticks). The words are the wizard's (the service's static/js: pages/wizard.js,
# pages/wizard_framework.js, pages/agent_detail.js, core.js, components.js). For each key: its label, and the words of its value.
WIZARD = {
    "lane": ("What runs the agent?", ("Domino Agent Harness (opencode)",)),
    "name": ("Name", ("Purpose and data",)),
    "description": ("Description", ("`description`", "agent.json")),
    "tags": ("Tags", ("none",)),
    "scope": ("Where can it work?", ("Any project",)),
    "inputs": ("Project required as trigger input", ("checked",)),
    "guardrails.access.inputs": ("Inputs", ("only the project",)),
    "model.access": ("Model access", ("Whoever triggers it", "Agent identity")),
    "model.source": ("Custom endpoint", ("off",)),
    "model.models": ("LLM Gateway models", (MODEL, "only")),
    "execution.environment": ("Environment", ("Domino Agent Runtime (opencode)",)),
    "execution.maxRuntimeMin": ("Max minutes per round", ("45",)),
    "execution.maxTurns": ("Max turns per round", ("120",)),
    "execution.idleWaitMin": ("Wait for answers (min)", ("0",)),
    "systemPrompt": ("System prompt", ("instructions.md",)),
    "directTrigger.starterPrompts": ("Suggested prompts (optional)", ("none",)),
    "skills": ("Skills", ("purpose-and-data",)),
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
    "guardrails.tools.subagents": ("Subagents", ("off",)),
    "guardrails.tools.jobs": ("Start Domino jobs", ("off",)),
    "guardrails.tools.push": ("Git push", ("on",)),
    "guardrails.network": ("Outbound traffic", ("Domino services only",)),
}
TRIGGERS_TAB = {   # the same for subscription.json, on the Triggers tab's form "New event subscription"
    "type": ("Event subscriptions", ("Add subscription",)),
    "name": ("Name", ("Bundle enters Validation",)),
    "enabled": ("Create trigger", ("on",)),
    "event.eventType": ("Event", ("Governance: Bundle stage changed",)),
    "event.filter": ("Only when (optional)", ("Add condition", "toStage", "Validation", "project.id", "demo project")),
    "titleTemplate": ("Task title (optional)", ("`titleTemplate`",)),
    "instructionTemplate": ("Instruction to the agent (optional)", ("`instructionTemplate`",)),
    "defaultResources": ("Pin resources to every task", ("none",)),
    "writeBack": ("Notifications", ("none",)),
}
readme = every.get("README.md", "")


def section(title):
    """The text of the README's `## <title>` part, up to the next `## `."""
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", readme, re.S | re.M)
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


def steps_case(what, part, reference, words):
    got = rows(part)
    by_key = {k: (label, value) for label, value, ks in got for k in ks}
    every_key = set(keys(reference, leaf=False))
    covered = {leaf: [k for k in by_key if leaf == k or leaf.startswith(k + ".")] for leaf in keys(reference)}
    check(f"the README's {what} have one row for each setting of {'agent.json' if reference is ref else 'subscription.json'}, "
          "with its key", got and all(len(v) == 1 for v in covered.values()) and set(by_key) <= every_key and set(by_key) == set(words),
          {"not one row": sorted(k for k, v in covered.items() if len(v) != 1), "not a key": sorted(set(by_key) - every_key),
           "not in this check": sorted(set(by_key) ^ set(words))})
    wrong = sorted(k for k, (label, value) in by_key.items() if k in words and (
        label != words[k][0] or not all(has(value, w) for w in words[k][1])
        or (words[k][1] in (("on",), ("off",)) and not value.lower().startswith(words[k][1][0]))))
    check(f"...and each row has the wizard's label of its setting, and its value", got and not wrong,
          [(k, by_key[k], words[k]) for k in wrong])
    return got


wizard_rows = steps_case("wizard steps", section("Make it in the wizard"), ref, WIZARD)
steps = re.findall(r"^### (\d)\. (.+)$", section("Make it in the wizard"), re.M)
check("...in the wizard's six steps, in order: Basics, Model & runtime, Instructions & behaviors, Identity & sharing, Tools & "
      "permissions, Review", steps == [("1", "Basics"), ("2", "Model & runtime"), ("3", "Instructions & behaviors"),
                                      ("4", "Identity & sharing"), ("5", "Tools & permissions"), ("6", "Review")], steps)
tab_rows = steps_case("steps on the Triggers tab", section("The subscription, on the Triggers tab"), sub, TRIGGERS_TAB)


def blocks(md):
    """The paragraphs, list items and table rows of the Markdown text `md`, each on one line (the README wraps its lines)."""
    out = []
    for para in re.split(r"\n\s*\n", md):
        item = []
        for ln in para.splitlines():
            if item and re.match(r"\s*(- |\| |\d+\. |#|```)", ln):
                out.append(" ".join(item))
                item = []
            item.append(ln.strip())
        if item:
            out.append(" ".join(item))
    return out


rlines = [b.lower() for b in blocks(readme)]


def rrule(name, *words):
    """One paragraph, list item or table row of the folder's README.md says it: it holds every one of `words` (case aside)."""
    check(f"the README says: {name}", any(all(w.lower() in ln for w in words) for ln in rlines), words)


rrule("the store skill must exist first: the live script adds it with the skills API", "store skill", "first", "post /api/skills")
rrule("...a second add with the same name is refused: find it by its name, and change its text", "already exists",
      "get /api/skills", "put /api/skills/{id}")
rrule("...or by hand, on the Skills library page", "skills library", '"new skill"', '"save new version"')
rrule("the token: the checkbox Create one for me, which uses your own permission", '"create one for me"', "your own permission")
rrule("...or, as the fallback, a pasted token of the service account", "fallback", '"paste access token"')
rrule("...which lasts 24 hours: rotate it before a later run", "24 hours", '"rotate: create a new token for me"')
rrule("the model: the wizard lists only the models that you can call", "lists only the models", "you can call")
rrule("do not apply a preset: it changes the access rows", '"apply preset"', "project datasets")
rrule("the Hardware tier and the token are not compared", '"hardware tier"', "not compared")
rrule("the service account's rights: Contributor on the demo project, the model, the bundle", "service account", "contributor",
      "llm gateway", "bundle")
rrule("the service account's Git credential, with write access to the repo (the push)", "git credential", "write access", "push")
rrule("share it with the analyst who moves the stage, else a stage move starts no task", "analyst", "is not allowed to use agent")
rrule("...and with the approver as an editor, else Validation status shows not started", "approver", "editor", "not started")
rrule("the platform App polls the audit trail", "smoke_audit_poll_seconds")
rrule("...and pushes for real, else the push is a dry run and the doc isn't attached", "smoke_push_dry_run=0", "dry run", "attach")
rrule("the demo project's default branch has the shared parts", "default branch", "governance/validation-doc.md", "governance/readme.md")
rrule("the live script compares the agent with compare.py diff", "compare.py diff agent.json", "get /api/agents/{id}")
rrule("...and the subscription too", "compare.py diff subscription.json", "get /api/agents/{id}/triggers")
rrule("...and checks the stored token's status, which no reference file holds", "identitycredential.status", "active")
rrule("how to run this check", "python tests/check_purpose_and_data.py")
hub = text(ROOT / "governance" / "README.md")
check("governance/README.md (the hub of the three checks) names this folder", f"`{FOLDER.relative_to(ROOT)}/`" in hub)

# ----------------------------------------------------------------------------------------------- the public repo: no leak, no dash
leaks = sorted({f"{rel}: {m.group(0)}" for rel, body in every.items()
                for m in re.finditer(r"[0-9a-f]{24}|agt_[0-9a-z]{6,}|skl_[0-9a-z]{6,}|[\w.-]+\.domino\.tech|apps-internal/[0-9a-f]+"
                                     r"|eyJ[\w-]{20,}", body)})
check("no file of the folder has a Domino host, the ID of a Domino object or a token", not leaks, leaks)
dashed = sorted(rel for rel, body in [*every.items(), ("tests/check_purpose_and_data.py", text(Path(__file__)))] if chr(0x2014) in body)
check("no file of the folder, and not this check, has an em dash", not dashed, dashed)

service = os.environ.get("AGENT_SERVICE_REPO", "").strip()
if not service:
    done("AGENT_SERVICE_REPO is not set, so the tool names, the wizard's labels, the agents API and the event's task weren't checked "
         "against the service. Set it to a domino-agent-service checkout (governance/check-purpose-and-data/README.md, \"The check\")")
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

# Each text in quotes in the README's tables (a label, or a choice of the wizard) is in the wizard's code, as a string. A few labels are
# built from parts: the gateway's name, the account's name, the event's source and name (the service's agent_service/catalog.py).
JS = "\n".join(p.read_text() for p in sorted((service / "static" / "js").rglob("*.js")))
CATALOG = text(service / "agent_service" / "catalog.py")
BUILT = {"LLM Gateway models": ("'LLM Gateway'" in JS and "gatewayName()} models`" in JS),
         "<account>'s token": "idAccount()}'s token`" in JS,
         "Governance: Bundle stage changed": '"source": "Governance",\n        "name": "Bundle stage changed"' in CATALOG}
quoted = sorted({q for label, value, _ in wizard_rows + tab_rows for q in [label, *re.findall(r'"([^"]+)"', value)]})
unknown = [q for q in quoted if not BUILT.get(q) and not any(form in JS for form in (f"'{q}'", f'"{q}"', f"`{q}`", f"`{q}$" + "{"))]
check("each label and choice in quotes in the README's tables is the wizard's own text (its code in static/js)",
      len(quoted) > 40 and not unknown, unknown)

# ------------------------------------------------------------------------------ the store skill and the agents API, on Linux
if not ref or not skill:
    done()   # the first part said why: there is no reference to make the agent from
if not (service / "tests" / "agent_folder_seam.py").is_file():
    check(f"AGENT_SERVICE_REPO ({service}) has the seam helper (tests/agent_folder_seam.py)", False)
    done()
if not sys.platform.startswith("linux"):
    done("needs Linux for the agents API and the event's task: the service's app imports agent_runtime/sandbox.py. On a Mac, run it "
         "with Docker, in the image of the service's checks (governance/check-purpose-and-data/README.md, \"The check\")")
import importlib.util  # noqa: E402

sys.path.insert(0, str(service / "tests"))
import agent_folder_seam as seam  # noqa: E402  (the service's seam helper, from AGENT_SERVICE_REPO)

loader = importlib.util.spec_from_file_location("compare_purpose_and_data", HELPER)
compare = importlib.util.module_from_spec(loader)
loader.loader.exec_module(compare)   # the helper that the live script runs, as a module
seam.GATEWAY.append({"id": MODEL, "providerType": "openai", "capabilities": ["chat", "tools"]})   # the seam's catalog has no such alias
seam.start()
OWNER, PEOPLE_ANALYST, PEOPLE_APPROVER, ACCOUNT = "olivia", "rita", "bob", "purpose-data-sa"   # people of the seam's fake Domino
token = seam.add_person(ACCOUNT)   # the service account: the fake Domino knows its token
try:
    import requests  # noqa: E402  (the service's checks image has it)
    from agent_service import audit_source, domino  # noqa: E402

    # The store skill, as the live script adds it: the skills API, with SKILL.md as its text and its description from its top
    skill_body = {"name": "purpose-and-data", "description": re.search(r"^description: (.+)$", top.group(1), re.M).group(1),
                  "content": skill, "scope": "personal"}
    r = seam.api("POST", "/api/skills", OWNER, json=skill_body)
    store = r.json() if r.status_code == 200 else {}
    check("the store skill is added through the skills API (POST /api/skills), with SKILL.md as its text",
          r.status_code == 200 and store.get("name") == "purpose-and-data" and store.get("content") == skill
          and str(store.get("id")).startswith("skl_") and store.get("version"), (r.status_code, r.text[:300]))
    r = seam.api("POST", "/api/skills", OWNER, json=skill_body)
    check("a second add with the same name is refused, so the live script finds the skill by its name first",
          r.status_code == 400 and "A skill named 'purpose-and-data' already exists" in r.text, (r.status_code, r.text[:300]))
    listed = seam.api("GET", "/api/skills", OWNER).json()
    check("GET /api/skills lists it once, by its name, as the wizard's step 3 lists the skills",
          [s.get("id") for s in listed if s.get("name") == "purpose-and-data"] == [store.get("id")], [s.get("name") for s in listed])

    # The agent, as the wizard's Save sends it: the reference settings filled by compare.py, and the token on its own
    values = {"__SERVICE_ACCOUNT__": ACCOUNT, "__ANALYST__": PEOPLE_ANALYST, "__APPROVER__": PEOPLE_APPROVER,
              "__SKILL_ID__": store.get("id", ""), "__SKILL_VERSION__": store.get("version", "")}
    body = compare.fill(compare.load("agent.json"), values)
    r = seam.api("POST", "/api/agents", OWNER, json=body)
    check("the agents API refuses the settings with no token: an agent that acts as a service account needs its token",
          r.status_code == 400 and ACCOUNT in r.text and "token" in r.text, (r.status_code, r.text[:300]))
    r = seam.api("POST", "/api/agents", OWNER, json={**body, "identityCredentialToken": token})
    a = r.json() if r.status_code == 200 else {}
    aid = a.get("id")
    check("the agents API (POST /api/agents) takes the reference settings, with the store skill from the skills API and the service "
          "account's token", r.status_code == 200 and a.get("lane") == "harness" and a.get("name") == NAME, (r.status_code, r.text[:400]))
    got = seam.api("GET", f"/api/agents/{aid}", OWNER).json() if aid else {}
    found = compare.differences(body, got)
    check("the agent as the App stores it (GET /api/agents/{id}) has each setting of the reference: compare finds no difference",
          got and not found, found)
    (work / "agent-read-back.json").write_text(json.dumps(got))
    code, out = helper("diff", "agent.json", str(work / "agent-read-back.json"),
                       *[x for k, v in values.items() for x in ("--set", f"{k}={v}")])
    check("...and so does compare.py diff, as the live script runs it on that answer", code == 0 and "Same as agent.json." in out,
          (code, out[:400]))
    check("its stored token is active, for the service account (no reference file holds it)",
          (got.get("identityCredential") or {}).get("status") == "active"
          and (got.get("identityCredential") or {}).get("account") == ACCOUNT, got.get("identityCredential"))
    check("the store skill says that the agent uses it (the skills library's Used by)",
          [u.get("id") for s in seam.api("GET", "/api/skills", OWNER).json() if s.get("name") == "purpose-and-data"
           for u in s.get("usedBy") or []] == [aid])

    # The subscription, from subscription.json with the demo project's ID: here the seam's Git-based project
    sbody = compare.fill(compare.load("subscription.json"), {"__DEMO_PROJECT_ID__": seam.PROJECT["id"]})
    r = seam.api("POST", f"/api/agents/{aid}/triggers", OWNER, json=sbody)
    trigger = r.json() if r.status_code == 200 else {}
    check("the owner makes the subscription from subscription.json (POST /api/agents/{id}/triggers)",
          r.status_code == 200 and trigger.get("type") == "event" and trigger.get("enabled") is True, (r.status_code, r.text[:300]))
    triggers = seam.api("GET", f"/api/agents/{aid}/triggers", OWNER).json()
    found = compare.differences(sbody, compare.pick(sbody, triggers) or {})
    check("the subscription as the App stores it (GET /api/agents/{id}/triggers) has each setting of subscription.json", not found, found)

    # A stage move reaches it as the audit poller publishes it: Domino's audit row (AuditEvent, as the service's tests/check_phase3.py
    # audit_event() copies a real stage move), made into the payload by the poller's own audit_source.to_payload, then published
    # through the subscription's test route, which runs the same fan-out (service.emit_event) as the person who calls it.
    BUNDLE = {"id": "4f2b7c1e-0d3a-4e5f-9a8b-7c6d5e4f3a21", "name": "aml-case-management v7"}
    real_get = domino.get

    def bundle_get(path, params=None, cache=True, token=None, credential=None):
        """The fake Domino also answers the event bundle's GET (GET /api/governance/v1/bundles/{id}: guardrails.Bundle of the
        service's reference_materials/domino-api-specs/api-governance.swagger.json), a bundle of the task's project."""
        if path == f"/api/governance/v1/bundles/{BUNDLE['id']}":
            return {"id": BUNDLE["id"], "name": BUNDLE["name"], "projectId": seam.PROJECT["id"], "projectName": seam.PROJECT["name"],
                    "policyId": "pol-app-deployment", "policyName": "App deployment policy", "stage": "Validation", "state": "Active"}
        return real_get(path, params, cache=cache, token=token, credential=credential)

    domino.get = bundle_get

    def stage_move(to="Validation", project=None, by=PEOPLE_ANALYST):
        """The payload of one stage move of BUNDLE, from Intake to `to`, in `project` (the seam's project by default)."""
        ent = lambda kind, id_, name_: {"entityType": kind, "id": id_, "name": name_, "tags": []}
        p = project or (seam.PROJECT["id"], seam.PROJECT["name"])
        row = {"timestamp": 1795000000000, "actor": {"id": f"u-{by}", "name": by},
               "action": {"eventName": "Change Governance Bundle Stage", "using": [ent("eventSource", "Web", None)], "traceId": "tr-395"},
               "targets": [{"entity": ent("governanceBundle", BUNDLE["id"], BUNDLE["name"]),
                            "fieldChanges": [{"fieldType": "scalar", "fieldName": "stage", "before": "Intake", "after": to}]}],
               "affecting": [ent("governancePolicy", "pol-app-deployment", "App deployment policy")], "in": ent("project", *p)}
        return audit_source.to_payload("governance.bundle.stage_changed", row)

    def fire(payload, person):
        """Publish `payload` to the subscription as `person`. -> the event's `fired` list (one entry for each agent it reached)."""
        r = seam.api("POST", f"/api/triggers/{trigger.get('id')}/test", person, json={"payload": payload})
        return r.json().get("fired") if r.status_code == 200 else (r.status_code, r.text[:300])

    fired = fire(stage_move(by="alice"), "alice")
    check("a stage move by a person who is not in People starts no task: the analyst who moves the stage must be in People",
          isinstance(fired, list) and len(fired) == 1 and "is not allowed to use agent" in (fired[0].get("error") or ""), fired)
    n = len(seam.JOBS)
    fired = fire(stage_move(), PEOPLE_ANALYST)
    check("a stage move to Validation in the demo project starts one task, which acts as the service account, not as the analyst",
          isinstance(fired, list) and len(fired) == 1 and fired[0].get("taskId") and fired[0].get("actingAs") == ACCOUNT, fired)
    task_id = fired[0].get("taskId") if isinstance(fired, list) and fired else None
    task = seam.api("GET", f"/api/tasks/{task_id}", OWNER).json() if task_id else {}
    check("the task's title is the check's name and the bundle ID, from the title template",
          task.get("title") == f"{NAME}: bundle {BUNDLE['id']}", task.get("title"))
    check("its instruction names the bundle ID and its own evidence item, from the instruction template",
          BUNDLE["id"] in (task.get("instruction") or "") and f'"{EVIDENCE}"' in (task.get("instruction") or "")
          and "{{" not in (task.get("instruction") or ""), task.get("instruction"))
    r = seam.api("GET", f"/api/tasks/{task_id}", PEOPLE_APPROVER)
    check("the approver (an editor) can read the task, as Validation status does", r.status_code == 200, r.status_code)
    found = seam.api("GET", "/api/tasks", PEOPLE_APPROVER, params={"q": BUNDLE["id"]}).json()
    found = found.get("tasks", found) if isinstance(found, dict) else found
    check("...and the App's task search with the bundle ID finds it, with the check's name as its agent's name",
          [(x.get("id"), x.get("agentName")) for x in found or []] == [(task_id, NAME)], found)
    for _ in range(100):   # the Job starts in the background
        if len(seam.JOBS) > n:
            break
        time.sleep(0.1)
    job = seam.JOBS[-1] if len(seam.JOBS) == n + 1 else {}
    check("its Domino Job starts at once, in the bundle's project, as the service account (its stored token)",
          job.get("credential") == ("bearer", token) and (job.get("body") or {}).get("projectId") == seam.PROJECT["id"],
          (len(seam.JOBS) - n, job.get("credential")))

    def spec_of(job):
        """The Job's spec, as its bootstrapper reads it: claim the session with the Job's credential, then the spec route."""
        tok = requests.post(f"{seam.B}/api/runtime/sessions/{job['sid']}/claim", headers={"authorization": f"Bearer {token}"},
                            json={"runId": f"localjob{len(seam.JOBS)}"}, timeout=30).json().get("token")
        return requests.get(f"{seam.B}/api/runtime/sessions/{job['sid']}/spec", headers={"x-agent-session-token": tok},
                            timeout=30).json()

    spec = spec_of(job) if job else {}
    rules = str(spec.get("operatingRules") or "")
    check("the Job's spec has the instructions at the top of the agent's rules, and the access rows of the reference settings",
          rules.startswith(instructions.strip() + "\n\n## Operating rules") and "Project files: read & write. Project datasets: no "
          "access. Other resources attached to the task: read & write." in rules, rules[:300])
    check("the Job gets the store skill purpose-and-data, with SKILL.md as its text (a store skill: no own skill, no commit)",
          spec.get("skills") == [{"name": "purpose-and-data", "version": store.get("version"), "content": skill}],
          [(s.get("name"), s.get("version"), len(s.get("content") or "")) for s in spec.get("skills") or []])
    perm = ((spec.get("opencodeConfig") or {}).get("permission")) or {}
    check("opencode may call the Domino tools and push, and may not run a Job or a subagent (the Job's permissions)",
          {k: perm.get(k) for k in ("domino_*", "domino_run_job", "domino_git_push", "skill", "task")}
          == {"domino_*": "allow", "domino_run_job": "deny", "domino_git_push": "allow", "skill": "allow", "task": "deny"}, perm)
    check("the Job pushes to the task branch and starts no Job (Git push on, Run a Job off), ends a failure with a report (onError "
          "fail), and has check 2's limits", spec.get("onError") == "fail" and spec.get("tools") == {"push": True, "jobs": False}
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
            "filename": f"docs/validation/purpose-and-data-{BUNDLE['id']}.md", "commit": "0" * 40, "source": "GBP",
            "branch": "agent/AGT-1"}},
        "write_governance_finding": {"bundleId": BUNDLE["id"], "name": f"[{NAME}] Data class Internal for Restricted data in the Intake",
                                     "severity": "S1", "description": "Evidence."},
        "write_policy_result": {"bundleId": BUNDLE["id"], "evidenceId": "ev-1", "content": {"art-verdict": "do not approve"}},
    }
    for name, args in CALLS.items():
        d = gateway.decide(name, args, policy) if policy else {}
        check(f"the gateway allows {name} on the event's bundle, by its own row (named), with no owner check",
              d.get("allow") is True and d.get("row") == "named" and not any(s.get("expect") for s in d.get("steps") or []),
              {k: d.get(k) for k in ("allow", "row", "why")})
    d = gateway.decide("git_push", {"message": "The doc"}, policy) if policy else {}
    check("...and git_push, in the task's project", d.get("allow") is True, {k: d.get(k) for k in ("allow", "row", "why")})
    d = gateway.decide("get_dataset", {"datasetId": "ds-of-the-project"}, policy) if policy else {}
    check("...but no dataset of the project (Project datasets: No access)", d.get("allow") is False
          and "Project datasets is No access" in (d.get("why") or ""), {k: d.get(k) for k in ("allow", "row", "why")})
    listed = {f"domino_{t['name']}" for t in gateway.tool_defs(policy)} | {f"domino_{t}" for t in proxies.RELAY_TOOLS
                                                                            if t != "submit_plan"} if policy else set()
    check("each tool that the skill and the instructions name is one that this task's agent is offered, and run_job is not one",
          named <= listed and "domino_run_job" not in listed, sorted(named - listed))

    # A store skill always gives its newest text: an edit in the store reaches the next task, whatever version the agent names
    newer = skill.rstrip("\n") + "\n\nA rule added in the store.\n"
    r = seam.api("PUT", f"/api/skills/{store.get('id')}", OWNER, json={"content": newer, "note": "A new rule"})
    n = len(seam.JOBS)
    fired = fire(stage_move(), PEOPLE_ANALYST)
    for _ in range(100):
        if len(seam.JOBS) > n:
            break
        time.sleep(0.1)
    spec = spec_of(seam.JOBS[-1]) if r.status_code == 200 and len(seam.JOBS) == n + 1 else {}
    check("a new stage move starts the check again, and its Job gets the store skill's newest text (PUT /api/skills/{id}), though "
          "the agent still names the version that it was made with", [s.get("content") for s in spec.get("skills") or []] == [newer]
          and seam.api("GET", f"/api/agents/{aid}", OWNER).json().get("skills") == body["skills"],
          (r.status_code, fired, [s.get("version") for s in spec.get("skills") or []]))

    fired = [fire(stage_move("Approval"), PEOPLE_ANALYST), fire(stage_move(project=("p-other", "another-project")), PEOPLE_ANALYST)]
    check("a stage move to another stage, or to Validation in another project, starts nothing (the filter)", fired == [[], []], fired)
    domino.get = real_get
finally:
    seam.close()
done()
