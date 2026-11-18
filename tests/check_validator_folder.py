"""The agent folder validator (governance/validator-folder/): the App validator of the harness lane (opencode), domino-agent-service
spec #260, Implementation Decision 8, ticket #267. Seen from outside: its files as `domino-agent deploy` uploads them, its checklist
skill as the agent reads it, the templates of its event subscription, and the agent that a local agent service registers from it.

With no service, it checks the folder's files: the ones that deploy uploads, the checklist's rules and the order of its tools, the
instructions' rules, the tool names (as a harness agent sees them: domino_<name>), the subscription's file (its filter and its two
templates, which name the bundle ID), no Domino host or ID (the repo is public), and the READMEs.

With the service (AGENT_SERVICE_REPO, the path of a domino-agent-service checkout), it checks each tool name against the service's
gateway and relay (agent_runtime/gateway.py and proxies.py: stdlib, any OS). On Linux, it also starts that service over real HTTP with
a fake Domino (the service's seam helper, tests/agent_folder_seam.py), with the folder committed in a temporary clone:
  - `domino-agent deploy --dry-run` passes the service's folder rules; `deploy` registers the agent, which can't run yet.
  - The owner makes the subscription from subscription.json. A stage move (the audit poller's payload) starts no task before the
    service account's token, nor for an analyst who may not use the agent; then one task, as the service account, and its Job.
  - The Job's spec (the skill, the access rows, the permissions, the limits) and the gateway's decisions for that task on the event's
    bundle: the attachment, the findings and the evidence are allowed by the row "Other resources attached to the task".
With AGENT_SERVICE_REPO unset, or not on Linux, those parts print a SKIP line. No Domino host: the live run is domino-agent-service
#270.

  python tests/check_validator_folder.py                                                   # the files only
  AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_validator_folder.py   # on Linux: everything (its README)
"""
import json
import os
import re
import sys
import time
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
dashed = sorted(rel for rel, body in [*every.items(), ("tests/check_validator_folder.py", text(Path(__file__)))] if chr(0x2014) in body)
check("no file of the folder, and not this check, has an em dash", not dashed, dashed)

# ---------------------------------------------------------------------------------------------------------------- the READMEs
# The folder holds no user names and no trigger: its README says what the owner adds before the agent can run.
rlines = [ln.lower() for ln in every.get("README.md", "").splitlines()]


def rrule(name, *words):
    """One line of the folder's README.md says it: it holds every one of `words` (case aside)."""
    check(f"the folder's README says: {name}", any(all(w.lower() in ln for w in words) for ln in rlines), words)


rrule("deploy it with a dry run first", "domino-agent deploy --dry-run governance/validator-folder")
rrule("the owner adds the service account and its token, else it can't run yet", "service account", "token", "can't run yet")
rrule("...and stores a new token before the old one expires", "token", "expires")
rrule("the service account's rights: Contributor on the demo project, the model, the bundle", "service account", "contributor",
      "llm gateway", "bundle")
rrule("the service account's Git credential, with write access to the repo (the push)", "git credential", "write access", "push")
rrule("the access rows, with attached Read & write for the event's bundle", "other resources attached to the task", "read & write",
      "bundle")
rrule("share it with the analyst who moves the stage", "share", "analyst", "moves the stage")
rrule("...and with the approver as an owner or an editor", "approver", "owner or an editor")
rrule("make the subscription from subscription.json, with the demo project's ID", "subscription.json", PROJECT_ID,
      "post /api/agents/{id}/triggers")
rrule("the platform App polls the audit trail", "smoke_audit_poll_seconds")
rrule("...and pushes for real, else the push is a dry run and the doc isn't attached", "smoke_push_dry_run=0", "dry run", "attach")
rrule("the demo project's default branch has the shared parts", "default branch", "governance/scan.py",
      "governance/validation-doc.md")
rrule("how to run this check", "python tests/check_validator_folder.py")
readme = text(ROOT / "README.md")
check("the repo's README has a section for this validator that links to the folder's README",
      "\n## The agent folder validator\n" in readme and "governance/validator-folder/README.md" in readme)

