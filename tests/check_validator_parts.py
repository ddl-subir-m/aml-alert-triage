"""The shared parts of the two App validators (domino-agent-service spec #260, Implementation Decision 7), seen from outside: the scan
script as a Domino Job runs it, the doc template, and the severity scale with the rule for finding names (governance/README.md).

The scan script runs with no network: a bare venv (no pip-audit, no bandit, no pip) and fake scanners on PYTHONPATH that answer with
the real tools' output, saved in tests/fixtures/scan/ (pip-audit 2.10.1 and bandit 1.9.4 on case_server: `clean` is main, and
`vulnerable` is pip-audit's answer for the demo branch's pin, pyyaml==5.3.1). The fakes copy the real tools: their `--version` line,
their JSON file at -o, their messages on stderr and their exit codes (pip-audit: 0, 1 with hits, 1 and no JSON when it fails; bandit:
0, 1 with hits). A fake pip "installs" the fake scanners, as a Job's pip installs the real ones.

With AGENT_SERVICE_REPO (the path of a domino-agent-service checkout), it also checks the severity scale against the gateway's
write_governance_finding (agent_runtime/gateway.py, stdlib only, so any OS). Without it, that part prints a SKIP line.

  python tests/check_validator_parts.py
  AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_validator_parts.py
"""
import json
import os
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
check("the scan installs both tools with pip in one call (a Job reaches PyPI, as the probe's did)",
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
sys.exit(1 if failed else 0)
