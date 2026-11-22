---
name: architecture-and-access
description: The checklist of the check Architecture and access, from the governance bundle to the filled evidence item. Use it in every task of this agent.
---
# Check the architecture and access of the App of a governance bundle

The task's instruction names the bundle ID (`bundleId` below). Do the steps in order. A step is done when its "Done when" line is true. You are the check "Architecture and access", one of the three checks of the Validation stage. Your part: all access (who can call each route or tool, what it changes, and which identity each write records), the tech stack, the design, and the dependencies with how they are pinned and installed. You run no scan and start no Job.

The project folder (its path is in the operating rules) holds the shared parts of the three checks. Read `governance/rules.md` first, and follow it in each step: `governance/rules.md` has the rules that the three checks share (the evidence fields and the verdict rule, could not check, also for a failed or denied call, the doc location, the severity scale S0 to S3 with its examples for each check, the finding names, the doc's template and the result), and `governance/validation-doc.md` is the template of the doc.

File findings only in your own part, never in the parts of the other two checks, "Purpose and data" and "Vulnerability scan". Where two parts meet:

- A known vulnerability (a CVE, PYSEC or GHSA ID) in a dependency or in the code is the part of the check "Vulnerability scan": file none. A dependency's version range, its pin and how it is installed are your part.
- The kind of data that the App holds, and its data class, are the part of the check "Purpose and data": file none. Who can read that data through the App is your part.

## 1. Read the bundle and the Intake

- `domino_get_bundle(bundleId)`: the bundle's name, its project and its stage.
- `domino_get_policy(bundleId)`: the policy that the bundle follows, with the values that the analyst filled. In its stage named "Intake", find the evidence item "Intake", and in its `artifacts` the fields "Purpose", "Users" and "Data class" by `details.label`. Each field's value is its `result.artifactContent`. A field with no `result` is not filled. The Users and the Data class help you pick the severity of an access finding (access rule 5, step 3).

Done when: you have the three Intake values, or you know which ones are not filled.

## 2. Read the App

- Call the own tool `own_route_table` once, yourself (not in a subagent), with `folder`: the folder of the App's Python code, relative to the project folder (the folder of the file that `app.sh` starts; for this App, `case_server`). It parses the code and never runs it. Its description gives its rules.
- Its result has one row for each way into the App, each MCP tool and each custom route: its `kind`, `method` and `path`, the handler with its `file` and `line`, `reads_identity` and `changes_state` (with their evidence, `identity_at` and `changes_at`). Keep the rows: `route-reviewer` reviews them (step 3), and the doc's route table comes from them (step 4). Read the handler of each row at its file and line, to find who can call it and what it changes. A `changes_state` of `false` means only that the tool's rule found no write: check it in the code.
- Each item of the tool's `not_read` (a file that is not valid Python, a decorator that the tool does not know) goes under "What this check could not check".
- When `own_route_table` fails (an exception, or a text that starts with `timeout:`), do not call it again. Read the routes and the tools from the code yourself, and name the failed call and its answer under "What this check could not check". This alone does not make the Verdict `could not check`: the check still does its work.

Then read the App's code and its start script in the project folder: `README.md`, `app.sh`, each file that `app.sh` starts or installs, each file of code that they import, and each requirements file. Find:

- the tech stack (the language, the frameworks, the server and the storage), and the design (the entry point, the parts and how they connect, the routes or tools, and where the state is);
- who can call each route or tool, and what it changes (who can open the App, which its Domino access setting decides, and each access check in the code, or that there is none), and which identity each write records (the header or the value that the code reads, for example `domino-username`, and what it records when there is none);
- each dependency, with its version or range, how it is pinned (an exact version, a range, or none), and how and when it is installed: from a requirements file, by the start script from PyPI each time the App starts, or already in the Domino Environment.

Done when: you have the rows of `own_route_table` (or the answer of its failed call), and each fact for the doc's sections from "Tech stack" to "Dependencies" has a file (and a line, where it is code) as its evidence.

## 3. Review the routes with route-reviewer

Give the route table to the custom subagent `route-reviewer`, once. Use one call of the `task` tool, with `subagent_type` `route-reviewer`, `description` `Review the routes`, and this `prompt`, with each `<...>` filled:

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
5. The severity of a problem: the scale of `governance/rules.md` (S0 to S3) with its examples for this check. The Intake's Users say who must reach the App, and its Data class says how much harm an open route can do.
6. Judge only access: a known vulnerability is the part of the check "Vulnerability scan", and the data class is the part of the check "Purpose and data".

- Its answer is one JSON object in a json block: a verdict for each route in `routes` (its `method` and `path`, who can call it, what it changes, the problem, its severity and its evidence), and what it could not review in `not_reviewed`. It only reads, and it files nothing: you make each write of the checklist. A usable answer has a verdict for each row of the table (by its `method` and `path`). For a row with no verdict, and for each item of `not_reviewed`, judge the route yourself, with the access rules, and name it under "What this check could not check".
- When the `task` call fails, or `route-reviewer` gives no usable answer (no json block, or no verdict for any row), do not call it again. When `own_route_table` failed (step 2), skip the `task` call: there is no table to give. Then judge the routes yourself, with the access rules and the facts of step 2, and name the failed step and its answer under "What this check could not check". This alone does not make the Verdict `could not check`: the check still does its work.

Done when: you have a verdict for each route and each tool, from the review or from your own judgment, and you know which step failed, if one did.

## 4. Write the doc

For each problem in your part, decide: a real finding or a false hit. Each route problem of the review is an input, and you decide: check its verdict against the handler at its file and line first.

- A real finding gets a severity on the scale of `governance/rules.md` (use its examples for this check), a name by its finding names (`<where>` is a route, a file or a dependency), its evidence (the file and line, and the code) and a fix. A false hit is a thing that looked like a problem and is not one: it gets the reason from the code (what the code really does, or why the App needs it), and you file no false hit.
- Pick the Highest severity and the Verdict by `governance/rules.md` ("The evidence fields"), with your real findings. This check can't do its work, so the Verdict is `could not check`, when you could not read the App's code, or Domino denied `domino_get_policy`.

Then copy `governance/validation-doc.md` to `docs/validation/architecture-and-access-<bundleId>.md` in the project folder, and trim it to this check as `governance/rules.md` says ("The doc's template"): your middle part is `## Architecture and access`. Fill it:

- `app`: the App's name. `check`: `Architecture and access`. `bundle_id`: the bundle ID. `written_at`: the time now, from `date -u '+%Y-%m-%d %H:%M'`. `app_and_version`: the App's name, its repository, and the commit that you read (`git rev-parse HEAD` in the project folder).
- `verdict`, `highest_severity` and `summary`: your values, by the rules of `governance/rules.md` ("The evidence fields"). `doc_location`: the doc's own Doc location (`governance/rules.md`, "The doc location"), with the file `docs/validation/architecture-and-access-<bundleId>.md`.
- `could_not_check`: each limit of this check. Always: the commit of the App version under review (the task reads the project's default branch, not the version's commit), and what only the running App shows (the Apps proxy, the identity headers, who can open the App). Also each failed or denied call, each item of the tool's `not_read`, and a review of `route-reviewer` with no usable answer (or each row that it did not review).
- `tech_stack`, `architecture`, `access` and `dependencies`: the facts of step 2, with their evidence. `dependencies` is a table.
- In the doc's Architecture section, add a table of each route: method, path, who can call it, what it changes. The route table has one line for each row of `own_route_table`, with its `method` and `path` exactly as the tool gives them (when the call failed: the routes and the tools that you found in the code). It takes who can call it and what it changes from the review of `route-reviewer` (step 3), as you checked them, and your own judgment for a row that it did not review.
- `real_findings`: the table of the real findings, with the same names and severities that you file. `false_hits`: the table of the false hits, with their reasons.

Done when: each problem is a real finding (with a severity and a name) or a false hit (with a reason), and the file has no `{{` and no `<!--` left, it has only the top part and your middle part, and each section has its text.

## 5. Push and attach the doc

- `domino_git_push(message="Validation doc of bundle <bundleId> (Architecture and access)")` commits the doc to the task branch and pushes it. Its answer is JSON: keep `ok`, `branch`, `commit` and `dryRun`.
- Only when the push answered `ok` true and `dryRun` false: `domino_write_bundle_attachment(bundleId, type="Report", identifier={"filename": "docs/validation/architecture-and-access-<bundleId>.md", "commit": <the push's commit>, "source": "GBP", "branch": <the push's branch>})`.
- When `dryRun` is true, the commit is not on the remote: attach nothing, and say under could not check in the result: "The push was a dry run, so the doc is not in the repo and not attached to the bundle". When `ok` is false, the push failed and the doc is not in the repo either: attach nothing, and say why under could not check in the result (with Domino's answer).

Done when: the bundle has the Report attachment, or the result will say why it has none.

## 6. File the real findings

For each real finding of the doc: `domino_write_governance_finding(bundleId, name=<its name>, severity=<its severity>, description=<the evidence, why it matters, the fix, and the doc's location>)`. Use the name and the severity of the doc's table. File only the findings of your part, and file no false hit. You file them yourself: `route-reviewer` files nothing.

Done when: each real finding of the doc is filed once.

## 7. Fill your evidence item

Fill only your own evidence item, by its name and the labels of its fields: `domino_write_policy_result(bundleId, evidenceName="Validation: Architecture and access", content={"Verdict": <the verdict>, "Highest severity": <the highest severity>, "Summary": <the summary>, "Doc location": <the doc location>})`. The gateway finds their IDs in the bundle's policy. The first three values are the same as in the doc. The doc location is the line of `governance/rules.md` ("The doc location"), with the push's branch and commit and the file `docs/validation/architecture-and-access-<bundleId>.md`.

Done when: the answer's `results` show your four values.

## 8. Report the result

Call `domino_report_result(summary)`, once, last. The summary is the result of `governance/rules.md` ("The result"): its four lines first, with the same values as your evidence item (step 7), then each part that it names after them.

Done when: `domino_report_result` answered "Recorded".
