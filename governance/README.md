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
| Vulnerability scan | A framework agent (a LangGraph graph, code in Git) | `governance/check-vulnerability-scan/` | Validation: Vulnerability scan | Known vulnerabilities in the code and the dependencies (the scan) | Written to the doc dataset as `vulnerability-scan-<bundle ID>-<UTC time>.md`, in a dataset snapshot, and attached to the bundle as a dataset snapshot file |

Each agent's name is its check's name. Each check fills only its own evidence item.

A check files findings only in its own part. When it sees a problem in another check's part, it files nothing for it: the check that
owns that part files it. Where two parts meet:

- A dependency's version range, its pin and how it is installed are Architecture and access. A known vulnerability in it (a CVE,
  PYSEC or GHSA ID) is Vulnerability scan.
- Who can call a route, and what it changes, is Architecture and access. A scanner hit in the code is Vulnerability scan.
- The kind of data that the App holds, and its class, is Purpose and data. Who can read that data through the App is Architecture
  and access.

## The evidence fields

Each check fills its own evidence item with `write_policy_result`. The three items have the same four fields, with these labels and
values:

| Field | Its value |
|---|---|
| Verdict | `approve`, `do not approve` or `could not check` |
| Highest severity | `S0`, `S1`, `S2`, `S3` or `none` |
| Summary | A short text: the verdict's reason, and the real findings by name and severity |
| Doc location | One line that says where the doc is |

- **Verdict.** One rule for all three checks, so that the approver can compare them. False hits never count.
  - `do not approve` when at least one real finding of the check is S0 or S1.
  - `approve` when the highest severity of its real findings is S2, S3 or `none`.
  - `could not check` when the check could not do its work (for example a failed scan, a model that refused the call or gave no
    usable answer, or a call that Domino denied). This comes before the other two, also with an S0 or S1 finding. Then Highest
    severity names only what it did check, and the Summary says why.

  The reason names the findings that decide it. The verdict is advice: the approver decides.
- **Highest severity.** It is the highest severity of the check's real findings, on the scale below: `S0` when at least one real
  finding is S0. It is `none` when the check has no real finding. With `could not check`, it counts the real findings that the check
  did file, and it is `none` when it filed none.
- **Summary.** Three to five sentences: the verdict's reason, and each real finding by its name and its severity. With
  `could not check`, it says what was not checked, and why.
- **Doc location.** The same line in the evidence item and in the result:
  - Purpose and data, Architecture and access (a pushed doc): `<task branch> at <commit>, docs/validation/<file>`. When the doc is
    not in the repo: `Not in the repo: <why>. The doc is in the task's result.`
  - Vulnerability scan (a dataset snapshot): `dataset <ID>, snapshot <ID>, file <name>`. When there is no snapshot:
    `Not written: <why>.`

  The doc is written before its push or its snapshot, so its own top part names only the file and where it goes, with no commit and
  no snapshot.

## The severity scale

The four severities that the gateway tool `write_governance_finding` takes. One scale for all three checks, so that "S1" means the
same in each check.

| Severity | Use it for |
|---|---|
| S0 (critical) | A caller can run code on the App's machine. Or a known vulnerability (a CVE, PYSEC or GHSA ID) that a caller can reach through the App's code. |
| S1 (high) | A caller can wipe, change or read data that they must not, with no code execution. Or the App holds data of a higher class than its Intake says, so the data gets less protection than it needs. |
| S2 (medium) | A weakness that can do harm only together with another flaw, an insider or a bad release of a dependency. Or a record that can't say who made a change. |
| S3 (low) | A hardening step or a gap in a record or a document, with no direct harm. |

### Examples for each check

The examples show how to pick a severity. They are not a list of the expected findings.

| Check | Example | Severity |
|---|---|---|
| Purpose and data | An Intake data class lower than the data that the App is built to hold | S1 |
| Architecture and access | `POST /reset`: anyone who can open the App can delete all state | S1 |
| Architecture and access | A write with no `domino-username`, recorded as "no identity" | S2 |
| Architecture and access | `mcp` installed from PyPI at App start | S2 |
| Vulnerability scan | A known vulnerability that a caller can reach through the App's code | S0 |

## Finding names

Each finding's name is `[<check name>] <what> in <where>`: the check's name in brackets, what the problem is, and where it is (a
route, a file, a dependency or an Intake field). The name says which check filed the finding, so that the analyst can send it to the
right team.

| Check | An example |
|---|---|
| Purpose and data | `[Purpose and data] Data class Internal for Restricted data in the Intake` |
| Architecture and access | `[Architecture and access] Anyone who can open the App can delete all state in POST /reset` |
| Vulnerability scan | `[Vulnerability scan] Code execution through yaml.full_load in POST /upload` |

A check files only its real findings. A false hit goes in its doc only, under "False hits", with the reason.

## The result

Purpose and data and Architecture and access end with `report_result`, once, last. Vulnerability scan is a framework agent, which has
no `report_result`: it ends with its run's last streamed text, which is the task's result. In both, the result starts with four
lines, one for each evidence field, in the fields' order, with the same values as the evidence item:

```
Verdict: approve | do not approve | could not check
Highest severity: S0 | S1 | S2 | S3 | none
Summary: <the Summary, on one line>
Doc location: <the Doc location>
```

Each line is the field's label, a colon and the value, with no Markdown. "Validation status" reads these lines, so it and the task's
page show the same result. Then come the real findings (name and severity), the false hits (the hit and the reason), and "Could not
check:" with each limit of the check. When the doc is not at its location (not pushed, or not in a snapshot), add the whole doc after
them, so that the approver can read it.

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
- Highest severity counts only the real findings that the check filed. It is `none` when it filed none.
- The evidence item's Summary, and the doc's "Scan results" and "What this check could not check", say that the scan failed, and
  why.

## The check

```bash
python tests/check_validator_parts.py
AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_validator_parts.py
```

It runs the scan with no network: in a bare venv, with fake scanners that answer with the real tools' output (saved in
`tests/fixtures/scan/`: `clean` is main, `vulnerable` is pip-audit's answer for `pyyaml==5.3.1`, and `gaps` has a file that bandit
can't parse and a package that isn't on PyPI). It covers the summary (each tool, its version and its hits, at the end of the output,
nothing on stderr), the JSON files, the parts that a tool did not check, a tool that cannot run, and the install. It also checks
this page's rules (the three checks, the evidence fields and their values, the scale and its examples, the finding names, the result
and a failed scan), and the doc template (its shared top part, and each check's middle part with its findings). With
`AGENT_SERVICE_REPO` (a domino-agent-service checkout, any OS), it checks the severity scale against the gateway's
`write_governance_finding`. Without it, that part prints a SKIP line.
