"""The agent folder validator (governance/validator-folder/): the App validator of the harness lane (opencode), domino-agent-service
spec #260, Implementation Decision 8, ticket #267. Seen from outside: its files as `domino-agent deploy` uploads them, its checklist
skill as the agent reads it, the templates of its event subscription, and the agent that a local agent service registers from it.

  python tests/check_validator_folder.py                                                    # the files only
  AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_validator_folder.py   # on Linux: everything (README)
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "governance" / "validator-folder"
UPLOADED = ("definition.md", "instructions.md", "skills/app-validation/SKILL.md")   # what deploy uploads of the folder
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
    """Is `rel` (a path in the folder) a file that deploy uploads? definition.md, instructions.md, skills/<name>/<file> and
    subagents/<file>.md (the service's docs/definition-file.md, "The limits and the refusals")."""
    parts = rel.split("/")
    return rel in ("definition.md", "instructions.md") or (len(parts) >= 3 and parts[0] == "skills") \
        or (len(parts) == 2 and parts[0] == "subagents" and rel.endswith(".md"))


# --------------------------------------------------------------------------------------------------------------------- the files
every = {p.relative_to(FOLDER).as_posix(): p.read_text() for p in sorted(FOLDER.rglob("*")) if p.is_file()} if FOLDER.is_dir() else {}
files = {k: v for k, v in every.items() if known(k)}
check("governance/validator-folder/ uploads definition.md, instructions.md and one own skill, app-validation, and nothing else",
      sorted(files) == sorted(UPLOADED), sorted(files))
settings, instructions, skill = (files.get(k, "") for k in UPLOADED)
check("definition.md holds only the settings, between its two --- lines: the instructions are instructions.md",
      settings.startswith("---\n") and settings.rstrip().endswith("\n---") and settings.count("\n---") == 1, settings[-200:])
top = re.match(r"---\n(.*?)\n---\n", skill, re.S)
check("the skill's SKILL.md has YAML on top with its folder's name and a description (else opencode never offers it)",
      bool(top) and re.search(r"^name: app-validation$", top.group(1), re.M) and re.search(r"^description: \S.{20,}$", top.group(1), re.M),
      skill[:300])

# ------------------------------------------------------------------------------------------------------- the checklist (the skill)
EVIDENCE = "Validation (agent folder)"   # the evidence item's name in governance/app-deployment-policy.yaml (#266)
VERDICTS = ("approve", "approve after fixes", "do not approve")
DOC = "docs/validation/agent-folder-<bundleId>.md"   # where the doc goes on the task branch
lines = [ln.lower() for ln in skill.splitlines()]


def rule(name, *words):
    """One line of the skill says the rule: it holds every one of `words` (case aside)."""
    check(f"the skill says: {name}", any(all(w.lower() in ln for w in words) for ln in lines), words)


rule("read the bundle first", "domino_get_bundle", "bundleid")
rule("read the policy with the bundle's ID", "domino_get_policy", "bundleid")
rule("find the evidence item by its exact name, and keep its ID", f'"{EVIDENCE}"', "evidence item", "exact", "id")
rule("find each field by its label: Verdict, Critical vulns, Summary, Doc location", "details.label", '"verdict"', '"critical vulns"',
     '"summary"', '"doc location"')
rule("a radio field takes one of its options' values", "radio", "details.options", "value")
rule("read the App's code and its start script", "app.sh", "code", "read")
rule("the Intake values: no gateway tool reads them, so say so", "intake", "no gateway tool", "could not check")
rule("run the shared scan script in a Domino Job", "domino_run_job", '"python governance/scan.py"')
rule("wait for the Job, again while it still runs", "domino_wait_job", "still", "again")
rule("find the scan summary by its two marker lines", "== scan summary ==", "== end of scan summary ==")
rule("...with more of the log from get_job_logs", "domino_get_job_logs")
rule("the commit that was scanned is the summary's commit line", "commit:", "summary")
rule("sort each hit: a real finding or a false hit", "each hit", "real finding", "false hit")
rule("a false hit has the reason why it is false", "false hit", "reason")
rule("the severity scale is governance/README.md's", "governance/readme.md", "severity", "s0", "s3")
rule("a known vulnerability is S0 when a caller can reach it through the App's code", "known vulnerability", "s0", "reach")
rule("the doc follows the shared template", "governance/validation-doc.md", DOC.lower())
rule("...with every field replaced and every comment deleted", "{{field}}", "<!--")
rule("critical vulns is yes when a real finding is S0", "critical_vulns", "yes", "s0")
rule("the verdict is one of three values", "verdict", *VERDICTS)
rule("the doc says what the validator could not check", "could_not_check", "default branch")
rule("push the doc with git_push, and keep its branch, commit and dryRun", "domino_git_push", "branch", "commit", "dryrun")
rule("attach the doc: a Report from GBP, with the task branch and the push's commit", "domino_write_bundle_attachment", '"report"',
     '"gbp"', "branch", "commit", DOC.lower())
rule("...only when the push is on the remote (dryRun false)", "only when", "dryrun", "false")
rule("a dry-run push: attach nothing, and say so under what the validator could not check", "dryrun", "true", "attach nothing",
     "could not check")
rule("file each real finding, its name starting with [folder]", "domino_write_governance_finding", '"[folder] ', "severity")
rule("file no false hit", "no false hit")
rule("fill only its own evidence item, by the IDs from get_policy", "domino_write_policy_result", "only", f'"{EVIDENCE}"', "evidenceid")
rule("a failed or denied call: go on with the other steps, and name it under what the validator could not check", "fail", "denied",
     "go on", "could not check")
rule("the result goes to report_result, once, last", "domino_report_result", "once", "last")

order = ["domino_get_bundle", "domino_get_policy", "domino_run_job", "domino_wait_job", "domino_git_push",
         "domino_write_bundle_attachment", "domino_write_governance_finding", "domino_write_policy_result", "domino_report_result"]
at = [skill.find(t) for t in order]
check("the checklist's tools come in the spec's order: bundle and policy, scan, push, attachment, findings, evidence, result",
      all(i >= 0 for i in at) and at == sorted(at), dict(zip(order, at)))
steps = [int(n) for n in re.findall(r"^## (\d+)\. ", skill, re.M)]
check("the checklist is numbered steps, in order", len(steps) >= 8 and steps == list(range(1, len(steps) + 1)), steps)
check("each step ends with its completion criterion (a 'Done when' line)",
      steps and all("Done when:" in part for part in re.split(r"^## \d+\. ", skill, flags=re.M)[1:]), steps)
result = [ln.strip() for ln in skill.split("## ")[-1].splitlines()]
want = [f"Verdict: {' | '.join(VERDICTS)}", "Critical vulns: yes | no", "Doc location: "]
got = [next((ln for ln in result if ln.startswith(w.split(":")[0] + ":")), None) for w in want]
check("the last step gives the result's three lines, in order, with the scripted check's labels and the exact Verdict values",
      all(got) and got[0] == want[0] and got[1] == want[1] and [result.index(g) for g in got] == sorted(result.index(g) for g in got),
      got)

# ------------------------------------------------------------------------------------------------------------- the instructions
ilines = [ln.lower() for ln in instructions.splitlines()]


def irule(name, *words):
    """One line of instructions.md says the rule: it holds every one of `words` (case aside)."""
    check(f"the instructions say: {name}", any(all(w.lower() in ln for w in words) for ln in ilines), words)


irule("load the skill app-validation first, and do its checklist in order", "first", "skill app-validation", "in order")
irule("fill only its own evidence item", "only", "own evidence item", f'"{EVIDENCE}"')
irule("file only the real findings, each name starting with [folder]", "only the real findings", '"[folder] "')
irule("a false hit goes in the doc with its reason", "false hit", "doc", "reason")
irule("say what it could not check, in the doc and in the result", "could not check", "doc", "result")
irule("nobody answers an event task: no question and no access request", "nobody answers", "domino_ask_user", "domino_request_access")
irule("the checklist's writes are the task's work: no asking first", "push", "attachment", "findings", "evidence", "without asking")
irule("end with report_result, once, last", "domino_report_result", "once", "last")

# --------------------------------------------------------------------------------------------------------------- the tool names
# opencode names a tool of the relay's MCP server `domino` as domino_<name> (the service's agent_runtime/gateway.py)
NAMES = {"domino_get_bundle", "domino_get_policy", "domino_run_job", "domino_wait_job", "domino_get_job_logs", "domino_git_push",
         "domino_write_bundle_attachment", "domino_write_governance_finding", "domino_write_policy_result", "domino_report_result",
         "domino_ask_user", "domino_request_access"}
named = set(re.findall(r"\bdomino_[a-z_]+", skill + instructions))
check("the skill and the instructions name the checklist's Domino tools, and no other", named == NAMES, sorted(named ^ NAMES))
bare = sorted(set(re.findall(r"(?<![a-z_`])(?:get_bundle|get_policy|run_job|wait_job|git_push|write_[a-z_]+|report_result)\(",
                             skill + instructions)))
check("they call no tool by its plain name (a framework agent's name): a harness agent has only the domino_ names", not bare, bare)

# ------------------------------------------------------------------------------------------------- the event subscription's file
# The body of `POST /api/agents/{id}/triggers` (the service's agent_write.create_trigger), for the live script (#270). Its one
# placeholder is the demo project's ID. Deploy doesn't upload it: an agent folder holds no trigger.
SUB_FILE = FOLDER / "subscription.json"
PROJECT_ID = "__DEMO_PROJECT_ID__"
# The fields of a governance.bundle.stage_changed payload, as the service's audit poller builds it (agent_service/audit_source.py)
PAYLOAD = ("source", "triggeredBy", "occurredAt", "auditTraceId", "bundle.id", "bundle.name", "fromStage", "toStage", "policy.id",
           "policy.name", "project.id", "project.name")
try:
    sub = json.loads(text(SUB_FILE))
except ValueError as e:
    sub = {"error": str(e)}
sub = sub if isinstance(sub, dict) else {}
event = sub.get("event") or {}
check("governance/validator-folder/subscription.json is an event subscription to governance.bundle.stage_changed, on",
      sub.get("type") == "event" and event.get("eventType") == "governance.bundle.stage_changed" and sub.get("enabled") is True
      and sub.get("name"), {k: sub.get(k) for k in ("type", "name", "enabled", "event", "error")})
policy_yaml = text(ROOT / "governance" / "app-deployment-policy.yaml")
check("its filter: the bundle moved to the policy's stage named Validation (exact: the filter compares strings), in the demo project",
      event.get("filter") == [{"field": "toStage", "op": "equals", "value": "Validation"},
                              {"field": "project.id", "op": "equals", "value": PROJECT_ID}]
      and re.search(r"^  - name: Validation$", policy_yaml, re.M), event.get("filter"))
title, instruction = sub.get("titleTemplate") or "", sub.get("instructionTemplate") or ""
check("its title template names the bundle ID (the scripted check's task search matches the title and the key only)",
      "{{bundle.id}}" in title and len(title) <= 90, title)
check("its instruction template names the bundle ID, the evidence item to fill, and the skill",
      "{{bundle.id}}" in instruction and f'"{EVIDENCE}"' in instruction and "app-validation" in instruction, instruction)
fields = set(re.findall(r"\{\{([^}]+)\}\}", title + instruction))
check("each placeholder of the two templates is a field of the stage-change payload (a field that isn't stays as {{...}})",
      fields and fields <= set(PAYLOAD), sorted(fields - set(PAYLOAD)))
check("it pins no resource and writes nothing back: the event names the bundle and the project",
      sub.get("defaultResources") == [] and sub.get("writeBack") == [], {k: sub.get(k) for k in ("defaultResources", "writeBack")})

# The AML repo is public: no Domino host, no ID of a Domino object, no token in the folder (the live script fills the placeholder)
leaks = sorted({f"{rel}: {m.group(0)}" for rel, body in every.items()
                for m in re.finditer(r"[0-9a-f]{24}|agt_[0-9a-z]{6,}|[\w.-]+\.domino\.tech|apps-internal/[0-9a-f]+|eyJ[\w-]{20,}", body)})
check("no file of the folder has a Domino host, the ID of a Domino object or a token", not leaks, leaks)
dashed = sorted(rel for rel, body in every.items() if "—" in body)
check("no file of the folder has an em dash", not dashed, dashed)

service = os.environ.get("AGENT_SERVICE_REPO", "").strip()
if not service:
    done("AGENT_SERVICE_REPO is not set, so the tool names, the deploy and the event's task weren't checked against the service. Set "
         "it to a domino-agent-service checkout (README, \"The agent folder validator\")")
service = Path(service).expanduser().resolve()
if not (service / "agent_runtime" / "gateway.py").is_file() or not (service / "agent_runtime" / "proxies.py").is_file():
    check(f"AGENT_SERVICE_REPO ({service}) is a domino-agent-service checkout (agent_runtime/gateway.py and proxies.py)", False)
    done()
sys.path.insert(0, str(service))
from agent_runtime import gateway, proxies  # noqa: E402  (stdlib only, so any OS)

offered = {f"domino_{n}" for n in gateway.TOOLS} | {f"domino_{n}" for n in proxies.RELAY_TOOLS}
check("each tool that they name is a gateway tool or a relay tool of this service, as opencode names it (domino_<name>)",
      named and named <= offered, sorted(named - offered))

done()