service = os.environ.get("AGENT_SERVICE_REPO", "").strip()
if not service:
    done("AGENT_SERVICE_REPO is not set, so the tool names, the deploy and the event's task weren't checked against the service. Set "
         "it to a domino-agent-service checkout (governance/validator-folder/README.md, \"The check\")")
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
         "with Docker, in the image of the service's checks (governance/validator-folder/README.md, \"The check\")")
sys.path.insert(0, str(service / "tests"))
import agent_folder_seam as seam  # noqa: E402  (the service's seam helper, from AGENT_SERVICE_REPO)

seam.start()
OWNER, ANALYST, APPROVER, SA = "olivia", "rita", "bob", "app-validator-sa"   # people the seam's fake Domino knows, and the account
TITLE, PATH = "App validator (agent folder)", "governance/validator-folder"
REMOTE = "https://github.com/ddl-subir-m/aml-alert-triage.git"
repo = seam.Repo(every, path=PATH, remote=REMOTE)   # the whole folder, as git has it: deploy uploads only the known paths


def registered():
    """The agent that the folder's `name` registered, as its owner sees it, or None."""
    agents = seam.api("GET", "/api/agents", OWNER).json()
    return next((a for a in agents if (a.get("registration") or {}).get("name") == "app-validator-folder"), None)


ran = seam.command("deploy", "--dry-run", PATH, cwd=repo.root, person=OWNER)
check("deploy --dry-run passes the service's folder rules: it would create the agent, and registers nothing",
      ran.code == 0 and f"Dry run: would create {TITLE}" in ran.out and "Dry run: nothing was registered." in ran.out
      and registered() is None, ran)
ran = seam.command("deploy", PATH, cwd=repo.root, person=OWNER)
check("deploy registers it, and says that it can't run yet: it acts as a service account, and none is chosen",
      ran.code == 0 and ran.out.startswith(f"Created {TITLE} (agt_") and "Can't run yet" in ran.out and "service account" in ran.out, ran)
a = registered() or {}
aid = a.get("id")
check("the agent is a harness agent named App validator (agent folder), owned by the person who deployed it",
      a.get("lane") == "harness" and a.get("name") == TITLE and (a.get("owner") or {}).get("userName") == OWNER,
      (a.get("lane"), a.get("name"), a.get("owner")))
rec = a.get("registration") or {}
check("its Registration names the AML repo, the folder's path, the commit and a clean folder",
      rec.get("repo") == REMOTE and rec.get("path") == PATH and rec.get("commit") == repo.head and rec.get("clean") is True, rec)
check("its identity is a service account (the owner chooses which one, and adds its token)",
      (a.get("identity") or {}).get("mode") == "service_account", a.get("identity"))
g = a.get("guardrails") or {}
check("it runs Jobs and pushes its task branch, with no subagent (Run a Job: on, Git push: on)",
      {k: (g.get("tools") or {}).get(k) for k in ("jobs", "push", "subagents")} == {"jobs": True, "push": True, "subagents": False},
      g.get("tools"))
check("its Resource access: Project files Read & write, Project datasets No access, attached Read & write, not attached No access",
      {k: (g.get("access") or {}).get(k) for k in ("project", "data", "named", "other")}
      == {"project": "write", "data": "none", "named": "write", "other": "none"}, g.get("access"))
check("a failure ends the task with a report (on-error: fail): nobody unblocks an event task", a.get("onError") == "fail", a.get("onError"))
check("its limits: 45 minutes, 120 turns, and no wait for an answer",
      {k: (a.get("execution") or {}).get(k) for k in ("maxRuntimeMin", "maxTurns", "idleWaitMin")}
      == {"maxRuntimeMin": 45, "maxTurns": 120, "idleWaitMin": 0}, a.get("execution"))
check("its model is the LLM Gateway alias sonnet", (a.get("model") or {}).get("models") == ["sonnet"], a.get("model"))
check("its system prompt is instructions.md", a.get("systemPrompt") == instructions.strip(), (a.get("systemPrompt") or "")[:200])
own = a.get("ownSkills") or []
check("its own skill is app-validation, with its description and one file, SKILL.md (the API shows no text: the Job's spec has it)",
      [(s.get("name"), s.get("files")) for s in own] == [("app-validation", ["SKILL.md"])]
      and own[0].get("description") and own[0]["description"] in skill, own)

