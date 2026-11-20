---
name: purpose-and-data
description: The checklist of the check Purpose and data, from the governance bundle to the filled evidence item. Use it in every task of this agent.
---
# Check what the App of a governance bundle is for and what data it holds

The task's instruction names the bundle ID (`bundleId` below). Do the steps in order. A step is done when its "Done when" line is true.

This check owns one part of the validation: what the App is for and what data it holds, compared with the Intake answers (Purpose, Users, Data class). It is not a review of code security: two other checks own the access, the code and the dependencies.

The project folder (its path is in the operating rules) holds the shared parts of the three checks:

- `governance/README.md`: the three checks and what each one owns, the evidence fields, the severity scale (S0 to S3), the finding names and the result.
- `governance/validation-doc.md`: the template of the doc.

When a call fails or is denied, go on with the steps that don't need its answer. Name the call and Domino's answer under "What this check could not check" (in the doc, or in the result when the doc is already pushed). Try a failed call again at most once.

## 1. Read the bundle and its policy

- `domino_get_bundle(bundleId)`: the bundle's name, its project and its stage.
- `domino_get_policy(bundleId)`: the policy that the bundle follows. In its stage named "Validation", find the evidence item whose name is exactly "Validation: Purpose and data", and keep its `id`: that is your evidenceId.
- In that item's `artifacts`, find each field by its `details.label` and keep its `id`: "Verdict", "Highest severity", "Summary", "Doc location".
- A radio field (Verdict, Highest severity) takes one of its `details.options` as its value: use the option's `value`, exactly.
- The Intake values that the analyst filled: in the stage named "Intake", find the evidence item "Intake", and in its `artifacts` the fields "Purpose", "Users" and "Data class" by `details.label`. Each field's value is its `result.artifactContent`. A field with no `result` is not filled.

Done when: you have the evidenceId and the four artifact IDs, or you know which of them the policy doesn't have, and you have the three Intake values (or know which ones are not filled). When you can't read the policy, the check can't do its work: the verdict is `could not check` (step 5).

## 2. Read the App

