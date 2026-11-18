"""The shared parts of the two App validators (domino-agent-service spec #260, Implementation Decision 7), seen from outside: the scan
script as a Domino Job runs it, the doc template, and the severity scale with the rule for finding names (governance/README.md).

The scan script runs with no network: a bare venv (no pip-audit, no bandit, no pip) and fake scanners on PYTHONPATH that answer with
the real tools' output, saved in tests/fixtures/scan/ (pip-audit 2.10.1 and bandit 1.9.4 on case_server: `clean` is main,
`vulnerable` is pip-audit's answer for the demo branch's pin, pyyaml==5.3.1, and `gaps` adds a file that bandit can't parse and a
package that isn't on PyPI). The fakes copy the real tools: their `--version` line,
their JSON file at -o, their messages on stderr and their exit codes (pip-audit: 0, 1 with hits, 1 and no JSON when it fails; bandit:
0, 1 with hits). A fake pip "installs" the fake scanners, as a Job's pip installs the real ones.

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

# ----------------------------------------------------------------------------------------- the severity scale and the finding names
# write_governance_finding's own words: "severity: S0 (critical), S1 (high), S2 (medium) or S3 (low)" (agent_runtime/gateway.py).
SCALE = {"S0": "critical", "S1": "high", "S2": "medium", "S3": "low"}
RULES = ROOT / "governance" / "README.md"
rules = RULES.read_text() if RULES.is_file() else ""
rows = dict(re.findall(r"^\| (S\d) \((\w+)\) \|", rules, re.M))
check("governance/README.md has the severity scale, S0 to S3, with write_governance_finding's words", rows == SCALE, rows)
flat = " ".join(rules.split())
check("governance/README.md says that each finding's name starts with the validator's short name, [folder] or [LangGraph]",
      "[folder]" in flat and "[LangGraph]" in flat and "starts with" in flat, flat[:300])
check("governance/README.md says that critical vulns is yes when at least one real finding is S0",
      re.search(r"critical vulns.{0,40}yes.{0,80}at least one real finding is S0", flat, re.I) is not None, flat[:300])
failed_scan = " ".join(rules[rules.find("## A failed scan"):].split("\n## ")[0].split()) if "## A failed scan" in rules else ""
check("governance/README.md has one rule for a failed scan, for both validators: do not approve, no finding from the scan, critical "
      "vulns no only as 'No S0 finding; dependencies not scanned', and the summary and the doc say that the scan failed",
      all(w in failed_scan for w in ("result: both tools ran", "`do not approve`", "No finding comes from the scan",
                                     "No S0 finding; dependencies not scanned", "Summary", "What the validator could not check")),
      failed_scan[:400] or "no section '## A failed scan'")

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
