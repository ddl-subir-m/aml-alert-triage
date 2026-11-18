"""The scan of the App validation demo (domino-agent-service spec #260): pip-audit and bandit on the case server. Both validators run it
in a Domino Job, with the gateway tool run_job and the command `python governance/scan.py`. Stdlib only.

  python governance/scan.py              # from the project's root, as a Job runs it
  python governance/scan.py --out DIR    # where the JSON goes (default: $DOMINO_ARTIFACTS_DIR/governance-scan, else a new temp folder)

1. pip-audit on case_server/requirements.txt (it resolves the requirements from PyPI) and bandit on case_server/ (all severities).
   Each tool's JSON goes to the output folder (pip-audit.json, bandit.json), and its own messages to <tool>.log there.
2. The last thing it prints is a short summary, between "== scan summary ==" and "== end of scan summary ==": each tool, its version
   and its hits. The summary does not sort the hits: each validator decides which ones are real.

The end of the Job's log is what wait_job shows the agent (its last 8,000 characters), and a Job's stderr comes after its stdout there.
So the script writes nothing to stderr: the tools' own output goes to their log files.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # the project's root: this file is governance/scan.py
REQUIREMENTS = "case_server/requirements.txt"
SOURCE = "case_server"
START, END = "== scan summary ==", "== end of scan summary =="
LINE = 320   # the longest line of the summary: pip-audit's description of PYSEC-2021-142 is about 500 characters


def say(line):
    print(line, flush=True)


def run(args, log):
    """One tool run from the project's root, its stdout and stderr in the log file. -> exit code"""
    with open(log, "w") as f:
        return subprocess.run(args, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT).returncode


def version(module):
    """The tool's version: the last word of its `--version` line (pip-audit: "pip-audit 2.10.1"; bandit: "__main__.py 1.9.4")."""
    p = subprocess.run([sys.executable, "-m", module, "--version"], cwd=ROOT, capture_output=True, text=True)
    words = (p.stdout.strip().splitlines() or [""])[0].split()
    return words[-1] if p.returncode == 0 and words else "(version unknown)"


def commit():
    """The commit that was scanned: the project's HEAD (a Git-based project's Job has the repo at its root)."""
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    except OSError:
        return "unknown (no git)"
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else "unknown (not a git checkout)"


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def clip(text, n=LINE):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 3] + "..."


def pip_audit_lines(out):
    report = read_json(out / "pip-audit.json") or {}
    deps = report.get("dependencies") or []
    hits = []   # one line per package and vulnerability ID: pip-audit can list one vulnerability twice
    for d in deps:
        seen = {}
        for v in d.get("vulns") or []:
            seen.setdefault(v.get("id"), v)
        for vid, v in seen.items():
            aliases = ", ".join(v.get("aliases") or [])
            fix = ", ".join(v.get("fix_versions") or []) or "none known"
            hits.append(clip(f"- {d.get('name')} {d.get('version')}: {vid}" + (f" ({aliases})" if aliases else "")
                             + f", fixed in {fix}: {v.get('description') or 'no description'}"))
    head = f"pip-audit {version('pip_audit')} on {REQUIREMENTS}: "
    if not hits:
        return [head + f"no known vulnerabilities in {len(deps)} packages"]
    packages = sum(1 for d in deps if d.get("vulns"))
    return [head + f"{len(hits)} known vulnerabilit{'y' if len(hits) == 1 else 'ies'} in {packages} of {len(deps)} packages", *hits]


def bandit_lines(out):
    report = read_json(out / "bandit.json") or {}
    hits = report.get("results") or []
    lines = [f"bandit {version('bandit')} on {SOURCE} (all severities): {len(hits)} hits"]
    for h in hits:
        lines.append(f"- {h.get('test_id')} {h.get('test_name')} at {h.get('filename')}:{h.get('line_number')}, severity "
                     f"{h.get('issue_severity')}, confidence {h.get('issue_confidence')}: {h.get('issue_text')}")
    return lines


def main():
    ap = argparse.ArgumentParser(description="pip-audit and bandit on the case server, with a short summary at the end")
    ap.add_argument("--out", help="where the JSON goes (default: $DOMINO_ARTIFACTS_DIR/governance-scan, else a new temp folder)")
    a = ap.parse_args()
    arts = os.environ.get("DOMINO_ARTIFACTS_DIR")
    out = Path(a.out or (Path(arts) / "governance-scan" if arts else tempfile.mkdtemp(prefix="governance-scan-")))
    out.mkdir(parents=True, exist_ok=True)
    say(f"scan: pip-audit and bandit on {SOURCE} (governance/scan.py), output in {out}")

    say(f"scan: running pip-audit on {REQUIREMENTS}")
    run([sys.executable, "-m", "pip_audit", "-r", REQUIREMENTS, "--progress-spinner", "off", "--format", "json",
         "-o", str(out / "pip-audit.json")], out / "pip-audit.log")
    say(f"scan: running bandit on {SOURCE}")
    run([sys.executable, "-m", "bandit", "-r", SOURCE, "-f", "json", "-o", str(out / "bandit.json")], out / "bandit.log")

    say("\n".join([START, f"commit: {commit()}", *pip_audit_lines(out), *bandit_lines(out),
                   f"JSON: {out / 'pip-audit.json'}, {out / 'bandit.json'}", END]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
