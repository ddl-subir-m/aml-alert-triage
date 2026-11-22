# The three validation checks

The App validation demo (domino-agent-service spec #388) has three checks at the Validation stage of the policy "App deployment
policy". Each check is an agent that one team owns, and each team builds its agent in its own way. All three checks follow the rules
of [rules.md](rules.md), so that the approver can compare three results. All the data is fake.

The tag `app-validation-two-ways` keeps the demo of spec #260: two validators that do the same job, two ways.

| Part | What it is |
|---|---|
| This page | The three checks and what each one owns, the scan, and a failed scan |
| [rules.md](rules.md) | The rules that the three checks share, each one time: the evidence fields and the verdict rule, could not check, the doc location, the severity scale, the finding names, the doc's template and the result |
| [checks.json](checks.json) | The one source of the values: the check names, the evidence items, the field labels, the verdicts and the severities |
| [validation-doc.md](validation-doc.md) | The template of each check's doc: one shared top part, and one middle part for each check |
| [scan.py](scan.py) | The scan: pip-audit and bandit on the case server, in a Domino Job. Only the Vulnerability scan runs it |

There is no list of the expected findings. Each check reads the App and sorts what it finds itself.

## The three checks

| Check | Built as | Its folder | Its evidence item | What it owns | Its doc |
|---|---|---|---|---|---|
| Purpose and data | A wizard agent (made in the UI) | `governance/check-purpose-and-data/` | Validation: Purpose and data | What the App is for and what data it holds, compared with the Intake answers (Purpose, Users, Data class). Not code security | Pushed to its task branch as `docs/validation/purpose-and-data-<bundle ID>.md`, and attached to the bundle as a Report |
| Architecture and access | A registered agent (an agent folder in Git, deployed with `domino-agent deploy`) | `governance/check-architecture-and-access/` | Validation: Architecture and access | All access (who can call what, and which identity each write records), the tech stack, the design, and the dependencies with how they are pinned and installed | Pushed to its task branch as `docs/validation/architecture-and-access-<bundle ID>.md`, and attached to the bundle as a Report |
| Vulnerability scan | A framework agent (a LangGraph graph, code in Git) | `governance/check-vulnerability-scan/` | Validation: Vulnerability scan | Known vulnerabilities in the code and the dependencies (the scan) | Written to the doc dataset as `vulnerability-scan-<bundle ID>-<UTC time>.md`, in a dataset snapshot, and attached to the bundle as a dataset snapshot file |

Each agent's name is its check's name. Each check fills only its own evidence item.

A check files findings only in its own part. When it sees a problem in another check's part, it files nothing for it: the check that
owns that part files it. Where two parts meet:

- A dependency's version range, its pin and how it is installed are Architecture and access. A known vulnerability in it (a CVE,
  PYSEC or GHSA ID) is Vulnerability scan.
- Who can call a route, and what it changes, is Architecture and access. A scanner hit in the code is Vulnerability scan.
- The kind of data that the App holds, and its class, is Purpose and data. Who can read that data through the App is Architecture
  and access.

## The scan

The Vulnerability scan starts it with the gateway tool `run_job` and the command `python governance/scan.py`, then calls `wait_job`
until the Job ends.

- It installs pip-audit and bandit with pip when the Domino Environment does not have them (the Job reaches PyPI).
- It runs pip-audit on `case_server/requirements.txt` (pip-audit resolves the requirements from PyPI) and bandit on `case_server/` at
  every severity. Each tool's JSON goes to `$DOMINO_ARTIFACTS_DIR/governance-scan/`, with the tool's own messages in `<tool>.log`.
- The last lines that it prints are the summary, between `== scan summary ==` and `== end of scan summary ==`: the commit that it
  scanned, each tool with its version and its hits, where the JSON is, and a `result:` line.
- It exits 0 when both tools ran, with hits or not. It exits 1 when a tool could not run, and the summary says which tool and why.
  The doc then says so under "What this check could not check".
- A tool can run and still miss a part: pip-audit does not audit a package that is not on PyPI (its `skip_reason`), and bandit does
  not scan a file that it cannot parse (its `errors`). The summary counts only what was checked, and names each part that was not
  (`- not audited: ...`, `- not scanned: ...`). The doc names each one under "What this check could not check".

`wait_job` shows the end of the Job's log: its last 8,000 characters. The summary is short, so it is there. Domino adds a few lines of
its own after the script's output, and the Job's stderr (Domino's messages only: the script writes nothing to stderr) comes after its
stdout. So find the summary by its two marker lines. `get_job_logs` gives more of the log.

On your computer, in a Python with pip-audit and bandit (or with network to install them):

```bash
python governance/scan.py --out /tmp/governance-scan
```

## A failed scan

Only the Vulnerability scan runs the scan. The scan failed when its Job did not end `Succeeded`, or when its summary's `result:` line
is not `result: both tools ran` (a tool could not run). Then nobody checked the dependencies:

- The Verdict is `could not check`: run the check again when the scan runs.
- No finding comes from the scan, so none is filed. A real finding in the code that the check found with no scan is filed as usual.
- The evidence item's Summary, and the doc's "Scan results" and "What this check could not check", say that the scan failed, and
  why.

The rest is the rule "Could not check" of [rules.md](rules.md).

## The check

```bash
python tests/check_validator_parts.py
AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_validator_parts.py
```

It runs the scan with no network: in a bare venv, with fake scanners that answer with the real tools' output (saved in
`tests/fixtures/scan/`: `clean` is main, `vulnerable` is pip-audit's answer for `pyyaml==5.3.1`, and `gaps` has a file that bandit
can't parse and a package that isn't on PyPI). It covers the summary (each tool, its version and its hits, at the end of the output,
nothing on stderr), the JSON files, the parts that a tool did not check, a tool that cannot run, and the install. It also checks
this page (the three checks and a failed scan), each rule of `rules.md`, that `rules.md` and `checks.json` agree (each check name,
field label, verdict and severity), that no other Markdown file of the repo copies a rule of `rules.md`, and the doc template (its
shared top part, and each check's middle part with its findings). With
`AGENT_SERVICE_REPO` (a domino-agent-service checkout, any OS), it checks the severity scale against the gateway's
`write_governance_finding`. Without it, that part prints a SKIP line.

The checks of the three checks (`tests/check_purpose_and_data.py`, `tests/check_architecture_and_access.py` and
`tests/check_vulnerability_scan.py`) share `tests/three_checks.py`, with the stdlib only: the case lines, the reading of
`governance/checks.json`, the rule lines, the leak pattern of the public repo, and the fakes of a stage move.
