---
name: architecture-and-access
description: The checklist of the check Architecture and access, from the governance bundle to the filled evidence item. Use it in every task of this agent.
---
# Check the architecture and access of the App of a governance bundle

The task's instruction names the bundle ID (`bundleId` below). Do the steps in order. A step is done when its "Done when" line is true.

You are the check "Architecture and access", one of the three checks of the Validation stage. Your part: all access (who can call each route or tool, what it changes, and which identity each write records), the tech stack, the design, and the dependencies with how they are pinned and installed. You run no scan and start no Job.

The project folder (its path is in the operating rules) holds the shared rules of the three checks:

- `governance/README.md`: the evidence fields, the verdict rule, the severity scale (S0 to S3) with its examples for each check, the finding names and the rule for the result.
- `governance/validation-doc.md`: the template of the doc.

File findings only in your own part, never in the parts of the other two checks, "Purpose and data" and "Vulnerability scan". Where two parts meet:

- A known vulnerability (a CVE, PYSEC or GHSA ID) in a dependency or in the code is the part of the check "Vulnerability scan": file none. A dependency's version range, its pin and how it is installed are your part.
- The kind of data that the App holds, and its data class, are the part of the check "Purpose and data": file none. Who can read that data through the App is your part.

When a call fails or is denied, go on with the steps that don't need its answer. Name the call and Domino's answer under "What this check could not check" (in the doc, or in the result when the doc is already pushed). Try a failed call again at most once.

## 1. Read the bundle and its policy

- `domino_get_bundle(bundleId)`: the bundle's name, its project and its stage.
- `domino_get_policy(bundleId)`: the policy that the bundle follows. In its stage named "Validation", find the evidence item whose name is exactly "Validation: Architecture and access", and keep its `id`: that is your evidenceId.
- In that item's `artifacts`, find each field by its `details.label` and keep its `id`: "Verdict", "Highest severity", "Summary", "Doc location".
- A radio field takes one of its `details.options` as its value: use the option's `value`, exactly.
- The Intake values that the analyst filled: in the stage named "Intake", find the evidence item "Intake", and in its `artifacts` the fields "Purpose", "Users" and "Data class" by `details.label`. Each field's value is its `result.artifactContent`. A field with no `result` is not filled.

The Intake's Users say who must reach the App, and its Data class says how much harm an open route can do. Use them to pick the severity of an access finding. Do not judge the data class itself: that is the part of the check "Purpose and data".

Done when: you have the evidenceId and the four artifact IDs, or you know which of them the policy doesn't have, and you have the three Intake values (or know which ones are not filled).

## 2. Read the App

First, the table of the ways into the App, from this agent's own tool:

- Call `own_route_table` once, yourself (not in a subagent), with `folder`: the folder of the App's Python code, relative to the project folder (the folder of the file that `app.sh` starts; for this App, `case_server`). It parses the code and never runs it. Its description gives its rules.
- Its result has one row for each way into the App, each MCP tool and each custom route: its `kind`, `method` and `path`, the handler with its `file` and `line`, `reads_identity` and `changes_state` (with their evidence, `identity_at` and `changes_at`). Keep the rows: `route-reviewer` reviews them (step 3), and the doc's route table comes from them (step 5).
- Read the handler of each row at its file and line, to find who can call it and what it changes. A `changes_state` of `false` means only that the tool's rule found no write: check it in the code.
- Each item of the tool's `not_read` (a file that is not valid Python, a decorator that the tool does not know) goes under "What this check could not check".
- When `own_route_table` fails (an exception, or a text that starts with `timeout:`), do not call it again. Read the routes and the tools from the code yourself, as below, and name the failed call and its answer under "What this check could not check". This alone does not make the Verdict `could not check`: the check still does its work.

Then read the App's code and its start script in the project folder: `README.md`, `app.sh`, each file that `app.sh` starts or installs, each file of code that they import, and each requirements file. Find:

- the tech stack: the language, the frameworks, the server and the storage;
- the design: the entry point, the parts and how they connect, the routes or tools, and where the state is;
- who can call each route or tool, and what it changes: who can open the App (its Domino access setting decides it), and each access check in the code, or that there is none;
- which identity each write records: the header or the value that the code reads (for example `domino-username`), and what it records when there is none;
- each dependency, with its version or range, how it is pinned (an exact version, a range, or none), and how and when it is installed: from a requirements file, by the start script from PyPI each time the App starts, or already in the Domino Environment.

