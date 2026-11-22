---
name: architecture-and-access
description: The checklist of the check Architecture and access for a wizard agent, from the governance bundle to the filled evidence item. It reads the routes with the shell and gives their review to the built-in subagent. Use it in every task that validates a bundle.
---
# Check the architecture and access of the App of a governance bundle

The task's instruction names the bundle ID (`bundleId` below). Do the steps in order. A step is done when its "Done when" line is true. This is the check "Architecture and access", one of the three checks of the Validation stage. Its part: all access (who can call each route or tool, what it changes, and which identity each write records), the tech stack, the design, and the dependencies with how they are pinned and installed. It runs no scan and starts no Job.

The project folder (its path is in the operating rules) holds the shared parts of the three checks. Read `governance/rules.md` first, and follow it in each step. It has the rules that the three checks share: the evidence fields, the verdict rule, could not check (also for a failed or denied call), the doc location, the severity scale S0 to S3 with its examples for each check, the finding names, the doc's template and the result. `governance/validation-doc.md` is the template of the doc.

File findings only in your own part, never in the parts of the other two checks, "Purpose and data" and "Vulnerability scan". Where two parts meet:

- A known vulnerability (a CVE, PYSEC or GHSA ID) in a dependency or in the code is the part of the check "Vulnerability scan": file none. A dependency's version range, its pin and how it is installed are your part.
- The kind of data that the App holds, and its data class, are the part of the check "Purpose and data": file none. Who can read that data through the App is your part.

## 1. Read the bundle and the Intake

- `domino_get_bundle(bundleId)`: the bundle's name, its project and its stage.
- `domino_get_policy(bundleId)`: the policy that the bundle follows, with the values that the analyst filled. In its stage named "Intake", find the evidence item "Intake", and in its `artifacts` the fields "Purpose", "Users" and "Data class" by `details.label`. Each field's value is its `result.artifactContent`. A field with no `result` is not filled. The Users and the Data class help you pick the severity of an access finding (access rule 5, step 3).

Done when: you have the three Intake values, or you know which ones are not filled.

## 2. Read the App and make the route table

Read the code with the shell, with commands that only read (`grep`, `sed -n`, `cat`, `ls`, `git rev-parse`). Run no command that writes a file, installs a package or starts the App. The App's Python code is in the folder of the file that `app.sh` starts (for this App, `case_server`).

- `grep -rn -e 'FastMCP(' -e '\.tool' -e '\.custom_route' -e 'domino-username' case_server` finds the servers, the ways into the App and the identity header. A server is a name that a file binds to `FastMCP(...)`.
- The route table has one row for each `@<server>.tool` and each `@<server>.custom_route(<path>, methods=[...])`. An MCP tool: `kind` `MCP tool`, `method` `POST`, `path` `/mcp (tool: <name>)`, where the name is the decorator's `name`, else the function's name. A custom route: `kind` `route`, its methods in upper case joined by `, `, and its path.
- Each row also has `handler`, `file` and `line` (of the handler's `def`), `reads_identity` with `identity_at` (the handler, or a function that it calls, reads `domino-username`: the file and line), and `changes_state` with `changes_at` (the file and line of the first write in the handler, or in a function of the App's code that it calls). Find a called function with `grep -rn 'def <name>' case_server`.
- A write is a SQL text that starts with INSERT INTO, REPLACE INTO, UPDATE ... SET, DELETE FROM, or CREATE, DROP or ALTER of a table, index, view or trigger; `open` with a mode with w, a, x or +; a call of write_text, write_bytes, mkdir, makedirs, touch, rename, remove, unlink, rmdir or rmtree; or a `global` or `nonlocal` statement. A docstring is not code.
- A file that is not valid Python, a decorator on a handler that you do not know, and a route whose path or methods are not plain values get no row: each one goes under "What this check could not check".

Then read the App's code and its start script in the project folder: `README.md`, `app.sh`, each file that `app.sh` starts or installs, each file of code that they import, and each requirements file. Find:

