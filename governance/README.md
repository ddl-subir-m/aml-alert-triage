# The shared parts of the App validators

The App validation demo (domino-agent-service spec #260) has two validators that do the same job in two lanes: the agent folder
validator (harness lane, short name `folder`) and the LangGraph validator (framework lane, short name `LangGraph`). Both use the parts
on this page, so that the demo compares two lanes, not two jobs. All the data is fake.

| Part | What it is |
|---|---|
| [scan.py](scan.py) | The scan: pip-audit and bandit on the case server, in a Domino Job |
| [validation-doc.md](validation-doc.md) | The template of the validation doc |
| This page | The severity scale, the finding names and the rule for "critical vulns" |

There is no list of the expected findings. Each validator reads the code and the scan, and sorts the hits itself.

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

The doc's "Critical vulns" is `yes` when at least one real finding is S0, and `no` when none is.

## The check

```bash
python tests/check_validator_parts.py
AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_validator_parts.py
```

It runs the scan with no network: in a bare venv, with fake scanners that answer with the real tools' output (saved in
`tests/fixtures/scan/`: `clean` is main, and `vulnerable` is pip-audit's answer for `pyyaml==5.3.1`). It covers the summary (each tool,
its version and its hits, at the end of the output, nothing on stderr), the JSON files, a tool that cannot run, and the install. It
also checks the doc template's sections and this page's rules. With `AGENT_SERVICE_REPO` (a domino-agent-service checkout, any OS), it
checks the severity scale against the gateway's `write_governance_finding`. Without it, that part prints a SKIP line.