# ------------------------------------------------------------------------------------- the subscription and the event's task
# The owner makes the subscription from subscription.json, as the live script does, with the demo project's ID: here the seam's
# Git-based project. A stage move reaches it as the audit poller publishes it: Domino's audit row (AuditEvent, as the service's
# tests/check_phase3.py audit_event() copies a real stage move), made into the payload by the poller's own audit_source.to_payload,
# then published through the subscription's test route, which runs the same fan-out (service.emit_event) as the person who calls it.
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


body = json.loads(text(SUB_FILE).replace(PROJECT_ID, seam.PROJECT["id"]))
r = seam.api("POST", f"/api/agents/{aid}/triggers", OWNER, json=body)
trigger = r.json() if r.status_code == 200 else {}
check("the owner makes the subscription from subscription.json, with the demo project's ID in its one placeholder",
      r.status_code == 200 and trigger.get("type") == "event" and trigger.get("enabled") is True, (r.status_code, r.text[:300]))


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
check("the task's title names the bundle ID (so the scripted check finds it), from the title template",
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
check("the Job gets the own skill app-validation with the checklist's text, at the commit that was deployed",
      skills == [("app-validation", True, skill)] and (spec.get("skills") or [{}])[0].get("commit") == repo.head, [s[:2] for s in skills])
perm = ((spec.get("opencodeConfig") or {}).get("permission")) or {}
check("opencode may call the Domino tools, run a Job and push (the Job's permissions)",
      {k: perm.get(k) for k in ("domino_*", "domino_run_job", "domino_git_push", "skill")}
      == {"domino_*": "allow", "domino_run_job": "allow", "domino_git_push": "allow", "skill": "allow"}, perm)
check("the Job ends a failure with a report (onError fail), pushes to the task branch, and has the folder's limits",
      spec.get("onError") == "fail" and spec.get("tools") == {"push": True, "jobs": True}
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
        "filename": f"docs/validation/agent-folder-{BUNDLE['id']}.md", "commit": "0" * 40, "source": "GBP", "branch": "agent/AGT-1"}},
    "write_governance_finding": {"bundleId": BUNDLE["id"], "name": "[folder] A finding", "severity": "S1", "description": "Evidence."},
    "write_policy_result": {"bundleId": BUNDLE["id"], "evidenceId": "ev-1", "content": {"art-verdict": "approve after fixes"}},
}
for name, args in CALLS.items():
    d = gateway.decide(name, args, policy) if policy else {}
    check(f"the gateway allows {name} on the event's bundle, by its own row (named), with no owner check",
          d.get("allow") is True and d.get("row") == "named" and not any(s.get("expect") for s in d.get("steps") or []),
          {k: d.get(k) for k in ("allow", "row", "why")})
for name, args in (("run_job", {"command": "python governance/scan.py"}), ("git_push", {"message": "The doc"})):
    d = gateway.decide(name, args, policy) if policy else {}
    check(f"...and {name}, in the task's project", d.get("allow") is True, {k: d.get(k) for k in ("allow", "row", "why")})
d = gateway.decide("get_dataset", {"datasetId": "ds-of-the-project"}, policy) if policy else {}
check("...but no dataset of the project (Project datasets: No access)", d.get("allow") is False
      and "Project datasets is No access" in (d.get("why") or ""), {k: d.get(k) for k in ("allow", "row", "why")})
listed = {f"domino_{t['name']}" for t in gateway.tool_defs(policy)} | {f"domino_{t}" for t in proxies.RELAY_TOOLS
                                                                        if t != "submit_plan"} if policy else set()
check("each tool that the skill and the instructions name is one that this task's agent is offered", named <= listed,
      sorted(named - listed))

fired = [fire(stage_move("Approval"), ANALYST), fire(stage_move(project=("6a0000000000000000000e40", "another-project")), ANALYST)]
check("a stage move to another stage, or to Validation in another project, starts nothing (the filter)", fired == [[], []], fired)
domino.get = real_get

seam.close()
done()
