# The shared rules of the three checks

The App validation demo (domino-agent-service spec #388) has three checks at the Validation stage of the policy "App deployment
policy". Each check is an agent that one team owns, and each team builds its agent in its own way. All three checks use the rules on
this page, so that the approver can compare three results. All the data is fake.

The tag `app-validation-two-ways` keeps the demo of spec #260: two validators that do the same job, two ways.

| Part | What it is |
|---|---|
| This page | The three checks, the evidence fields, the severity scale, the finding names, the rule for a failed scan and the rule for the result |
| [validation-doc.md](validation-doc.md) | The template of each check's doc: one shared top part, and one middle part for each check |
| [scan.py](scan.py) | The scan: pip-audit and bandit on the case server, in a Domino Job. Only the Vulnerability scan runs it |

There is no list of the expected findings. Each check reads the App and sorts what it finds itself.

## The three checks

| Check | Built as | Its folder | Its evidence item | What it owns | Its doc |
|---|---|---|---|---|---|
| Purpose and data | A wizard agent (made in the UI) | `governance/check-purpose-and-data/` | Validation: Purpose and data | What the App is for and what data it holds, compared with the Intake answers (Purpose, Users, Data class). Not code security | Pushed to its task branch as `docs/validation/purpose-and-data-<bundle ID>.md`, and attached to the bundle as a Report |
| Architecture and access | A registered agent (an agent folder in Git, deployed with `domino-agent deploy`) | `governance/check-architecture-and-access/` | Validation: Architecture and access | All access (who can call what, and which identity each write records), the tech stack, the design, and the dependencies with how they are pinned and installed | Pushed to its task branch as `docs/validation/architecture-and-access-<bundle ID>.md`, and attached to the bundle as a Report |
| Vulnerability scan | A framework agent (a LangGraph graph, code in Git) | `governance/check-vulnerability-scan/` | Validation: Vulnerability scan | Known vulnerabilities in the code and the dependencies (the scan) | Written to a dataset snapshot of the doc dataset as `vulnerability-scan-<bundle ID>-<UTC time>.md`, and that file attached to the bundle |

Each agent's name is its check's name. Each check fills only its own evidence item.

A check files findings only in its own part. When it sees a problem in another check's part, it files nothing for it: the check that
owns that part files it. Where two parts meet:

- A dependency's version range, its pin and how it is installed are Architecture and access. A known vulnerability in it (a CVE,
  PYSEC or GHSA ID) is Vulnerability scan.
- Who can call a route, and what it changes, is Architecture and access. A scanner hit in the code is Vulnerability scan.
- The kind of data that the App holds, and its class, is Purpose and data. Who can read that data through the App is Architecture
  and access.

## The scan

A validator starts it with the gateway tool `run_job` and the command `python governance/scan.py`, then calls `wait_job` until the Job
ends.

- It installs pip-audit and bandit with pip when the Domino Environment does not have them (the Job reaches PyPI).
- It runs pip-audit on `case_server/requirements.txt` (pip-audit resolves the requirements from PyPI) and bandit on `case_server/` at
  every severity. Each tool's JSON goes to `$DOMINO_ARTIFACTS_DIR/governance-scan/`, with the tool's own messages in `<tool>.log`.
- The last lines that it prints are the summary, between `== scan summary ==` and `== end of scan summary ==`: the commit that it
  scanned, each tool with its version and its hits, where the JSON is, and a `result:` line.
- It exits 0 when both tools ran, with hits or not. It exits 1 when a tool could not run, and the summary says which tool and why.
  The doc then says so under "What the validator could not check".
- A tool can run and still miss a part: pip-audit does not audit a package that is not on PyPI (its `skip_reason`), and bandit does
  not scan a file that it cannot parse (its `errors`). The summary counts only what was checked, and names each part that was not
  (`- not audited: ...`, `- not scanned: ...`). The doc names each one under "What the validator could not check".

`wait_job` shows the end of the Job's log: its last 8,000 characters. The summary is short, so it is there. Domino adds a few lines of
its own after the script's output, and the Job's stderr (Domino's messages only: the script writes nothing to stderr) comes after its
stdout. So find the summary by its two marker lines. `get_job_logs` gives more of the log.

On your computer, in a Python with pip-audit and bandit (or with network to install them):

```bash
python governance/scan.py --out /tmp/governance-scan
```

## The severity scale

The four severities that the gateway tool `write_governance_finding` takes.

| Severity | Use it for |
|---|---|
| S0 (critical) | A caller can run code on the App's machine. Or a known vulnerability (a CVE, PYSEC or GHSA ID) that a caller can reach through the App's code. |
| S1 (high) | A caller can wipe, change or read data that they must not, with no code execution. |
| S2 (medium) | A weakness that can do harm only together with another flaw, an insider or a bad release of a dependency. |
| S3 (low) | A hardening step or a gap in a record, with no direct harm. |

## Finding names

Each finding's name starts with the validator's short name in brackets, then a short title: `[folder] <title>` or
`[LangGraph] <title>`. Two validators can file findings that look the same, and the name says which validator filed each one.

A validator files only the real findings. A false hit goes in the doc only, under "False hits", with the reason.

## Critical vulns

The doc's "Critical vulns" is `yes` when at least one real finding is S0, and `no` when none is. It is `not analyzed` when the
analysis failed (the model refused the call, or gave no usable answer): nothing was checked, so it is neither. The evidence item's
Critical vulns radio (`yes` or `no` only) then stays empty, and its Summary says why.

## A failed scan

The scan failed when its Job did not end `Succeeded`, or when its summary's `result:` line is not `result: both tools ran` (a tool
could not run). Then nobody checked the dependencies, and both validators do the same:

- The verdict is `do not approve`: run the validation again when the scan runs.
- No finding comes from the scan, so none is filed. The findings from the code are filed as usual.
- Critical vulns stays `yes` or `no`: the policy's field has only these two values. It is `yes` when a finding from the code is S0.
  Else it is `no`, and its reason starts with "No S0 finding; dependencies not scanned".
- The evidence item's Summary, and the doc's "Scan results" and "What the validator could not check", say that the scan failed, and
  why.

## The check

```bash
python tests/check_validator_parts.py
AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_validator_parts.py
```

It runs the scan with no network: in a bare venv, with fake scanners that answer with the real tools' output (saved in
`tests/fixtures/scan/`: `clean` is main, `vulnerable` is pip-audit's answer for `pyyaml==5.3.1`, and `gaps` has a file that bandit
can't parse and a package that isn't on PyPI). It covers the summary (each tool, its version and its hits, at the end of the output,
nothing on stderr), the JSON files, the parts that a tool did not check, a tool that cannot run, and the install. It
also checks the doc template's sections and this page's rules. With `AGENT_SERVICE_REPO` (a domino-agent-service checkout, any OS), it
checks the severity scale against the gateway's `write_governance_finding`. Without it, that part prints a SKIP line.
