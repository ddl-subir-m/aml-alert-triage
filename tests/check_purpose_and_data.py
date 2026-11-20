"""Check 1, "Purpose and data" (governance/check-purpose-and-data/): the wizard agent of the App validation demo, domino-agent-service
spec #388, Implementation Decision 8, ticket #395. A person makes the agent once in the App's wizard. The folder is its reference copy
in git: the store skill's text, the instructions, the settings as the wizard saves them, the event subscription, a helper that fills
and compares them, and a README with the wizard steps. Seen from outside, as check 2's check sees its agent folder.

With no service, it checks the files: the store skill's rules and the order of its tools, the instructions' rules, the reference
settings (each value of decision 8), the subscription's file (its filter and its two templates, which name the bundle ID), the
compare helper, the README's wizard steps (each setting of the reference settings, with the wizard's own label), and no Domino host,
ID or user name (the repo is public). The names, the evidence item, the field labels, the verdicts and the severities come from
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
check2 = ROOT / "governance" / "check-architecture-and-access" / "definition.md"
if check2.is_file():
    got2 = {k: int(m.group(1)) if (m := re.search(rf"^  {k}: (\d+)", text(check2), re.M)) else None
            for k in ("minutes", "turns", "wait-minutes")}
    check("...the same limits as check 2's definition.md", got2 == {"minutes": 45, "turns": 120, "wait-minutes": 0}, got2)
else:
    print("SKIP: check 2's definition.md is not on this branch, so the limits were compared with #260's folder validator only",
          flush=True)
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

done()
