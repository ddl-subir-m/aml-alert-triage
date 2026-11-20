"""The shared parts of the two App validators (domino-agent-service spec #260, Implementation Decision 7), seen from outside: the scan
script as a Domino Job runs it, the doc template, and the severity scale with the rule for finding names (governance/README.md).

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

# ------------------------------------------------------------------------------------------------------------------ the doc template
# The sections of spec #260, Implementation Decision 7, in its order.
SECTIONS = ["App and version", "Purpose", "Users and data class", "Tech stack", "Architecture", "Dependencies", "Scan results",
            "Findings", "Critical vulns", "Verdict for the approver", "What the validator could not check"]
TEMPLATE = ROOT / "governance" / "validation-doc.md"
doc = TEMPLATE.read_text() if TEMPLATE.is_file() else ""
headings = [ln[3:].strip() for ln in doc.splitlines() if ln.startswith("## ")]
check("the doc template has every section of the spec, in its order, and no other", headings == SECTIONS, headings)
parts = {}
for ln in doc.splitlines():
    if ln.startswith("## "):
        parts[ln[3:].strip()] = ""
    elif parts:
        parts[list(parts)[-1]] += ln.lower() + "\n"
check("each section has a {{field}} for the validator to fill", bool(parts) and all(re.search(r"\{\{[a-z_]+\}\}", t) for t in parts.values()),
      [h for h, t in parts.items() if not re.search(r"\{\{[a-z_]+\}\}", t)])


def says(section, *words):
    text = parts.get(section, "")
    check(f"the doc template's {section!r} section says: {', '.join(words)}", all(w in text for w in words), text[:300])


says("App and version", "commit")
says("Users and data class", "intake")
says("Dependencies", "installed")
says("Scan results", "tool", "version", "hits")
says("Findings", "severity", "evidence", "false", "reason")
says("Critical vulns", "yes", "no", "s0")
says("Verdict for the approver", "approve", "approve after fixes", "do not approve")

# ---------------------------------------------------------------------------------------------------- the shared rules: the checks
# Spec #388, Implementation Decisions 5 to 7: three checks, each one built its own way, each one owns one part. The names are the
# ones of the spec (and of governance/checks.json, which this check does not read).
RULES = ROOT / "governance" / "README.md"
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


checks = {r[0]: r for r in table(section(rules, "The three checks"))}
check("governance/README.md has a row for each of the three checks, in the spec's order, and no other row",
      list(checks) == CHECKS, list(checks))
BUILT = {"Purpose and data": "wizard agent", "Architecture and access": "registered agent", "Vulnerability scan": "framework agent"}
check("each check's row says how it is built: a wizard agent, a registered agent (an agent folder), a framework agent (LangGraph)",
      all(len(checks.get(c, [])) > 1 and BUILT[c] in checks[c][1].lower() for c in CHECKS)
      and "agent folder" in " ".join(checks.get("Architecture and access", [])) and "LangGraph" in " ".join(checks.get("Vulnerability scan", [])),
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
      "A check files findings only in its own part." in one_line(rules), one_line(section(rules, "The three checks"))[:300])
check("governance/README.md names the tag app-validation-two-ways, which keeps the same job done two ways (spec #388, user story 47)",
      any(TAG in ln and "the same job, two ways" in ln for ln in rules.splitlines()), [ln for ln in rules.splitlines() if TAG in ln])

# --------------------------------------------------------------------------------------------- the shared rules: the evidence fields
# Spec #388, Implementation Decision 7: each evidence item has the same four fields, with these values. They replace spec #260's
# "Critical vulns" (yes or no, and "not analyzed" in the doc) and its verdict "approve after fixes".
FIELDS = {"Verdict": ["approve", "do not approve", "could not check"], "Highest severity": ["S0", "S1", "S2", "S3", "none"],
          "Summary": [], "Doc location": []}
fields = {r[0]: r for r in table(section(rules, "The evidence fields"))}
check("governance/README.md has the four evidence fields, in order: Verdict, Highest severity, Summary, Doc location, and no other",
      list(fields) == list(FIELDS), list(fields))
values = {f: re.findall(r"`([^`]+)`", " ".join(fields.get(f, [])[1:2])) for f in FIELDS}
check("Verdict's values are exactly approve, do not approve and could not check", values["Verdict"] == FIELDS["Verdict"], values)
check("Highest severity's values are exactly S0, S1, S2, S3 and none", values["Highest severity"] == FIELDS["Highest severity"], values)
check("Summary and Doc location are text, with no list of values", not values["Summary"] and not values["Doc location"]
      and all(len(fields.get(f, [])) > 1 and fields[f][1] for f in ("Summary", "Doc location")), values)
evidence = one_line(section(rules, "The evidence fields"))
check("governance/README.md says that Highest severity is the highest severity of the check's real findings, and none when it has none",
      "the highest severity of the check's real findings" in evidence and re.search(r"`none` when [^.]*no real finding", evidence),
      evidence[:400])
check("governance/README.md says when the Verdict is could not check: the check could not do its work, and the Summary says why",
      re.search(r"`could not check` when the check could not do its work", evidence) is not None and "Summary says why" in evidence,
      evidence[:400])
OLD_RULES = re.compile(r"critical vulns|not analyzed|approve after fixes", re.I)
check("governance/README.md has no rule of spec #260 left: no Critical vulns, no 'not analyzed', no 'approve after fixes'",
      not OLD_RULES.search(rules), sorted(set(m.group(0) for m in OLD_RULES.finditer(rules))))

# ----------------------------------------------------------------------------------------- the severity scale and the finding names
# write_governance_finding's own words: "severity: S0 (critical), S1 (high), S2 (medium) or S3 (low)" (agent_runtime/gateway.py).
SCALE = {"S0": "critical", "S1": "high", "S2": "medium", "S3": "low"}
rows = dict(re.findall(r"^\| (S\d) \((\w+)\) \|", rules, re.M))
check("governance/README.md has the severity scale, S0 to S3, with write_governance_finding's words", rows == SCALE, rows)
# The examples that the user agreed (spec #388, Implementation Decision 7), so that "S1" means the same in each check.
scale = section(rules, "The severity scale")
examples = table(scale[scale.find("### Examples"):]) if "### Examples" in scale else []
check("the severity scale has examples for each of the three checks, and for no other", sorted({r[0] for r in examples}) == sorted(CHECKS),
      sorted({r[0] for r in examples}))
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
check("governance/README.md has the finding name rule [<check name>] <what> in <where>",
      "`[<check name>] <what> in <where>`" in names, one_line(names)[:300])
for name in CHECKS:
    shown = re.findall(rf"`\[{re.escape(name)}\] [^`]+ in [^`]+`", names)
    check(f"the finding name rule has an example for {name}, in the rule's shape", len(shown) == 1, shown or one_line(names)[:300])
check("the Vulnerability scan's example is the spec's: [Vulnerability scan] Code execution through yaml.full_load in POST /upload",
      "`[Vulnerability scan] Code execution through yaml.full_load in POST /upload`" in names, one_line(names)[:300])
check("a check files only its real findings, and a false hit goes in its doc only, with the reason",
      re.search(r"files only its real findings\. A false hit goes in its doc only, [^.]*with the reason", one_line(names)) is not None,
      one_line(names)[:400])
check("governance/README.md names no validator of spec #260: no [folder], no [LangGraph] finding names",
      "[folder]" not in rules and "[LangGraph]" not in rules, [ln for ln in rules.splitlines() if "[folder]" in ln or "[LangGraph]" in ln])

# ---------------------------------------------------------------------------------------------- the shared rules: a failed scan
# Spec #388, Implementation Decision 10: only check 3 runs the scan now. A failed scan gives "could not check" (it replaces spec #260's
# "do not approve"), no finding from the scan, and the Summary and the doc say why.
failed_scan = one_line(section(rules, "A failed scan"))
check("governance/README.md has the rule for a failed scan: when the Job did not succeed or the summary's result is not 'both tools "
      "ran'", "`Succeeded`" in failed_scan and "`result: both tools ran`" in failed_scan, failed_scan[:400] or "no '## A failed scan'")
check("the rule for a failed scan says that only the Vulnerability scan runs the scan",
      re.search(r"[Oo]nly the Vulnerability scan runs the scan", failed_scan) is not None, failed_scan[:400])
check("a failed scan gives the Verdict could not check, and never do not approve",
      "The Verdict is `could not check`" in failed_scan and "`do not approve`" not in failed_scan, failed_scan[:400])
check("a failed scan gives no finding from the scan", "No finding comes from the scan" in failed_scan, failed_scan[:400])
check("after a failed scan, the Summary and the doc's Scan results and 'What this check could not check' say that the scan failed, "
      "and why", all(w in failed_scan for w in ("Summary", "Scan results", "What this check could not check", "why")), failed_scan[:400])

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
