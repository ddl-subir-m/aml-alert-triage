---
name: app-validation
description: The checklist of an App validation, from the governance bundle to the filled evidence item. Use it in every task of this agent.
---
# Validate the App of a governance bundle

The task's instruction names the bundle ID (`bundleId` below). Do the steps in order. A step is done when its "Done when" line is true.

The project folder (its path is in the operating rules) holds the shared parts of the validators:

- `governance/README.md`: the severity scale (S0 to S3), the finding names and the rule for "critical vulns".
- `governance/validation-doc.md`: the template of the doc.
- `governance/scan.py`: the scan, which you run in a Domino Job.

When a call fails or is denied, go on with the steps that don't need its answer. Name the call and Domino's answer under "What the validator could not check" (in the doc, or in the result when the doc is already pushed). Try a failed call again at most once.

## 1. Read the bundle and its policy

- `domino_get_bundle(bundleId)`: the bundle's name, its project and its stage.
- `domino_get_policy(bundleId)`: the policy that the bundle follows. In its stage named "Validation", find the evidence item whose name is exactly "Validation (agent folder)", and keep its `id`: that is your evidenceId.
- In that item's `artifacts`, find each field by its `details.label` and keep its `id`: "Verdict", "Critical vulns", "Summary", "Doc location".
- A radio field takes one of its `details.options` as its value: use the option's `value`, exactly.

Done when: you have the evidenceId and the four artifact IDs, or you know which of them the policy doesn't have.

## 2. Read the App

Read the App's code and its start script in the project folder: `README.md`, `app.sh`, each file that `app.sh` starts or installs, each file of code that they import, and each requirements file. Also read `governance/README.md`. Collect:

- the purpose and the users, from the code and the README;
- the tech stack: the language, the frameworks, the server and the storage;
- the architecture: the entry point, the routes or tools, where the state is, and who can call what;
- each dependency, with its version or range and how it is installed: from a requirements file, by the start script when the App starts, or from the Domino Environment.

The Intake values (users, data class) that the analyst filled are not readable: no gateway tool reads a bundle's evidence values. In the doc, write "Not read" with that reason, and name it under could not check.

Done when: each fact for the doc's sections from "Purpose" to "Dependencies" has a file (and a line, where it is code) as its evidence.

## 3. Run the scan

- `domino_run_job(command="python governance/scan.py", title="App validation scan, bundle <bundleId>")`. Keep the Job's ID from the answer (`job.id`).
- `domino_wait_job(jobId)`. While it says that the Job is still running, call it again.
- When the Job is finished, find the scan summary in the end of its output: the lines between `== scan summary ==` and `== end of scan summary ==`. Domino adds lines of its own after the summary. If the summary isn't there, `domino_get_job_logs(jobId)` gives more of the log.
- The summary's `commit:` line is the commit that the scan read. Its `result:` line says whether both tools ran.

Done when: you have the summary, or you know why there is none (the Job failed, or a tool could not run). A tool that could not run goes under could not check, and so does each part that the summary says was not checked (`- not audited: ...`, `- not scanned: ...`).

## 4. Sort each hit

For each hit of the scan summary (each known vulnerability of pip-audit, each hit of bandit), read the code that it points at. Then decide: a real finding or a false hit.

- A real finding gets a severity on the scale of `governance/README.md` (S0, S1, S2 or S3), a name `[folder] <short title>`, its evidence (the file and line, and the hit or the code) and a fix.
- A known vulnerability of a dependency is S0 when a caller can reach the vulnerable function through the App's code. Find that call in the code, and cite it.
- A false hit gets the reason why it is false, from the code: what the flagged line really does, or why the App needs it.

Then review the code for what no scanner sees, and add each real finding of it: who can call each route and what it changes, which identity each write records, and what is installed, from where, and when.

Done when: each hit is a real finding or a false hit, each real finding has a severity, and each false hit has a reason.

## 5. Write the doc

- Copy `governance/validation-doc.md` to `docs/validation/agent-folder-<bundleId>.md` in the project folder.
- Replace each `{{field}}` with its text. Keep every heading, in its order. Delete every comment (`<!-- ... -->`).
- `validator`: `App validator (agent folder)`. `bundle_id`: the bundle ID. `written_at`: the time now, from `date -u '+%Y-%m-%d %H:%M'`.
- `critical_vulns`: `yes` when at least one real finding is S0, else `no`. The reason names those findings, or says why no finding is S0.
- `verdict`: exactly one of `approve`, `approve after fixes`, `do not approve`. The reason names the findings that decide it.
- `could_not_check`: each limit of this review. Always: the commit of the App version under review (the task reads the project's default branch, not the version's commit), what only the running App shows (the Apps proxy, the identity headers, who can open the App), and the Intake values. Also each tool that could not run, and each failed or denied call.

Done when: the file has no `{{` and no `<!--` left, and each section has its text.

## 6. Push the doc

- `domino_git_push(message="Validation doc of bundle <bundleId> (agent folder)")` commits the doc to the task branch and pushes it. Its answer is JSON: keep `ok`, `branch`, `commit` and `dryRun`.

Done when: you have the branch and the commit, and you know whether `dryRun` is true.

## 7. Attach the doc

- Only when the push answered `ok` true and `dryRun` false: `domino_write_bundle_attachment(bundleId, type="Report", identifier={"filename": "docs/validation/agent-folder-<bundleId>.md", "commit": <the push's commit>, "source": "GBP", "branch": <the push's branch>})`.
- When `dryRun` is true, the commit is not on the remote: attach nothing. Say under could not check in the result: "The push was a dry run, so the doc is not in the repo and not attached to the bundle".
- When `ok` is false, the doc is not in the repo either: attach nothing, and say why under could not check in the result.

Done when: the bundle has the Report attachment, or the result will say why it has none.

## 8. File the real findings

For each real finding of the doc: `domino_write_governance_finding(bundleId, name="[folder] <short title>", severity="S0" to "S3", description=<the evidence, why it matters, the fix, and the doc's location>)`. Use the name and the severity of the doc's table. File no false hit.

Done when: each real finding of the doc is filed once.

## 9. Fill your evidence item

Fill only your own evidence item, "Validation (agent folder)": `domino_write_policy_result(bundleId, evidenceId=<step 1>, content={<Verdict ID>: <the verdict>, <Critical vulns ID>: "yes" or "no", <Summary ID>: <three to five sentences: the verdict's reason, and the real findings by name and severity>, <Doc location ID>: <the doc location>})`.

The doc location is one line: `<branch> at <commit>, docs/validation/agent-folder-<bundleId>.md`. When the doc is not in the repo: `Not in the repo: <why>. The doc is in the task's result.`

Done when: the answer's `results` show your four values for your evidenceId.

## 10. Report the result

Call `domino_report_result(summary)`, once, last. The summary starts with these three lines, each on its own line, with one of the values and the same doc location as in step 9:

```
Verdict: approve | approve after fixes | do not approve
Critical vulns: yes | no
Doc location: <the doc location>
```

Then: the real findings (name and severity), the false hits (the hit and the reason), and "Could not check:" with each limit and each failed or denied call. When the doc is not in the repo, add the whole doc after them, so that the approver can read it.

Done when: `domino_report_result` answered "Recorded".
