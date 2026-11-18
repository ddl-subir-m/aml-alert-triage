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

done()
