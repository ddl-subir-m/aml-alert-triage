# Check 2: Architecture and access

One of the three checks of the App validation demo (domino-agent-service spec #388, Implementation Decision 9). It is a registered
agent (opencode), "Architecture and access", and this folder is its definition: `domino-agent deploy` registers it
from git (domino-agent-service ADR 0037). When an analyst moves an App's governance bundle to the Validation stage of the App
deployment policy, its event subscription starts a task. The task checks the App's architecture and access.
It fills only its own evidence item, "Validation: Architecture and access". All the data is fake.

It is the folder validator of spec #260 (the tag `app-validation-two-ways` keeps it), narrowed to its part, as below.
It runs no scan and no Job (Run a Job is off): known vulnerabilities are the part of the check "Vulnerability scan".
The shared rules of the three checks (the evidence fields, the verdict rule, the severity scale, the finding names, the result and the
doc template) are on [governance/README.md](../README.md).

| File | What it holds | Deployed |
|---|---|---|
| `definition.md` | The settings, as YAML between two `---` lines. Each field is on domino-agent-service's reference page, `docs/definition-file.md`. | Yes |
| `instructions.md` | The instructions: the check's rules. They become the agent's system prompt. | Yes |
| `skills/architecture-and-access/SKILL.md` | The checklist, an own skill: the steps from the bundle to the filled evidence item, with the tool of each step. | Yes |
| `subscriptions/bundle-enters-validation.md` | The event subscription: its event and filter on top, its instruction below them. The file name is its name. | Yes |
| `tools/route_table.py` | The own tool `route_table`: the table of the ways into the App, from the App's code. The agent sees it as `own_route_table`. | Yes |
| `test_route_table.py` | The own tool's unit test. It is next to `definition.md`, not in `tools/`, so deploy does not upload it. | No |
| `README.md` | This page. | No |

The agent's title, "Architecture and access", is the check's name in `governance/checks.json`. The scripted check "Validation
status" finds the check's task by it.

## What a task does

The checklist's steps, in order:

1. It reads the bundle and its policy (`domino_get_bundle`, `domino_get_policy`). It finds its evidence item by its name, and each
   field (Verdict, Highest severity, Summary, Doc location) by its label.
   It reads the Intake values that the analyst filled with `domino_get_policy`: each filled field has its value in
   `result.artifactContent`. The Intake's Users and Data class help it pick the severity of an access finding. It does not judge the data class.
2. It calls its own tool `own_route_table` once, for the table of the App's routes and MCP tools (below, "Its own tool"). Then it
   reads the App's code, its start script and its requirements. It finds who can call each route and what it changes, which
   identity each write records, the tech stack, the design, and each dependency with how it is pinned and installed.
3. It sorts each problem into a real finding (with a severity, S0 to S3) or a false hit (with the reason). Then it picks the Verdict
   and the Highest severity by the shared rules.
4. It writes the doc from `governance/validation-doc.md`: the shared top part and its own middle part, "Architecture and access".
   The doc's file on the task branch is `docs/validation/architecture-and-access-<bundleId>.md`. The route table of its
   Architecture section comes from the rows of `own_route_table`.
5. It commits and pushes the doc to its task branch, `agent/<task key>` (`domino_git_push`).
6. It attaches the doc to the bundle: a `Report` from `GBP`, with the task branch and the push's commit
   (`domino_write_bundle_attachment`).
7. It files each real finding of its part, named `[Architecture and access] <what> in <where>` (`domino_write_governance_finding`).
8. It fills its own evidence item (`domino_write_policy_result`).
9. Its result (`domino_report_result`) starts with four lines: `Verdict: ...`, `Highest severity: ...`, `Summary: ...` and
   `Doc location: ...`. The scripted check of the policy (`governance/validation_status.py`) shows them to the approver.

It files findings only in its own part. A known vulnerability (a CVE, PYSEC or GHSA ID) is the part of the check "Vulnerability
scan", and the data class is the part of the check "Purpose and data": it files none for them.

Where it can't do the whole job, it says so under "What this check could not check" (in the doc and in the result):

- **A dry-run push.** When the platform App pushes in dry-run mode, the commit is not on the remote. The check then attaches nothing,
  its Doc location says "Not in the repo", and its result holds the whole doc.
- **A failed push.** When the push fails (`ok` false), the doc is not in the repo either. The check attaches nothing, and says why.
- **The App version's commit.** An event task reads the demo project's default branch, not the commit of the App version under
  review.
- **What only the running App shows.** The Apps proxy, the identity headers, and who can open the App (its Domino access setting).

## Its own tool

`tools/route_table.py` is the agent's own tool `route_table`: a Python function with `@tool` from `domino_agent`
(domino-agent-service's `docs/write-an-agent-folder.md`, "Your own tools"). The agent sees it as `own_route_table`. It uses the
standard library only (`ast`): it parses the App's code, and never imports or runs it. `definition.md` has no list of own tools:
the folder `tools/` is the switch.

- Its argument, `folder`: the folder of the App's Python code, relative to the project folder (for this App, `case_server`).
- Its result: `files` (the files that it read), `rows` and `not_read`. For this App it is about 2 KB, well under the 51 KB of a
  result that the model sees.
- Each row is one way into the App: each MCP tool (`@mcp.tool`, a POST to the MCP endpoint, with the path
  `/mcp (tool: <name>)`) and each custom route (`@mcp.custom_route`). A row has the kind, the method, the path, the handler with
  its file and line, `reads_identity` and `changes_state`, with the file and line of the evidence (`identity_at`, `changes_at`).
- `reads_identity`: the handler, or a function of the same file that it calls, has the text `domino-username` (the header with
  the caller's identity).
- `changes_state`: the handler, or a function of the App's code that it calls, has a write: a SQL text that writes, `open` to
  write, a call that writes a file or a folder, or a `global` statement. The tool's docstring (its description for the model) has
  the full rule. `false` means only that the rule found no write.
- `not_read`: each file that is not valid Python, and each decorator that the tool does not know. The doc names each one under
  "What this check could not check".

On the App's code of `main`, it gives 5 MCP tools (`get_alert`, `get_customer_profile`, `get_transactions`, `close_alert`,
`escalate_to_sar`) and 2 custom routes (`POST /reset`, `GET /`). `close_alert` and `escalate_to_sar` read the identity and change
state. `POST /reset` reads no identity and changes state. `GET /` and the three `get_` tools change nothing.

In each task, the main agent calls it once, itself, in step 2 of the checklist, and the doc's route table comes from its rows. When
the call fails (an exception or a timeout), the agent reads the routes from the code, and names the failed call under "What this
check could not check". That alone does not make the Verdict `could not check`. The task page shows the call with the mark "own
tool", its argument and its result, and the Activity log has a row for it, `own_route_table`.

### Its unit test

`test_route_table.py` calls the tool as a plain function: `@tool` gives back the function as it is. It needs the `domino-agent`
package (`pip install domino-agent`), or a domino-agent-service checkout on `PYTHONPATH`: no agent service and no network. Run it in
this folder:

```
cd governance/check-architecture-and-access
python -m unittest
```

It reads the App's code (on `main`: the 5 MCP tools and the 2 custom routes, each with its handler, file and line; on the demo
branch, also exactly the planted `POST /upload`, and no other row), a sample of the demo branch's `POST /upload` (no identity,
changes nothing), and small sample files: a handler that reads the identity through a helper, a decorator that the tool does not
know, a file that is not valid Python, and the writes of the rule.