- the tech stack (the language, the frameworks, the server and the storage), and the design (the entry point, the parts and how they connect, the routes or tools, and where the state is);
- who can call each route or tool, and what it changes (who can open the App, which its Domino access setting decides, and each access check in the code, or that there is none), and which identity each write records (the header or the value that the code reads, for example `domino-username`, and what it records when there is none);
- each dependency, with its version or range, how it is pinned (an exact version, a range, or none), and how and when it is installed: from a requirements file, by the start script from PyPI each time the App starts, or already in the Domino Environment.

Done when: the route table has a row for each way into the App, and each fact for the doc's sections from "Tech stack" to "Dependencies" has a file (and a line, where it is code) as its evidence.

## 3. Review the routes with the built-in subagent

Give the route table to the built-in subagent, once: one call of the `task` tool, with `subagent_type` `general`, `description` `Review the routes`, and this `prompt`, with each `<...>` filled:

```
You review the access of each route of one App, and you give your verdicts back to the main agent. All the data is fake.
You only read. Use only the read, glob, grep and list tools. Run no shell command, call no Domino tool, load no skill, write no file and file no finding: the main agent files the findings.
The project folder is <the path of the project folder>. Each file of the route table is relative to it.
For each row of the route table: read its handler at its file and line, and each function of the App's code that it calls. Find who can call it, with the access rules: who can open the App, and each check in the code that limits the callers, or that there is none. Find what it changes: the state that it writes, or nothing (a changes_state of false means only that no write was found: check it in the code). Find each access problem: a change that any caller can make, a write that records no identity, or data that a caller can read and must not, or none. Give each problem a severity on the scale of governance/rules.md (S0, S1, S2 or S3) with its examples for the check "Architecture and access", or none. The Intake's Users say who must reach the App, and its Data class says how much harm an open route can do. Cite a file and a line for each claim.
Judge only access: give no verdict on a known vulnerability (a CVE, PYSEC or GHSA ID) or on the data class.
Give one verdict for each row, with its method and path exactly as the table has them, in the table's order. A row that you could not review goes in not_reviewed, with why. Your answer is one JSON object in a json block, and no other text:
{"routes": [{"method": "", "path": "", "who_can_call": "", "what_it_changes": "", "problem": "", "severity": "", "severity_reason": "", "evidence": ["<file>:<line>"]}], "not_reviewed": [""]}
Users: <the Intake's Users, or: not filled>
Data class: <the Intake's Data class, or: not filled>
Access rules:
<the access rules below, as they are>
Route table:
<the route table of step 2, as JSON>
```

The access rules:

1. Who can open the App is its Domino access setting, which the code does not show. A route or a tool with no access check in the code: anyone who can open the App can call it.
2. An access check is code in the handler, or in a function that it calls, that refuses a caller. Code that only reads the `domino-username` header to record it is not an access check.
3. A route or a tool that changes state with no access check: anyone who can open the App can make that change.
4. Each write must record who made it, from the `domino-username` header. A write that records no identity (for example "no identity" when the header is missing) is a problem.
5. The severity of a problem: the scale of `governance/rules.md` (S0 to S3) with its examples for this check. The Intake's Users say who must reach the App, and its Data class says how much harm an open route can do.
6. Judge only access: a known vulnerability is the part of the check "Vulnerability scan", and the data class is the part of the check "Purpose and data".

- A usable answer has a verdict for each row of the table (by its `method` and `path`). For a row with no verdict, and for each item of `not_reviewed`, judge the route yourself, with the access rules, and name it under "What this check could not check".
- When the `task` call fails, or the subagent gives no usable answer (no json block, or no verdict for any row), do not call it again. Judge the routes yourself, with the access rules and the facts of step 2, and name the failed step and its answer under "What this check could not check". This alone does not make the Verdict `could not check`: the check still does its work.

Done when: you have a verdict for each route and each tool, from the review or from your own judgment, and you know which step failed, if one did.

## 4. Write the doc

For each problem in your part, decide: a real finding or a false hit. Each route problem of the review is an input, and you decide: check its verdict against the handler at its file and line first.

- A real finding gets a severity on the scale of `governance/rules.md` (use its examples for this check), a name by its finding names (`<where>` is a route, a file or a dependency), its evidence (the file and line, and the code) and a fix. A false hit is a thing that looked like a problem and is not one: it gets the reason from the code, and you file no false hit.
- Pick the Highest severity and the Verdict by `governance/rules.md` ("The evidence fields"), with your real findings. This check can't do its work, so the Verdict is `could not check`, when you could not read the App's code, or Domino denied `domino_get_policy`.