Read the App in the project folder: `README.md`, `app.sh` (the App's start script), each file that `app.sh` starts, each file of code that they import, and the sample data that the code loads (a seed, a fixture or a sample file). Collect:

- the purpose: what the App does, and for whom, from the README and the code;
- the users: who uses the App, and how (people in a browser, agents through its tools, other systems);
- the data: each kind of data that the App holds or shows, from the code (its tables and their fields, the answers of its routes and its tools) and from the sample data. For each kind, note what it is about: for example people by name, their money and their activity, risk flags, or notes that people write about a person.

Done when: each fact for the doc's sections "Purpose", "Users" and "Data class" has a file (and a line, where it is code) as its evidence.

## 3. Classify the data

The classes are the Intake's four, from low to high: Public, Internal, Confidential, Restricted. Give the App's data one class: the highest class of any kind of data that it holds.

| Class | The data |
|---|---|
| Public | Meant for anyone. Nothing about a person who can be named, and no harm when it is published. |
| Internal | For the company's own people. No data about named customers, or only data that does no harm when it leaks. |
| Confidential | Business data, or data about named people, that does harm when it leaks: for example customers by name with their accounts, their activity or their contact details. |
| Restricted | The data that does the most harm when it leaks, or that a law or a regulator restricts: for example the records of a financial crime investigation about named people, reports of a suspicion, flags of political exposure, health data, government IDs or credentials. |

- Judge the class by the kind of data that the App is built to hold: the fields of its tables, its routes and its tools, and what each field is for.
- Classify it by the kind of data, not by whether the sample data is fake: fake sample data shows the kind of data that the App holds when people use it. When the README or the data says that the data is fake, say so in the doc, and still give the class of that kind of data.

Done when: the App's data has one class, and each kind of data that decides it has its evidence (a file and a line).

## 4. Compare with the Intake

Compare what the App is for and what data it holds (steps 2 and 3) with the Intake's Purpose, Users and Data class (step 1). Each difference that matters is a real finding, with a severity on the scale of `governance/README.md` (S0 to S3):

- An Intake Data class lower than the class of the data that the App is built to hold, or a Data class that is not filled: S1. The data gets less protection than it needs. This is the scale's example for this check.
- An Intake Data class higher than the class of the data: no finding. Say it in the doc.
- An Intake Purpose or Users that is not filled, or that differs from what the App does or from who uses it: S3, a gap in a record.

File findings only in your own part: what the App is for and what data it holds, against the Intake. Not code security.
When you see a problem in another check's part, file nothing for it: that check files it. Who can read the data through the App (its access) is the part of the check Architecture and access. A weakness in the code or a dependency is the part of the checks Architecture and access and Vulnerability scan.

Each real finding gets a name, its severity, its evidence (the Intake field and its value, and the file and line that show the data) and a fix. The name is `[Purpose and data] <what> in <where>`, where `<where>` is an Intake field, a file or a route. For example: `[Purpose and data] Data class Internal for Restricted data in the Intake`.

Something that looks like a problem and is not one is a false hit: it goes in the doc, with the reason why it is not a finding. File no false hit.

Done when: each difference is a real finding with a severity, or a false hit with its reason.

## 5. Write the doc

- Copy `governance/validation-doc.md` to `docs/validation/purpose-and-data-<bundleId>.md` in the project folder.
- Keep the shared top part (from the title to "What this check could not check") and only the middle part named "Purpose and data". Delete the other two middle parts ("Architecture and access" and "Vulnerability scan").
- Replace each `{{field}}` with its text. Keep every heading of your parts, in its order. Delete every comment (`<!-- ... -->`).
- `app`: the App's name. `check`: `Purpose and data`. `bundle_id`: the bundle ID. `written_at`: the time now, from `date -u '+%Y-%m-%d %H:%M'`.
- `app_and_version`: the App's name, its repository, and the commit that you read (`git rev-parse HEAD` in the project folder).
- `verdict`: exactly one of `approve`, `do not approve`, `could not check`, by the one rule of the three checks (`governance/README.md`, "The evidence fields"):
  - `do not approve` when at least one real finding is S0 or S1.
  - `approve` when the highest severity of the real findings is S2, S3 or `none`.
  - `could not check` when the check could not do its work: for example you could not read the policy or the Intake values, or the App's code is not in the project folder. This comes before the other two.
  - The reason names the findings that decide it. The verdict is advice: the approver decides.
- `highest_severity`: the highest severity of the real findings (`S0` is the highest), or `none` when there is no real finding.
- `summary`: three to five sentences: the verdict's reason, and each real finding by its name and its severity.
- `doc_location`: the doc is written before its push, so name only the task branch and the file, with no commit: `agent/<task key>, docs/validation/purpose-and-data-<bundleId>.md`.
- `could_not_check`: each limit of this check. Always: the commit of the App version under review (the task reads the project's default branch, not the version's commit), and the data in the running App (the check reads the code and the sample data, not the App's state). Also each call that failed or that Domino denied.
- `purpose`, `users`, `data_class`: from steps 2 to 4. Each one gives the Intake's value ("not filled" for a field with no value), and says where it differs.
- `real_findings`, `false_hits`: the tables of step 4.

Done when: the file has no `{{` and no `<!--` left, it has only the top part and the part "Purpose and data", and each section has its text.

## 6. Push the doc

- `domino_git_push(message="Validation doc of bundle <bundleId> (Purpose and data)")` commits the doc to the task branch and pushes it. Its answer is JSON: keep `ok`, `branch`, `commit` and `dryRun`.

Done when: you have the branch and the commit, and you know whether `dryRun` is true.

## 7. Attach the doc

- Only when the push answered `ok` true and `dryRun` false: `domino_write_bundle_attachment(bundleId, type="Report", identifier={"filename": "docs/validation/purpose-and-data-<bundleId>.md", "commit": <the push's commit>, "source": "GBP", "branch": <the push's branch>})`.
- When `dryRun` is true, the commit is not on the remote: attach nothing. Say under could not check in the result: "The push was a dry run, so the doc is not in the repo and not attached to the bundle".
- When `ok` is false, the doc is not in the repo either: attach nothing, and say why under could not check in the result.

Done when: the bundle has the Report attachment, or the result will say why it has none.

## 8. File the real findings

For each real finding of the doc: `domino_write_governance_finding(bundleId, name="[Purpose and data] <what> in <where>", severity="S0" to "S3", description=<the evidence, why it matters, the fix, and the doc's location>)`. Use the name and the severity of the doc's table. File no false hit.

Done when: each real finding of the doc is filed once.

## 9. Fill your evidence item

Fill only your own evidence item, "Validation: Purpose and data": `domino_write_policy_result(bundleId, evidenceId=<step 1>, content={<Verdict ID>: <the verdict>, <Highest severity ID>: <the highest severity>, <Summary ID>: <the summary>, <Doc location ID>: <the doc location>})`.

The doc location is one line, with the push's branch and commit: `<branch> at <commit>, docs/validation/purpose-and-data-<bundleId>.md`. When the doc is not in the repo: `Not in the repo: <why>. The doc is in the task's result.`

Done when: the answer's `results` show your four values for your evidenceId.

## 10. Report the result

Call `domino_report_result(summary)`, once, last. The summary starts with these four lines, each on its own line, with the same values as your evidence item (step 9). Each line is the field's label, a colon and the value, with no Markdown:

```
Verdict: approve | do not approve | could not check
Highest severity: S0 | S1 | S2 | S3 | none
Summary: <the Summary, on one line>
Doc location: <the Doc location>
```

Then: the real findings (name and severity), the false hits (what and why), and "Could not check:" with each limit and each failed or denied call. When the doc is not in the repo, add the whole doc after them, so that the approver can read it.

Done when: `domino_report_result` answered "Recorded".