The run writes `__pycache__/`, and the repo's `.gitignore` ignores it. Else deploy refuses the folder, because it has changes that
are not committed.

## Its subscription

`subscriptions/bundle-enters-validation.md` is the event subscription "Bundle enters Validation" of the three checks' form. Its name
in the agent service is the file name, `bundle-enters-validation`. The fields are on domino-agent-service's reference page,
`docs/trigger-files.md`.
`domino-agent deploy`, 0.4.0 or later, makes the subscription from its file (ADR 0049), and changes or removes it at each deploy.
An older command (before 0.4.0) sends no trigger file: the agent gets no subscription, and a first deploy gives no notice of it.

- Its event is `governance.bundle.stage_changed`, and its filter is `toStage` equals `Validation` and `project.name` equals
  `aml-validation-demo`.
- The repo is public, so the filter names the demo project by its name, not by its Domino ID.
  Any project with that name, `aml-validation-demo`, matches on the deployment, also one in another person's account (the event
  names no project owner).
- Its title template is `Architecture and access: bundle {{bundle.id}}`. Its instruction template, below the settings, names the
  bundle ID, the skill and only its own evidence item.
- The file name is its identity. A changed file keeps the subscription's ID, its on or off state and its history. In the App, a person
  can turn it off or on and send a test event, but can't change or delete it: change the file, commit, and deploy.
