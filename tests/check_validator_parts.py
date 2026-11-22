"""The shared parts of the three checks of the App validation demo (domino-agent-service spec #388, Implementation Decisions 5 to 7),
seen from outside: the scan script as a Domino Job runs it, the doc template (one shared top part and one middle part for each
check), the three checks and a failed scan (governance/README.md), and the rules file governance/rules.md (spec #499, ticket #508: the
four evidence fields and their values, the verdict rule, could not check, the doc location, the severity scale with its examples for
each check, the finding names, the trim of the template and the result). The rules file agrees with governance/checks.json, and no
other Markdown file of the repo copies one of its rules. The file name is the one of spec #260.

The scan script runs with no network: a bare venv (no pip-audit, no bandit, no pip) and fake scanners on PYTHONPATH that answer with
the real tools' output, saved in tests/fixtures/scan/ (pip-audit 2.10.1 and bandit 1.9.4 on case_server: `clean` is main,
`vulnerable` is pip-audit's answer for the demo branch's pin, pyyaml==5.3.1, and `gaps` adds a file that bandit can't parse and a
package that isn't on PyPI). The fakes copy the real tools: their `--version` line,
their JSON file at -o, their messages on stderr and their exit codes (pip-audit: 0, 1 with hits, 1 and no JSON when it fails; bandit:
0, 1 with hits). A fake pip "installs" the fake scanners, as a Job's pip installs the real ones.

It also checks that the two validators of spec #260 left the branch (spec #388, ticket #390): their folders and checks are not on it,
and no file names one of them, but with the tag app-validation-two-ways that keeps them.

With AGENT_SERVICE_REPO (the path of a domino-agent-service checkout), it also checks the severity scale against the gateway's
write_governance_finding (agent_runtime/gateway.py, stdlib only, so any OS). Without it, that part prints a SKIP line.

  python tests/check_validator_parts.py
  AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_validator_parts.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "governance" / "scan.py"
FIXTURES = ROOT / "tests" / "fixtures" / "scan"
START, END = "== scan summary ==", "== end of scan summary =="
TAG = "app-validation-two-ways"   # the tag that keeps the two validators of spec #260 (ticket #390)
WAIT_JOB_TAIL = 8000   # the service's wait_job shows the last 8,000 characters of the Job's log (agent_runtime/run.py)
failed = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{str(detail)[:600]}]" if detail and not ok else ""), flush=True)
    if not ok:
        failed.append(name)


# ----------------------------------------------------------------------------------------------------------------- the fake tools
# Each fake adds its arguments to $FAKE_SCAN_CALLS/<tool>.jsonl, so a check can see what the scan asked of it.
FAKE_PIP_AUDIT = '''import json, os, sys
args = sys.argv[1:]
calls = os.environ["FAKE_SCAN_CALLS"]
with open(os.path.join(calls, "pip-audit.jsonl"), "a") as f:
    f.write(json.dumps(args) + "\\n")
if "--version" in args:
    print("pip-audit 2.10.1")   # the real line
    sys.exit(0)
if os.environ.get("FAKE_SCAN_FAIL") == "pip-audit":   # the real pip-audit 2.10.1 when a requirement can't be resolved: no JSON
    print("ERROR:pip_audit._virtual_env:internal pip failure: ERROR: Could not find a version that satisfies the requirement "
          "no-such-package==1.0 (from versions: none)", file=sys.stderr)
    print("ERROR: No matching distribution found for no-such-package==1.0", file=sys.stderr)
    print("ERROR:pip_audit._cli:Failed to install packages: ['python3', '-m', 'pip', 'install', '--dry-run']", file=sys.stderr)
    sys.exit(1)
src = os.path.join(os.environ["FAKE_SCAN_FIXTURES"], "pip-audit.json")
out = args[args.index("-o") + 1] if "-o" in args else args[args.index("--output") + 1]
shutil = __import__("shutil")
shutil.copyfile(src, out)
n = sum(len(d.get("vulns") or []) for d in json.load(open(src))["dependencies"])
if n:
    print(f"Found {n} known vulnerabilities in 1 package", file=sys.stderr)
    sys.exit(1)
print("No known vulnerabilities found", file=sys.stderr)
'''

FAKE_BANDIT = '''import json, os, shutil, sys
args = sys.argv[1:]
calls = os.environ["FAKE_SCAN_CALLS"]
with open(os.path.join(calls, "bandit.jsonl"), "a") as f:
    f.write(json.dumps(args) + "\\n")
if "--version" in args:
    print("__main__.py 1.9.4")   # the real lines of `python -m bandit --version`
    print("  python version = 3.12.12")
    sys.exit(0)
src = os.path.join(os.environ["FAKE_SCAN_FIXTURES"], "bandit.json")
out = args[args.index("-o") + 1]
for line in ("[main]\\tINFO\\tprofile include tests: None", "[main]\\tINFO\\tprofile exclude tests: None",
             f"[json]\\tINFO\\tJSON output written to file: {out}"):
    print(line, file=sys.stderr)
shutil.copyfile(src, out)
sys.exit(1 if json.load(open(src))["results"] else 0)
'''

# A fake `python -m pip install ...`: it records the call and "installs" the fake scanners it is asked for into $FAKE_SCAN_SITE.
FAKE_PIP = '''import json, os, shutil, sys
args = sys.argv[1:]
with open(os.path.join(os.environ["FAKE_SCAN_CALLS"], "pip.jsonl"), "a") as f:
    f.write(json.dumps(args) + "\\n")
if os.environ.get("FAKE_SCAN_FAIL") == "pip":   # the real pip when PyPI has no such package (or can't be reached)
    print("ERROR: Could not find a version that satisfies the requirement pip-audit (from versions: none)", file=sys.stderr)
    print("ERROR: No matching distribution found for pip-audit", file=sys.stderr)
    sys.exit(1)
for spec in args:
    for name, module in (("pip-audit", "pip_audit"), ("bandit", "bandit")):
        if spec.startswith(name):
            shutil.copytree(os.path.join(os.environ["FAKE_SCAN_STORE"], module), os.path.join(os.environ["FAKE_SCAN_SITE"], module))
print("Successfully installed (fake)")
'''


def package(where, module, main):
    (where / module).mkdir(parents=True)
    (where / module / "__init__.py").write_text("")
    (where / module / "__main__.py").write_text(main)


tmp = Path(tempfile.mkdtemp(prefix="check-validator-parts-"))
subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp / "venv")], check=True)
PY = str(tmp / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))   # a bare Python: no pip, no scanners
store = tmp / "store"   # the fake scanners, before pip "installs" them
package(store, "pip_audit", FAKE_PIP_AUDIT)
package(store, "bandit", FAKE_BANDIT)
package(tmp / "pipdir", "pip", FAKE_PIP)


def scan(fixture, *, installed=True, fail=None):
    """One run of the scan script as a Job runs it (python governance/scan.py, from the project's root), with fake scanners.
    -> (exit code, stdout, stderr, calls {tool: [argv of each call]}, out folder)"""
    run = Path(tempfile.mkdtemp(dir=tmp))
    site, calls, out = run / "site", run / "calls", run / "out"
    site.mkdir()
    calls.mkdir()
    if installed:
        for module in ("pip_audit", "bandit"):
            shutil.copytree(store / module, site / module)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "DOMINO_"))}
    env.update(PYTHONPATH=os.pathsep.join([str(tmp / "pipdir"), str(site)]), FAKE_SCAN_FIXTURES=str(FIXTURES / fixture),
               FAKE_SCAN_CALLS=str(calls), FAKE_SCAN_SITE=str(site), FAKE_SCAN_STORE=str(store))
    if fail:
        env["FAKE_SCAN_FAIL"] = fail
    p = subprocess.run([PY, str(SCAN), "--out", str(out)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    seen = {f.stem: [json.loads(ln) for ln in f.read_text().splitlines()] for f in calls.glob("*.jsonl")}
    return p.returncode, p.stdout, p.stderr, seen, out


def summary(stdout):
    """The summary block: from its first line to its last, or "" when stdout has none."""
    if START not in stdout:
        return ""
    return stdout[stdout.rindex(START):]


# ------------------------------------------------------------------------------------------------------------ the scan: main (clean)
code, out, err, calls, folder = scan("clean")
block = summary(out)
check("the scan exits 0 when both tools ran", code == 0, f"exit {code}; stderr: {err[-400:]}")
check("the scan writes nothing to stderr (a Job's stderr comes after its stdout in what wait_job shows)", err == "", err[-400:])
check("the summary is the end of the scan's output", out.rstrip().endswith(END), out[-400:])
check("the summary names pip-audit with its version, and says it found no known vulnerabilities",
      "pip-audit 2.10.1" in block and "no known vulnerabilities" in block, block)
check("the summary names bandit with its version", "bandit 1.9.4" in block, block)
check("the summary names each bandit hit with its test ID and file:line",
      "B104" in block and "case_server/server.py:159" in block and "B608" in block and "case_server/store.py:215" in block, block)
pa, bd = (([c for c in calls.get(tool, []) if "--version" not in c] or [[]])[-1] for tool in ("pip-audit", "bandit"))
check("pip-audit audits the case server's requirements, in JSON",
      "-r" in pa and pa[pa.index("-r") + 1] == "case_server/requirements.txt" and "json" in pa, pa)
check("bandit scans the case server folder at every severity, in JSON",
      "-r" in bd and bd[bd.index("-r") + 1] == "case_server" and "json" in bd and not any(a.startswith("-l") for a in bd), bd)
reports = {name: (folder / name).read_text() if (folder / name).is_file() else "" for name in ("pip-audit.json", "bandit.json")}
check("each tool's JSON is in the output folder, as the tool wrote it",
      reports["pip-audit.json"] == (FIXTURES / "clean" / "pip-audit.json").read_text()
      and reports["bandit.json"] == (FIXTURES / "clean" / "bandit.json").read_text(), {k: len(v) for k, v in reports.items()})
check("the summary says where the JSON is", str(folder / "pip-audit.json") in block and str(folder / "bandit.json") in block, block)
commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
check("the summary names the commit that it scanned", commit and f"commit: {commit}" in block, block)
check(f"the summary fits well in what wait_job shows (under half of its {WAIT_JOB_TAIL} characters)",
      0 < len(block) < WAIT_JOB_TAIL // 2, len(block))

# ------------------------------------------------------------------------------------------- the scan: the demo branch's pyyaml pin
code, out, err, calls, folder = scan("vulnerable")
block = summary(out)
check("with a known vulnerability, the scan still exits 0 (both tools ran) and writes nothing to stderr", code == 0 and err == "",
      f"exit {code}; stderr: {err[-400:]}")
check("the summary counts the known vulnerability once (pip-audit lists PYSEC-2021-142 twice)",
      "pip-audit 2.10.1 on case_server/requirements.txt: 1 known vulnerability in 1 of 30 packages" in block, block)
vuln = [ln for ln in block.splitlines() if "PYSEC-2021-142" in ln]
check("the summary names PYSEC-2021-142 for pyyaml 5.3.1 on one line, with its aliases, its fix version and what it is",
      len(vuln) == 1 and all(w in vuln[0] for w in ("pyyaml 5.3.1", "CVE-2020-14343", "GHSA-8q59-q68h-6hv4", "fixed in 5.4",
                                                      "full_load")), vuln or block)

# ------------------------------------------------------------- the scan: a file bandit can't parse, a package pip-audit can't audit
# The `gaps` fixture is the real tools' JSON for case_server plus a Python 2 file (bandit's `errors`) and a local package that isn't on
# PyPI (pip-audit's dependency with `skip_reason` and no version). Both tools ran, but neither checked everything.
code, out, err, calls, folder = scan("gaps")
block = summary(out)
check("with a file bandit can't parse and a package pip-audit can't audit, both tools still ran: exit 0, nothing on stderr",
      code == 0 and err == "" and summary(out).rstrip().splitlines()[-2:-1] == ["result: both tools ran"], f"exit {code}; {err[-300:]}")
check("pip-audit counts only the packages it audited, and the summary names each one it did not audit, with pip-audit's reason",
      "pip-audit 2.10.1 on case_server/requirements.txt: no known vulnerabilities in 29 packages, and 1 package not audited" in block
      and "- not audited: aml-local-helper: Dependency not found on PyPI and could not be audited: aml-local-helper (0.1.0)" in block,
      block)
check("bandit's errors are not a clean file: the summary names each file bandit could not scan, with bandit's reason",
      "bandit 1.9.4 on case_server (all severities): 2 hits, and 1 file not scanned" in block
      and "- not scanned: case_server/legacy_export.py: syntax error while parsing AST from file" in block, block)

# ------------------------------------------------------------------------------------- the scan: pip-audit can't resolve the requirements
code, out, err, calls, folder = scan("clean", fail="pip-audit")
block = summary(out)
check("when a tool can't run, the scan exits 1 and still writes nothing to stderr", code == 1 and err == "",
      f"exit {code}; stderr: {err[-400:]}")
check("the summary is still the end of the output", out.rstrip().endswith(END), out[-400:])
line = next((ln for ln in block.splitlines() if ln.startswith("pip-audit")), "")
check("the summary says that pip-audit could not run, with its exit code and its first error",
      "could not run (exit 1)" in line and "Could not find a version that satisfies the requirement" in line
      and "no known vulnerabilities" not in block, block)
check("bandit's hits are still in the summary", "B104" in block and "B608" in block, block)
check("the summary's last line before its end says which tool could not run",
      block.rstrip().splitlines()[-2:-1] == ["result: pip-audit could not run (its messages: pip-audit.log)"], block)
code, out, err, calls, folder = scan("clean")
check("when both tools ran, the summary's last line before its end says so",
      summary(out).rstrip().splitlines()[-2:-1] == ["result: both tools ran"], summary(out))
check("when the Environment has both tools, the scan installs nothing", "pip" not in calls, calls.get("pip"))

# ------------------------------------------------------------------------------- the scan: an Environment with no pip-audit and no bandit
code, out, err, calls, folder = scan("clean", installed=False)
block = summary(out)
pip = (calls.get("pip") or [[]])[0]
check("the scan installs both tools with pip in one call (a Domino Job can reach PyPI)",
      len(calls.get("pip") or []) == 1 and pip[:1] == ["install"] and any(a.startswith("pip-audit") for a in pip)
      and any(a.startswith("bandit") for a in pip), calls.get("pip"))
check("after the install, both tools ran: exit 0, nothing on stderr, their hits in the summary",
      code == 0 and err == "" and "pip-audit 2.10.1" in block and "B104" in block, f"exit {code}; {err[-300:]}; {block}")
check("the scan says what it installed, before the summary", "installing pip-audit and bandit" in out.split(START)[0], out[:600])
code, out, err, calls, folder = scan("clean", installed=False, fail="pip")
block = summary(out)
check("when the install fails, the scan exits 1, writes nothing to stderr, and the summary still ends the output",
      code == 1 and err == "" and out.rstrip().endswith(END), f"exit {code}; {err[-300:]}; {out[-300:]}")
check("the summary says that the install failed, with pip's first error",
      "install: pip could not install pip-audit and bandit (exit 1): ERROR: Could not find a version that satisfies the requirement "
      "pip-audit" in block, block)

shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------------------------------------------- the shared rules: the checks
# Spec #388, Implementation Decisions 5 to 7: three checks, each one built its own way, each one owns one part. The names are the
# ones of the spec. governance/README.md has the three checks and the scan. Each rule that the three checks share is in
# governance/rules.md, one time (spec #499, ticket #508): the cases of the rules read it, the cases below make sure that it agrees
# with governance/checks.json, and that no other file copies a rule.
HUB = ROOT / "governance" / "README.md"
hub = HUB.read_text() if HUB.is_file() else ""
RULES = ROOT / "governance" / "rules.md"
rules = RULES.read_text() if RULES.is_file() else ""
CHECKS = ["Purpose and data", "Architecture and access", "Vulnerability scan"]


def section(text, heading):
    """The text of the section '## <heading>' of a Markdown page, to the next '## ' heading ("" when there is none)."""
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def table(text):
    """The rows of the first Markdown table of a text, as lists of cells, with no header row and no rule row."""
    lines = [ln for ln in text.splitlines() if ln.startswith("|")]
    return [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines[2:]]


def one_line(text):
    return " ".join(text.split())


checks = {r[0]: r for r in table(section(hub, "The three checks"))}
check("governance/README.md has a row for each of the three checks, in the spec's order, and no other row",
      list(checks) == CHECKS, list(checks))
BUILT = {"Purpose and data": "wizard agent", "Architecture and access": "registered agent", "Vulnerability scan": "framework agent"}
check("each check's row says how it is built: a wizard agent, a registered agent (an agent folder), a framework agent (LangGraph)",
      all(len(checks.get(c, [])) > 1 and BUILT[c] in checks[c][1].lower() for c in CHECKS)
      and "agent folder" in " ".join(checks.get("Architecture and access", []))
      and "LangGraph" in " ".join(checks.get("Vulnerability scan", [])),
      {c: checks.get(c, [""])[1:2] for c in CHECKS})
FOLDER = {c: "governance/check-" + c.lower().replace(" ", "-") + "/" for c in CHECKS}
check("each check's row names its folder (governance/check-<name>/)", all(f"`{FOLDER[c]}`" in checks.get(c, []) for c in CHECKS),
      {c: checks.get(c) for c in CHECKS})
check("each check's row names its own evidence item, Validation: <check name>",
      all(f"Validation: {c}" in " ".join(checks.get(c, [])) for c in CHECKS)
      and all(f"Validation: {o}" not in " ".join(checks.get(c, [])) for c in CHECKS for o in CHECKS if o != c), checks)
OWNS = {"Purpose and data": ("what the app is for", "what data it holds", "intake", "not code security"),
        "Architecture and access": ("access", "who can call what", "tech stack", "design", "dependencies", "pinned", "installed"),
        "Vulnerability scan": ("known vulnerabilities", "code", "dependencies")}
check("each check's row says what it owns (spec #388, Implementation Decision 6)",
      all(all(w in " ".join(checks.get(c, [])).lower() for w in OWNS[c]) for c in CHECKS),
      {c: [w for w in OWNS[c] if w not in " ".join(checks.get(c, [])).lower()] for c in CHECKS})
docs = {c: " ".join(checks.get(c, [])[-1:]) for c in CHECKS}
check("each check's row says where its doc goes: checks 1 and 2 push it to their task branch and attach it as a Report, check 3 "
      "writes it to a dataset snapshot and attaches that file",
      all("task branch" in docs[c] and "Report" in docs[c] for c in CHECKS[:2])
      and "dataset snapshot" in docs[CHECKS[2]] and "task branch" not in docs[CHECKS[2]], docs)
check("each check's doc file name names the check and the bundle ID",
      all(re.search(rf"`[^`]*{c.lower().replace(' ', '-')}-<bundle ID>[^`]*\.md`", docs[c]) for c in CHECKS), docs)
check("governance/README.md says that a check files findings only in its own part",
      "A check files findings only in its own part." in one_line(hub), one_line(section(hub, "The three checks"))[:300])
check("governance/README.md names the tag app-validation-two-ways, which keeps the same job done two ways (spec #388, user story 47)",
      any(TAG in ln and "the same job, two ways" in ln for ln in hub.splitlines()), [ln for ln in hub.splitlines() if TAG in ln])
check("governance/README.md links to the rules file, governance/rules.md, for the rules that the three checks share",
      "[rules.md](rules.md)" in hub, [ln for ln in hub.splitlines() if "rules.md" in ln])

# --------------------------------------------------------------------------------------------- the shared rules: the evidence fields
# Spec #388, Implementation Decision 7: each evidence item has the same four fields, with these values. They replace spec #260's
# "Critical vulns" (yes or no, and "not analyzed" in the doc) and its verdict "approve after fixes".
check("governance/rules.md is in the repo: the one file of the rules that the three checks share", bool(rules))
FIELDS = {"Verdict": ["approve", "do not approve", "could not check"], "Highest severity": ["S0", "S1", "S2", "S3", "none"],
          "Summary": [], "Doc location": []}
fields = {r[0]: r for r in table(section(rules, "The evidence fields"))}
check("governance/rules.md has the four evidence fields, in order: Verdict, Highest severity, Summary, Doc location, and no other",
      list(fields) == list(FIELDS), list(fields))
values = {f: re.findall(r"`([^`]+)`", " ".join(fields.get(f, [])[1:2])) for f in FIELDS}
check("Verdict's values are exactly approve, do not approve and could not check", values["Verdict"] == FIELDS["Verdict"], values)
check("Highest severity's values are exactly S0, S1, S2, S3 and none", values["Highest severity"] == FIELDS["Highest severity"],
      values)
check("Summary and Doc location are text, with no list of values", not values["Summary"] and not values["Doc location"]
      and all(len(fields.get(f, [])) > 1 and fields[f][1] for f in ("Summary", "Doc location")), values)
evidence = one_line(section(rules, "The evidence fields"))
check("governance/rules.md says that the evidence item, the doc's Evidence and the result's first four lines have the same values",
      "The evidence item, the doc's part \"Evidence\" and the first four lines of the result have the same values." in evidence,
      evidence[:400])
check("governance/rules.md says that Highest severity is the highest severity of the check's real findings, and none with none",
      "the highest severity of the check's real findings" in evidence and re.search(r"`none` when [^.]*no real finding", evidence),
      evidence[:400])
check("governance/rules.md says that with could not check, Highest severity counts only the real findings that the check did file, "
      "and the Summary says what was not checked, and why",
      "With `could not check`, it counts only the real findings that the check did file" in evidence
      and "With `could not check`, it says what was not checked, and why." in evidence, evidence[:400])
# One verdict rule for all three checks (the orchestrator's decision for spec #388, 2026-11-19), so that the approver can compare
# them. False hits never count.
verdict_rule = evidence[evidence.find("**Verdict.**"):evidence.find("**Highest severity.**")] if "**Verdict.**" in evidence else ""
check("the Verdict rule: do not approve when at least one real finding of the check is S0 or S1",
      "`do not approve` when at least one real finding of the check is S0 or S1" in verdict_rule, verdict_rule[:400])
check("the Verdict rule: approve when the highest severity of its real findings is S2, S3 or none",
      "`approve` when the highest severity of its real findings is S2, S3 or `none`" in verdict_rule, verdict_rule[:400])
check("the Verdict rule: could not check when the check could not do its work, before the other two, also with an S0 or S1 finding",
      "`could not check` when the check could not do its work" in verdict_rule
      and "This comes before the other two, also with an S0 or S1 finding." in verdict_rule, verdict_rule[:400])
check("the Verdict rule: false hits never count, and the reason names the findings that decide it",
      "False hits never count" in verdict_rule and "The reason names the findings that decide it." in verdict_rule, verdict_rule[:400])
OLD_RULES = re.compile(r"critical vulns|not analyzed|approve after fixes", re.I)
check("governance/README.md and governance/rules.md have no rule of spec #260 left: no Critical vulns, no 'not analyzed', no "
      "'approve after fixes'", not OLD_RULES.search(hub + rules), sorted(set(m.group(0) for m in OLD_RULES.finditer(hub + rules))))

# ---------------------------------------------------------------------------------------------- the shared rules: could not check
# Spec #499 (ticket #508): one rule for the three checks: when a check could not do its work, what it does after a failed call, and
# where it says each limit. Each checklist names its own cases.
cannot = one_line(section(rules, "Could not check"))
check("governance/rules.md has the rule for could not check: the check could not read or judge a part that its verdict needs, for "
      "example a failed scan, a model with no usable answer, or a call that Domino denied",
      all(w in cannot for w in ("could not read or judge a part that its verdict needs", "a failed scan", "no usable answer",
                                "a call that Domino denied")), cannot[:400] or "no '## Could not check'")
check("...each checklist names the cases of its own check", "Each checklist names the cases of its own check." in cannot,
      cannot[:400])
check("...a failed or denied call: go on with the steps that don't need its answer, and try a failed call again at most once",
      "When a call fails or is denied, go on with the steps that don't need its answer. Try a failed call again at most once."
      in cannot, cannot[:400])
check('...each limit goes under "What this check could not check" in the doc and under "Could not check:" in the result, and each '
      "failed or denied call is named with Domino's answer",
      all(w in cannot for w in ('"What this check could not check"', '"Could not check:"', "with Domino's answer")), cannot[:400])
check("...a limit alone does not make the Verdict could not check when the check still did its work",
      "A limit alone does not make the Verdict `could not check` when the check still did its work." in cannot, cannot[:400])

# ---------------------------------------------------------------------------------------------- the shared rules: the doc location
# Spec #388, Implementation Decision 7: the same line in the evidence item and in the result. The doc's own line has no commit and no
# snapshot: the doc is written before them.
location = one_line(section(rules, "The doc location"))
check(f"governance/rules.md gives the Doc location of {CHECKS[0]} and {CHECKS[1]}: the task branch at the push's commit and the "
      "doc's file, or why the doc is not in the repo", "`<task branch> at <commit>, docs/validation/<file>`" in location
      and "`Not in the repo: <why>. The doc is in the task's result.`" in location, location[:400] or "no '## The doc location'")
check(f"...and of {CHECKS[2]}: the dataset, the snapshot and the file, or why it is not written",
      "`dataset <ID>, snapshot <ID>, file <name>`" in location and "`Not written: <why>.`" in location, location[:400])
check(f"governance/rules.md gives the doc's own Doc location of {CHECKS[0]} and {CHECKS[1]}: the task branch and the doc's file, "
      "with no commit (the doc is written before its push)",
      f"For {CHECKS[0]} and {CHECKS[1]}, that is `<task branch>, docs/validation/<file>`, where the task branch is "
      "`agent/<task key>`." in location, location[:400])

# ----------------------------------------------------------------------------------------- the severity scale and the finding names
# write_governance_finding's own words: "severity: S0 (critical), S1 (high), S2 (medium) or S3 (low)" (agent_runtime/gateway.py).
SCALE = {"S0": "critical", "S1": "high", "S2": "medium", "S3": "low"}
rows = dict(re.findall(r"^\| (S\d) \((\w+)\) \|", rules, re.M))
check("governance/rules.md has the severity scale, S0 to S3, with write_governance_finding's words", rows == SCALE, rows)
# The examples that the user agreed (spec #388, Implementation Decision 7), so that "S1" means the same in each check.
scale = section(rules, "The severity scale")
examples = table(scale[scale.find("### Examples"):]) if "### Examples" in scale else []
check("the severity scale has examples for each of the three checks, and for no other",
      sorted({r[0] for r in examples}) == sorted(CHECKS), sorted({r[0] for r in examples}))
AGREED = [("Purpose and data", "S1", ("an intake data class lower than the data that the app is built to hold",)),
          ("Architecture and access", "S1", ("`post /reset`", "anyone who can open the app can delete all state")),
          ("Architecture and access", "S2", ("a write with no `domino-username`", 'recorded as "no identity"')),
          ("Architecture and access", "S2", ("`mcp` installed from pypi at app start",)),
          ("Vulnerability scan", "S0", ("a known vulnerability that a caller can reach through the app's code",))]
for name, severity, said in AGREED:
    hit = [r for r in examples if len(r) > 2 and r[0] == name and all(w in one_line(r[1]).lower() for w in said)]
    check(f"the scale's example for {name}: {said[0]} is {severity}", [r[2] for r in hit] == [severity], hit or examples)
check("each example's severity is on the scale", examples and all(len(r) > 2 and r[2] in SCALE for r in examples), examples)

# The finding names: spec #388, Implementation Decision 7. The name says which check filed it and where the problem is.
names = section(rules, "Finding names")
check("governance/rules.md has the finding name rule [<check name>] <what> in <where>",
      "`[<check name>] <what> in <where>`" in names, one_line(names)[:300])
for name in CHECKS:
    shown = re.findall(rf"`\[{re.escape(name)}\] [^`]+ in [^`]+`", names)
    check(f"the finding name rule has an example for {name}, in the rule's shape", len(shown) == 1, shown or one_line(names)[:300])
check("the Vulnerability scan's example is the spec's: [Vulnerability scan] Code execution through yaml.full_load in POST /upload",
      "`[Vulnerability scan] Code execution through yaml.full_load in POST /upload`" in names, one_line(names)[:300])
check("a check files only its real findings, and a false hit goes in its doc only, with the reason",
      re.search(r"files only its real findings\. A false hit goes in its doc only, [^.]*with the reason", one_line(names)) is not None,
      one_line(names)[:400])
check("governance/README.md and governance/rules.md name no validator of spec #260: no [folder], no [LangGraph] finding names",
      "[folder]" not in hub + rules and "[LangGraph]" not in hub + rules,
      [ln for ln in (hub + rules).splitlines() if "[folder]" in ln or "[LangGraph]" in ln])

# ---------------------------------------------------------------------------------------------- the shared rules: the doc's template
# Spec #388, Implementation Decision 7: each check keeps the template's shared top part and only its own middle part.
trim = one_line(section(rules, "The doc's template"))
check("governance/rules.md says how a check trims the template to its own check: the shared top part, and only the middle part with "
      "the check's name, with the other two deleted", all(w in trim for w in (
          "[validation-doc.md](validation-doc.md)", "Keep the shared top part (from the title to \"What this check could not check\") "
          "and only the middle part with the check's name.", "Delete the other two middle parts, with all their text.")),
      trim[:400] or "no '## The doc's template'")
check("...and how it fills it: each {{field}} replaced, every heading kept in its order, every comment deleted",
      all(w in trim for w in ("Replace each `{{field}}` with its text.", "Keep every heading of the kept parts, in its order.",
                              "Delete every comment (`<!-- ... -->`).")), trim[:400])

# The result: spec #388, Implementation Decision 7. Checks 1 and 2 end with report_result; check 3, a framework agent, has no
# report_result and ends with its run's last streamed text. In both, the first lines are the four evidence values, so that
# "Validation status" and the task page show the same result. Each line is "<field label>: <value>".
result_rule = section(rules, "The result")
check("governance/rules.md has the rule for the result: Purpose and data and Architecture and access end with report_result, once, "
      "last, and Vulnerability scan (a framework agent, with no report_result) with its run's last streamed text",
      "Purpose and data and Architecture and access end with `report_result`, once, last." in one_line(result_rule)
      and "Vulnerability scan is a framework agent, which has no `report_result`: it ends with its run's last streamed text"
      in one_line(result_rule) and "In both, " in one_line(result_rule), one_line(result_rule)[:300] or "no '## The result'")
block = re.search(r"```\n(.*?)```", result_rule, re.S)
first = block.group(1).splitlines()[:4] if block else []
check("the result's first four lines are the four evidence fields, in order, each as '<label>: <value>'",
      [ln.split(":")[0] for ln in first] == list(FIELDS), first)
check("the result's Verdict and Highest severity lines give exactly their values",
      first[:2] == ["Verdict: approve | do not approve | could not check", "Highest severity: S0 | S1 | S2 | S3 | none"], first)
check("the result's four values are the same as the evidence item's", "the same values as the evidence item" in one_line(result_rule),
      one_line(result_rule)[:300])
check("...each line is plain text: the label, a colon and the value, with no Markdown",
      "Each line is the field's label, a colon and the value, with no Markdown." in one_line(result_rule), one_line(result_rule)[:400])
check('...then the real findings, the false hits and "Could not check:", and the whole doc when it is not at its location',
      all(w in one_line(result_rule) for w in ("the real findings (name and severity)", "the false hits (the hit and the reason)",
                                               '"Could not check:"', "add the whole doc after them")), one_line(result_rule)[:400])

# ------------------------------------------------------------------------------------ the rules file and governance/checks.json agree
# Spec #499 (ticket #508): checks.json is the one source of the values, and the rules file uses them. Each check name, field label,
# verdict and severity that the rules file gives is one of checks.json, in checks.json's order.
try:
    SOURCE = json.loads((ROOT / "governance" / "checks.json").read_text())
except (OSError, ValueError) as e:
    SOURCE = {"error": str(e)}
src_names = [c.get("name") for c in SOURCE.get("checks") or [] if isinstance(c, dict)]
src_labels = [(SOURCE.get("fields") or {}).get(k) for k in ("verdict", "severity", "summary", "doc")]
src_verdicts, src_severities = SOURCE.get("verdicts") or [], SOURCE.get("severities") or []
check("governance/checks.json names three checks, four labels, the verdicts and the severities",
      len(src_names) == 3 and all(src_labels) and src_verdicts and src_severities, SOURCE)
check("the rules file and checks.json agree: the evidence fields are the four labels of checks.json, in its order",
      list(fields) == src_labels, (list(fields), src_labels))
check("...Verdict's values are the verdicts of checks.json, and Highest severity's values are its severities, in its order",
      values["Verdict"] == src_verdicts and values["Highest severity"] == src_severities,
      (values["Verdict"], values["Highest severity"], src_verdicts, src_severities))
said_verdicts = re.findall(r"^\s*- `([^`]+)` when ", section(rules, "The evidence fields"), re.M)
check("...the verdict rule gives each verdict of checks.json one time, and no other", sorted(said_verdicts) == sorted(src_verdicts),
      said_verdicts)
check("...the severity scale is the severities of checks.json, in its order, but the last one, none (no real finding)",
      list(rows) == src_severities[:-1] and src_severities[-1:] == ["none"], (list(rows), src_severities))
check("...the result's first lines have the labels of checks.json, in its order, and its exact verdicts and severities",
      [ln.split(":")[0] for ln in first] == src_labels
      and first[:2] == [f"{src_labels[0]}: {' | '.join(src_verdicts)}", f"{src_labels[1]}: {' | '.join(src_severities)}"], first)
shown_checks = sorted({*re.findall(r"`\[([^\]<>]+)\] ", names), *(r[0] for r in examples)})
check("...each check in the examples of the finding names and of the scale is a check of checks.json, and each check of checks.json "
      "has its examples", shown_checks == sorted(src_names), (shown_checks, src_names))
check("...the doc location names each check of checks.json", src_names and all(n in location for n in src_names), location[:300])

# ------------------------------------------------------------------------------------------------- no other file copies a rule
# Spec #499 (ticket #508): each rule that the three checks share is in governance/rules.md one time, so that one change is one edit.
# Each rule below has the words that say it. No other Markdown file of the repo holds them: a Markdown file is what a person or an
# agent reads, so a copy there can drift. The code of the Vulnerability scan applies the verdict rule and the finding names with the
# values of governance/checks.json: that is code, not a copy.
SAYS = {"the verdict rule": ["s0 or s1"],
        "the finding name": ["<what> in <where>"],
        "the severity scale": ["s0 (critical)", "run code on the app's machine"],
        "the four result lines": ["verdict: approve | do not approve | could not check"],
        "could not check": ["could not do its work"],
        "the doc location format": ["branch> at <commit>", "not in the repo: <why>"],
        "the trim of the template to one check": ["other two middle parts", "only the middle part"]}


def flat(body):
    """A Markdown text as its words: in lower case, on one line, with no backticks."""
    return " ".join(body.replace("`", "").lower().split())


pages = {f.relative_to(ROOT).as_posix(): flat(f.read_text()) for f in sorted(ROOT.rglob("*.md"))
         if not any(p.startswith(".") for p in f.relative_to(ROOT).parts) and f.resolve() != RULES.resolve()}
for rule_name, words in SAYS.items():
    check(f"governance/rules.md says {rule_name}", all(w in flat(rules) for w in words), words)
    copies = sorted(f"{rel}: {w}" for rel, body in pages.items() for w in words if w in body)
    check(f"...and no other Markdown file of the repo copies {rule_name}", not copies, copies)

# ---------------------------------------------------------------------------------------------- the shared rules: a failed scan
# Spec #388, Implementation Decision 10: only check 3 runs the scan now. A failed scan gives "could not check" (it replaces spec #260's
# "do not approve"), no finding from the scan, and the Summary and the doc say why. The rest is the rule for could not check.
failed_scan = one_line(section(hub, "A failed scan"))
check("governance/README.md has the rule for a failed scan: when the Job did not succeed or the summary's result is not 'both tools "
      "ran'", "`Succeeded`" in failed_scan and "`result: both tools ran`" in failed_scan, failed_scan[:400] or "no '## A failed scan'")
check("the rule for a failed scan says that only the Vulnerability scan runs the scan",
      re.search(r"[Oo]nly the Vulnerability scan runs the scan", failed_scan) is not None, failed_scan[:400])
check("a failed scan gives the Verdict could not check, and never do not approve",
      "The Verdict is `could not check`" in failed_scan and "`do not approve`" not in failed_scan, failed_scan[:400])
check("a failed scan gives no finding from the scan", "No finding comes from the scan" in failed_scan, failed_scan[:400])
check("after a failed scan, the Summary and the doc's Scan results and 'What this check could not check' say that the scan failed, "
      "and why", all(w in failed_scan for w in ("Summary", "Scan results", "What this check could not check", "why")),
      failed_scan[:400])
check("...and the rest is the rule for could not check, in the rules file", '"Could not check" of [rules.md](rules.md)' in failed_scan,
      failed_scan[:400])

# ------------------------------------------------------------------------------------------------------------------ the doc template
# Spec #388, Implementation Decision 7: one shared top part (the App, the commit, the bundle, the check's name, the four evidence
# fields, and "What this check could not check"), then one middle part for each check, each with its findings. A check keeps the top
# part and its own middle part. Its headings are the check's name, so that a check finds its part by its name.
TEMPLATE = ROOT / "governance" / "validation-doc.md"
doc = TEMPLATE.read_text() if TEMPLATE.is_file() else ""
TOP = ["App and version", "Evidence", "What this check could not check"]
MIDDLE = {"Purpose and data": ["Purpose", "Users", "Data class", "Findings"],
          "Architecture and access": ["Tech stack", "Architecture", "Access", "Dependencies", "Findings"],
          "Vulnerability scan": ["Scan results", "Findings"]}
FINDINGS = ["Real findings", "False hits"]
tree, path, text = {}, (), {}
for ln in doc.splitlines():
    m = re.match(r"^(#{1,4}) (.*)", ln)
    if m:
        level = len(m.group(1))
        path = path[:level - 1] + ("",) * (level - 1 - len(path)) + (m.group(2).strip(),)
        tree.setdefault(path[:-1], []).append(path[-1])
        text[path] = ""
    elif path:
        text[path] += ln.lower() + "\n"
title = [p for p in text if len(p) == 1]
check("the doc template has one title, which names the App", len(title) == 1 and "{{app}}" in title[0][0], title)
top_line = text.get(title[0], "") if title else ""
check("the line under the title names the check, the bundle and when the doc was written",
      all(f in top_line for f in ("{{check}}", "{{bundle_id}}", "{{written_at}}")), top_line[:300])
h2 = tree.get(title[0], []) if title else []
check("the doc template has the shared top part, then a middle part for each check, named by the check, in the checks' order",
      h2 == TOP + CHECKS, h2)
for name in CHECKS:
    got = tree.get(title[0] + (name,), []) if title else []
    check(f"the middle part {name!r} has its sections, in order: {', '.join(MIDDLE[name])}", got == MIDDLE[name], got)
    got = tree.get(title[0] + (name, "Findings"), []) if title else []
    check(f"the middle part {name!r} has its own findings: the real ones and the false hits", got == FINDINGS, got)
leaves = [p for p in text if p not in tree]
check("each section of the template has a {{field}} to fill", leaves and all(re.search(r"\{\{[a-z_]+\}\}", text[p]) for p in leaves),
      [" > ".join(p[1:]) for p in leaves if not re.search(r"\{\{[a-z_]+\}\}", text[p])])
top = title[0] if title else ("",)
ev = [ln[2:] for ln in text.get(top + ("Evidence",), "").splitlines() if re.match(r"^- [a-z ]+: \{\{", ln)]
check("the top part's Evidence has the four evidence fields, in order, each as '- <label>: {{field}}'",
      [ln.split(":")[0] for ln in ev] == [f.lower() for f in FIELDS], ev)


def says(where, *words):
    got = text.get(top + where, "")
    check(f"the doc template's {' > '.join(where)!r} says: {', '.join(words)}", all(w in got for w in words), got[:300])


says(("App and version",), "repository", "commit")
says(("Evidence",), "approve", "do not approve", "could not check", "s0", "s3", "none", "same values as the evidence item")
says(("What this check could not check",), "the commit of the app version under review", "default branch", "running app")
says(("Purpose and data", "Purpose"), "code", "readme", "intake's purpose")
says(("Purpose and data", "Users"), "intake's users")
says(("Purpose and data", "Data class"), "kind of data", "built to hold", "intake's data class",
     "not by whether the sample data is fake", "public", "internal", "confidential", "restricted")
says(("Architecture and access", "Tech stack"), "language", "frameworks", "server", "storage")
says(("Architecture and access", "Architecture"), "entry point", "routes", "where the state is", "who can call what")
says(("Architecture and access", "Access"), "who can open the app", "what it changes", "identity")
says(("Architecture and access", "Dependencies"), "version or range", "pinned", "how and when it is installed")
says(("Vulnerability scan", "Scan results"), "tool", "version", "hits", "did not check", "governance/scan.py")
for name in CHECKS:
    says((name, "Findings", "Real findings"), "name", "severity", "evidence", "fix", f"[{name.lower()}]")
    says((name, "Findings", "False hits"), "reason")
check("the doc template has no rule of spec #260 left: no Critical vulns, no 'not analyzed', no 'approve after fixes', no validator",
      not re.search(r"critical vulns|not analyzed|approve after fixes|validator", doc, re.I),
      sorted(set(m.group(0) for m in re.finditer(r"critical vulns|not analyzed|approve after fixes|validator", doc, re.I))))

# --------------------------------------------------------------------------------------------- words that a public reader can follow
# The repo is public. Its validator files say what was learned, never "as the probe did" (a private note). And they use the
# platform's words (domino-agent-service GLOSSARY.md): a "framework agent", never a "framework-lane agent". This file is left out:
# it names the words.
PUBLIC = [ROOT / "README.md",
          *(f for f in sorted((ROOT / "governance").rglob("*")) if f.is_file() and f.suffix in (".py", ".md", ".yaml", ".json")),
          *(f for f in sorted((ROOT / "tests").glob("check_valid*.py")) if f.resolve() != Path(__file__).resolve())]
PRIVATE = re.compile(r"\bthe probe\b|\bprobe's\b|\btrigger test\b|trigger_probe|framework-lane agent", re.I)
said = sorted(f"{f.relative_to(ROOT)}:{n}: {m.group(0)}" for f in PUBLIC for n, ln in enumerate(f.read_text().splitlines(), 1)
              for m in PRIVATE.finditer(ln))
check("the validators' public files point at no private note (the probe, the trigger test) and say framework agent, not "
      "framework-lane agent", not said, said)

# ------------------------------------------------------------------------- the two validators of spec #260: on the tag, not on the branch
# Spec #388 (ticket #390) took them off the branch. The tag app-validation-two-ways keeps their folders and their checks. No file of
# the branch names one of them, but on a line that also names the tag (to say where it is). This file is left out: it names them.
OLD = ["governance/validator-folder", "governance/validator-langgraph", "tests/check_validator_folder.py",
       "tests/check_validator_langgraph.py"]
still = [p for p in OLD if (ROOT / p).exists()]
check(f"the two #260 validators' folders and their checks are not on the branch (the tag {TAG} keeps them)", not still, still)
OLD_NAME = re.compile(r"validator-folder|validator-langgraph|check_validator_folder|check_validator_langgraph")
TEXT = (".md", ".py", ".yaml", ".yml", ".json", ".sh", ".txt", ".toml")
branch_files = [f for f in sorted(ROOT.rglob("*")) if f.is_file() and f.suffix in TEXT and f.resolve() != Path(__file__).resolve()
                and not any(part.startswith(".") or part == "__pycache__" for part in f.relative_to(ROOT).parts)]
named = sorted(f"{f.relative_to(ROOT)}:{n}: {m.group(0)}" for f in branch_files
               for n, ln in enumerate(f.read_text(errors="replace").splitlines(), 1) if TAG not in ln for m in OLD_NAME.finditer(ln))
check(f"no README, doc or check links to or names a file of the two #260 validators, but on a line that names the tag {TAG}",
      not named, named)

service = os.environ.get("AGENT_SERVICE_REPO", "").strip()
if not service:
    print("SKIP: AGENT_SERVICE_REPO is not set, so the severity scale wasn't checked against the gateway's write_governance_finding. "
          "Set it to a domino-agent-service checkout.", flush=True)
    sys.exit(1 if failed else 0)
sys.path.insert(0, service)
from agent_runtime import gateway  # noqa: E402  (stdlib only; from AGENT_SERVICE_REPO)

check("write_governance_finding takes exactly the scale's four severities", set(gateway.SEVERITY.values()) == set(SCALE),
      sorted(set(gateway.SEVERITY.values())))
check("write_governance_finding maps each severity and its word to that severity, as the scale says",
      all(gateway.SEVERITY.get(code.lower()) == code and gateway.SEVERITY.get(word) == code for code, word in rows.items()) and rows,
      {code: (gateway.SEVERITY.get(code.lower()), gateway.SEVERITY.get(word)) for code, word in rows.items()})
sys.exit(1 if failed else 0)