Then copy `governance/validation-doc.md` to `docs/validation/architecture-and-access-<bundleId>.md` in the project folder, and trim it to this check as `governance/rules.md` says ("The doc's template"): your middle part is `## Architecture and access`. Fill it:

- `app`: the App's name. `check`: `Architecture and access`. `bundle_id`: the bundle ID. `written_at`: the time now, from `date -u '+%Y-%m-%d %H:%M'`. `app_and_version`: the App's name, its repository, and the commit that you read (`git rev-parse HEAD` in the project folder).
- `verdict`, `highest_severity` and `summary`: your values, by the rules of `governance/rules.md` ("The evidence fields"). `doc_location`: the doc's own Doc location (`governance/rules.md`, "The doc location"), with the file `docs/validation/architecture-and-access-<bundleId>.md`.
- `could_not_check`: each limit of this check. Always: the commit of the App version under review (the task reads the project's default branch, not the version's commit), and what only the running App shows (the Apps proxy, the identity headers, who can open the App). Also each failed or denied call, each file or decorator of step 2 that has no row, and a review with no usable answer (or each row that it did not review).
- `tech_stack`, `architecture`, `access` and `dependencies`: the facts of step 2, with their evidence. `dependencies` is a table.
- In the doc's Architecture section, add a table of each route: method, path, who can call it, what it changes. It has one line for each row of the route table, with its `method` and `path`, and takes who can call it and what it changes from the review (step 3), as you checked them, and your own judgment for a row that it did not review.
- `real_findings`: the table of the real findings, with the same names and severities that you file. `false_hits`: the table of the false hits, with their reasons.

Done when: each problem is a real finding (with a severity and a name) or a false hit (with a reason), and the file has no `{{` and no `<!--` left, it has only the top part and your middle part, and each section has its text.

## 5. Push and attach the doc

- `domino_git_push(message="Validation doc of bundle <bundleId> (Architecture and access)")` commits the doc to the task branch and pushes it. Its answer is JSON: keep `ok`, `branch`, `commit` and `dryRun`.
- Only when the push answered `ok` true and `dryRun` false: `domino_write_bundle_attachment(bundleId, type="Report", identifier={"filename": "docs/validation/architecture-and-access-<bundleId>.md", "commit": <the push's commit>, "source": "GBP", "branch": <the push's branch>})`.
- When `dryRun` is true, the commit is not on the remote: attach nothing, and say under could not check in the result: "The push was a dry run, so the doc is not in the repo and not attached to the bundle". When `ok` is false, the doc is not in the repo either: attach nothing, and say why under could not check in the result (with Domino's answer).

Done when: the bundle has the Report attachment, or the result will say why it has none.

## 6. File the real findings

For each real finding of the doc: `domino_write_governance_finding(bundleId, name=<its name>, severity=<its severity>, description=<the evidence, why it matters, the fix, and the doc's location>)`. Use the name and the severity of the doc's table. File only the findings of your part, and file no false hit. You file them yourself: the subagent files nothing.

Done when: each real finding of the doc is filed once.

## 7. Fill your evidence item

Fill only your own evidence item, by its name and the labels of its fields: `domino_write_policy_result(bundleId, evidenceName="Validation: Architecture and access", content={"Verdict": <the verdict>, "Highest severity": <the highest severity>, "Summary": <the summary>, "Doc location": <the doc location>})`. The gateway finds their IDs in the bundle's policy. The first three values are the same as in the doc. The doc location is the line of `governance/rules.md` ("The doc location"), with the push's branch and commit and the file `docs/validation/architecture-and-access-<bundleId>.md`.

Done when: the answer's `results` show your four values.

## 8. Keep your part of the result

Your part of the task's result is the result of `governance/rules.md` ("The result") for this check: its four lines first, with the same values as your evidence item (step 7), then each part that it names after them. Do not call `domino_report_result` in this skill: the system prompt says when to report the result, with this part in it.

Done when: you have your part of the result, with its four lines first.