- A subscription of this agent made with the API before (the first form of spec #388): delete it after the deploy
  (`DELETE /api/triggers/{id}`, as an editor), else each stage move starts two tasks.

## Before it can run

The folder holds the agent's behaviour and its subscription, and no user names: no service account and no sharing. The owner adds
these once, after the first deploy. A later deploy keeps them.

| What the owner adds | How | Without it |
|---|---|---|
| The service account and its token | In the wizard's Identity & sharing step: pick the service account, and add its token. Store a new token before the old one expires. | The deploy says "Can't run yet", and each stage move starts no task: the agent can't run yet. |
| The service account's rights | The service account is a Contributor of the demo project, has an LLM Gateway grant on the model alias `google/gemini-3.8-flash`, and may submit results, attach files and file findings on the bundle (a governance role). | Domino refuses the Job, the model calls or the writes on the bundle. |
| The service account's Git credential | A Git credential for github.com in the service account's Domino account, whose token has write access to this repo (a fine-grained GitHub token: Contents, Read and write, on this repo). Test it with a `git push --dry-run`: the repo API's `permissions.push` is the account's role, not the token's grant. Then the service account maps it to the project's repository, with its own token: `PUT /v4/projects/{projectId}/repository/{repoId}/credentialMapping` `{"credentialId": ...}`. Domino keeps that link for each user on its own. | With no mapping, Domino gives the Job no Git credential, and the push fails ("could not read Username"). With a token that may not write, GitHub refuses the push (403). With a private repo, Domino can't clone it either. |
| The analyst | Share the agent, as a user, with each analyst who moves the stage. | The stage move starts no task: "<analyst> is not allowed to use agent ...". |
| The approver | Share the agent with the approver as an owner or an editor. | The scripted check shows "not started": a user of the agent can't read its tasks. |
| The poller | The platform App (the smoke App) has the project setting `SMOKE_AUDIT_POLL_SECONDS` (10 in the demo). | No stage move reaches the agent. |
| Real pushes | The platform App has the project setting `SMOKE_PUSH_DRY_RUN=0`. | Each push is a dry run: the doc is not in the repo, and the check doesn't attach it. |
| The shared rules | The demo project's default branch has `governance/README.md` and `governance/validation-doc.md` (the demo branch is rebased on main). | The checklist has no shared rules, and the doc has no template. |

The access rows are in `definition.md`. An edit in the wizard is a commit to the agent's branch, so keep these values there too:

| Row | Value | Why |
|---|---|---|
| Project files | Read & write | The doc goes in the project's files, and the push needs write. A bundle of the task's project that is not on the task falls under this row. |
| Project datasets | No access | The check reads no dataset. |
| Other resources attached to the task | Read & write | The event's bundle is attached to the task, so this row decides it. Its writes (the attachment, the findings, the evidence) need Read & write: with Read only, the gateway denies each one. |
| Resources not attached to the task | No access | The check works only on the task's project and the event's bundle. |

The tools: Run a Job off (no scan, so the agent has no `domino_run_job`), Git push on (the doc leaves the Job only through the push),
no subagents. Its own tool, `own_route_table`, comes from the folder `tools/`, not from a setting. `on-error: fail`: nobody answers an event task, so a denied call ends the task with a report, and never waits for a
person.

## Deploy it

In a Domino Workspace in this repo, on a commit (the folder must have no changes that aren't committed), with the `domino-agent`
command (`pip install domino-agent`). On a laptop, also set `DOMINO_TOKEN`.

```
export AGENT_SERVICE_URL=https://<apps host>/apps-internal/<App ID>      # the platform App's URL, as Domino gives it
domino-agent deploy --dry-run governance/check-architecture-and-access
domino-agent deploy governance/check-architecture-and-access
```

The first deploy prints `Created Architecture and access (agt_...)`, a line for the subscription, and a notice: it can't run yet,
because it acts as a service account and none is chosen. Then add what the table above lists. The subscription's line:

```
  Trigger: added subscription bundle-enters-validation (subscriptions/bundle-enters-validation.md)
```

## The check

```
python tests/check_architecture_and_access.py
AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_architecture_and_access.py
```

One line per case, with a non-zero exit code on any failure. Its own part uses the stdlib only. It reads the names from
`governance/checks.json` (the check's name, its evidence item, the field labels, the verdicts and the severities) and the doc's
fields from `governance/validation-doc.md`. It checks the files that deploy uploads (the tool file, and not its unit test or this
page), the settings of `definition.md`, the checklist's rules (no scan step, one call of `own_route_table`) and the order of its
tools, the instructions' rules, the own tool's file (the standard library only), the subscription's file (its filter on the demo
project's name), no Domino host or ID in the folder, and this page.

With the `domino-agent` package or `AGENT_SERVICE_REPO`, it runs the own tool's unit test (else a `SKIP:` line). With
`AGENT_SERVICE_REPO` (a domino-agent-service checkout, any OS), it also checks each tool name against the service's gateway and relay,
and the service's own tool reader reads the tool file. The rest needs Linux: it starts the agent service with a fake Domino (the
service's seam helper, `tests/agent_folder_seam.py`), commits the folder in a temporary clone, and then:

- `domino-agent deploy --dry-run` passes the service's folder rules, and its `Changed:` line names `tools/route_table.py`.
  `deploy` registers the agent: its settings, its skill, its own tool and "can't run yet". It adds the subscription from its file,
  in the temporary clone with the seam's project name (`local-proj`) in place of `aml-validation-demo`: the fake Domino has only that
  project.
- A stage move starts no task before the token, nor for an analyst who may not use the agent. After both, it starts one task as
  the service account, with the bundle ID in its title, and its Job.
- The Job's spec has the skill, the own tool (its file, and `own_*` allowed for the main agent), the access rows, Run a Job off,
  Git push on, the permissions and the limits. The gateway's decisions
  for this task allow the attachment, the findings and the evidence on the event's bundle and `git_push`, and deny `run_job` and
  a project dataset.
- A stage move to another stage, or in another project, starts nothing. A second deploy of the same commit keeps the subscription.

On a Mac, run it with Docker, in the image of the service's checks (in domino-agent-service, `./tests/linux_checks.sh` builds it
once; `docker images domino-agent-service-checks` lists it), from the root of this repo:

```
docker run --rm -v /path/to/domino-agent-service:/service:ro -v "$PWD:/aml:ro" -w /aml -e AGENT_SERVICE_REPO=/service \
  -e PYTHONDONTWRITEBYTECODE=1 domino-agent-service-checks:<tag> python tests/check_architecture_and_access.py
```

Nothing calls a Domino host. The live run is domino-agent-service #397.
