# The rules of the three checks

The three checks of the App validation demo follow these rules, so that the approver can compare three results. Each rule is on this
page one time, and no other file copies it:

- Both checklists (the `SKILL.md` files of Purpose and data and of Architecture and access) say to read this page.
- The Vulnerability scan puts this page in the prompt of its analyze step. Its code applies the verdict rule and the finding names.

[checks.json](checks.json) is the one source of the values: the check names, the evidence items, the field labels, the verdicts and
the severities. This page uses those values. `tests/check_validator_parts.py` makes sure that the two agree.

What each check owns, and where two parts meet, is on [README.md](README.md), "The three checks".

## The evidence fields

Each check fills only its own evidence item, with `write_policy_result`. The three items have the same four fields, with these labels
and values:

| Field | Its value |
|---|---|
| Verdict | `approve`, `do not approve` or `could not check` |
| Highest severity | `S0`, `S1`, `S2`, `S3` or `none` |
| Summary | A short text: the verdict's reason, and the real findings by name and severity |
| Doc location | One line that says where the doc is |

The evidence item, the doc's part "Evidence" and the first four lines of the result have the same values. The one difference is the
doc's own Doc location (see "The doc location").

- **Verdict.** One rule for all three checks, so that the approver can compare them. False hits never count.
  - `could not check` when the check could not do its work (see "Could not check"). This comes before the other two, also with an S0
    or S1 finding.
  - `do not approve` when at least one real finding of the check is S0 or S1.
  - `approve` when the highest severity of its real findings is S2, S3 or `none`.

  The reason names the findings that decide it. The verdict is advice: the approver decides.
- **Highest severity.** It is the highest severity of the check's real findings, on the severity scale: `S0` when at least one real
  finding is S0. It is `none` when the check has no real finding. With `could not check`, it counts only the real findings that the
  check did file, and it is `none` when it filed none.
- **Summary.** Three to five sentences: the verdict's reason, and each real finding by its name and its severity. With
  `could not check`, it says what was not checked, and why.
- **Doc location.** One line: see "The doc location".

## Could not check

A check could not do its work when it could not read or judge a part that its verdict needs. For example: a failed scan (README.md,
"A failed scan"), a model that refused the call or gave no usable answer, or a call that Domino denied. Each checklist names the cases
of its own check.

- When a call fails or is denied, go on with the steps that don't need its answer. Try a failed call again at most once.
- Say each limit of the check under "What this check could not check" in the doc (or in the result, when the doc is already pushed),
  and under "Could not check:" in the result. Name each failed or denied call, with Domino's answer.
- A limit alone does not make the Verdict `could not check` when the check still did its work.

## The doc location

The same line in the evidence item and in the result:

- Purpose and data, Architecture and access (a pushed doc): `<task branch> at <commit>, docs/validation/<file>`, with the push's
  branch and commit. When the doc is not in the repo: `Not in the repo: <why>. The doc is in the task's result.`
- Vulnerability scan (a dataset snapshot): `dataset <ID>, snapshot <ID>, file <name>`. When there is no snapshot:
  `Not written: <why>.`

The doc is written before its push or its snapshot, so its own Doc location (in its part "Evidence") names only the file and where it
goes, with no commit and no snapshot. For Purpose and data and Architecture and access, that is
`<task branch>, docs/validation/<file>`, where the task branch is `agent/<task key>`.

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
right team. The same name is in the doc's table of real findings and in `write_governance_finding`.

| Check | An example |
|---|---|
| Purpose and data | `[Purpose and data] Data class Internal for Restricted data in the Intake` |
| Architecture and access | `[Architecture and access] Anyone who can open the App can delete all state in POST /reset` |
| Vulnerability scan | `[Vulnerability scan] Code execution through yaml.full_load in POST /upload` |

A check files only its real findings. A false hit goes in its doc only, under "False hits", with the reason.

## The doc's template

Each check writes one doc from the template [validation-doc.md](validation-doc.md), at its own file name:

- Keep the shared top part (from the title to "What this check could not check") and only the middle part with the check's name.
  Delete the other two middle parts, with all their text.
- Replace each `{{field}}` with its text. Keep every heading of the kept parts, in its order. Delete every comment (`<!-- ... -->`).

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