Done when: you have the rows of `own_route_table` (or the answer of its failed call), and each fact for the doc's sections from "Tech stack" to "Dependencies" has a file (and a line, where it is code) as its evidence.

## 3. Review the routes with route-reviewer

Hand the route table to the custom subagent `route-reviewer`, once: one call of the `task` tool, with `subagent_type` `route-reviewer`, `description` `Review the routes`, and this `prompt`, with each `<...>` filled:

```
Users: <the Intake's Users, or: not filled>
Data class: <the Intake's Data class, or: not filled>
Access rules:
<the access rules below, as they are>
Route table:
<the result of own_route_table, as JSON, exactly as the tool gave it>
```

The access rules:

1. Who can open the App is its Domino access setting, which the code does not show. A route or a tool with no access check in the code: anyone who can open the App can call it.
2. An access check is code in the handler, or in a function that it calls, that refuses a caller. Code that only reads the `domino-username` header to record it is not an access check.
3. A route or a tool that changes state with no access check: anyone who can open the App can make that change.
4. Each write must record who made it, from the `domino-username` header. A write that records no identity (for example "no identity" when the header is missing) is a problem.
5. The severity of a problem: the scale of `governance/README.md` (S0 to S3) with its examples for this check. The Intake's Users say who must reach the App, and its Data class says how much harm an open route can do.
6. Judge only access: a known vulnerability is the part of the check "Vulnerability scan", and the data class is the part of the check "Purpose and data".

Its answer is one JSON object in a json block: in `routes`, for each route its `method` and `path`, `who_can_call`, `what_it_changes`, `problem`, `severity`, `severity_reason` and `evidence` (each a file and line); and in `not_reviewed`, what it could not review. Keep its verdicts for steps 4 and 5. It only reads, and it files nothing: you make each write of the checklist.

- A usable answer has a verdict for each row of the table (by its `method` and `path`). For a row with no verdict, and for each item of `not_reviewed`, judge the route yourself, with the access rules, and name it under "What this check could not check".
- When the `task` call fails, or `route-reviewer` gives no usable answer (no json block, or no verdict for any row), do not call it again: judge the routes yourself, with the access rules and the facts of step 2, and name the failed step and its answer under "What this check could not check". This alone does not make the Verdict `could not check`: the check still does its work.
- When `own_route_table` failed (step 2), there is no table to hand: skip the `task` call, judge the routes and the tools that you found in the code yourself, with the access rules, and say under "What this check could not check" that the review did not run.

Done when: you have a verdict for each route and each tool, from the review or from your own judgment, and you know which step failed, if one did.

## 4. Sort what you found

For each problem in your part, decide: a real finding or a false hit.

- Each route problem of the review is an input, and you decide: check its verdict against the handler at its file and line, then sort it with the rules below, as you sort each other problem.
- A real finding gets a severity on the scale of `governance/README.md` (S0, S1, S2 or S3: use its examples for this check), a name `[Architecture and access] <what> in <where>`, its evidence (the file and line, and the code) and a fix. `<where>` is a route, a file or a dependency.
- A false hit is a thing that looked like a problem and is not one. It gets the reason from the code: what the code really does, or why the App needs it. False hits never count, and you file no false hit.

Then pick two of the evidence values, with the rules of `governance/README.md`:

- Highest severity: the highest severity of your real findings, `S0` to `S3`, or `none` when you have no real finding.
- Verdict: `do not approve` when at least one real finding is S0 or S1. `approve` when the highest severity is S2, S3 or `none`. `could not check` when the check could not do its work (for example you could not read the App's code, or Domino denied `domino_get_policy`): this comes before the other two. The verdict's reason names the findings that decide it.

Done when: each problem is a real finding or a false hit, each real finding has a severity and a name, each false hit has a reason, and you have the Verdict and the Highest severity.

## 5. Write the doc

- Copy `governance/validation-doc.md` to `docs/validation/architecture-and-access-<bundleId>.md` in the project folder.
- Keep the shared top part (from the title to "What this check could not check") and only your middle part, `## Architecture and access`. Delete the other two middle parts, `## Purpose and data` and `## Vulnerability scan`, with all their text.
- Replace each `{{field}}` with its text. Keep every heading of your parts, in its order. Delete every comment (`<!-- ... -->`).
- `app`: the App's name. `check`: `Architecture and access`. `bundle_id`: the bundle ID. `written_at`: the time now, from `date -u '+%Y-%m-%d %H:%M'`.
- `app_and_version`: the App's name, its repository, and the commit that you read (`git rev-parse HEAD` in the project folder).
- `verdict`, `highest_severity` and `summary`: the values of step 4. The summary is three to five sentences: the verdict's reason, and each real finding by its name and its severity.
- `doc_location`: the doc is written before its push, so name only the task branch and the file, with no commit: `agent/<task key>, docs/validation/architecture-and-access-<bundleId>.md`.
- `could_not_check`: each limit of this check. Always: the commit of the App version under review (the task reads the project's default branch, not the version's commit), and what only the running App shows (the Apps proxy, the identity headers, who can open the App). Also each failed or denied call, each item of the tool's `not_read`, and a review of `route-reviewer` with no usable answer (or each row that it did not review).
- `tech_stack`, `architecture`, `access` and `dependencies`: the facts of step 2, with their evidence. `dependencies` is a table.
- In the doc's Architecture section, add a table of each route: method, path, who can call it, what it changes.
- The route table has one line for each row of `own_route_table`, with its `method` and `path` exactly as the tool gives them. When the call failed, it has the routes and the tools that you found in the code.
- The route table takes who can call it and what it changes from the review of `route-reviewer` (step 3), as you checked them in step 4. For a row that it did not review, it takes your own judgment.
- `real_findings`: the table of the real findings, with the same names and severities that you file. `false_hits`: the table of the false hits, with their reasons.

Done when: the file has no `{{` and no `<!--` left, it has only the top part and your middle part, and each section has its text.

## 6. Push the doc

- `domino_git_push(message="Validation doc of bundle <bundleId> (Architecture and access)")` commits the doc to the task branch and pushes it. Its answer is JSON: keep `ok`, `branch`, `commit` and `dryRun`.

Done when: you have the branch and the commit, and you know whether `ok` is true and whether `dryRun` is true.

## 7. Attach the doc

- Only when the push answered `ok` true and `dryRun` false: `domino_write_bundle_attachment(bundleId, type="Report", identifier={"filename": "docs/validation/architecture-and-access-<bundleId>.md", "commit": <the push's commit>, "source": "GBP", "branch": <the push's branch>})`.
- When `dryRun` is true, the commit is not on the remote: attach nothing. Say under could not check in the result: "The push was a dry run, so the doc is not in the repo and not attached to the bundle".
- When `ok` is false, the push failed and the doc is not in the repo either: attach nothing, and say why under could not check in the result (with Domino's answer).

Done when: the bundle has the Report attachment, or the result will say why it has none.

## 8. File the real findings

For each real finding of the doc: `domino_write_governance_finding(bundleId, name="[Architecture and access] <what> in <where>", severity="S0" to "S3", description=<the evidence, why it matters, the fix, and the doc's location>)`. Use the name and the severity of the doc's table. File only the findings of your part, and file no false hit. You file them yourself: `route-reviewer` files nothing.

Done when: each real finding of the doc is filed once.

## 9. Fill your evidence item

Fill only your own evidence item, "Validation: Architecture and access": `domino_write_policy_result(bundleId, evidenceId=<step 1>, content={<Verdict ID>: <the verdict>, <Highest severity ID>: <the highest severity>, <Summary ID>: <the summary>, <Doc location ID>: <the doc location>})`. The first three values are the same as in the doc.

The doc location is one line: `<branch> at <commit>, docs/validation/architecture-and-access-<bundleId>.md`, with the push's branch and commit. When the doc is not in the repo: `Not in the repo: <why>. The doc is in the task's result.`

Done when: the answer's `results` show your four values for your evidenceId.

## 10. Report the result

Call `domino_report_result(summary)`, once, last. The summary starts with these four lines, each on its own line, in this order: one of the values, the summary on one line, and the same doc location as in step 9. They are plain text, with no Markdown on those lines.

```
Verdict: approve | do not approve | could not check
Highest severity: S0 | S1 | S2 | S3 | none
Summary: <the summary, on one line>
Doc location: <the doc location>
```

Then: the real findings (name and severity), the false hits (what, and the reason), and "Could not check:" with each limit and each failed or denied call. When the doc is not in the repo, add the whole doc after them, so that the approver can read it.

Done when: `domino_report_result` answered "Recorded".
