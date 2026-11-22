# App validation: one wizard agent for the three checks

The App validation demo has three checks, each one built in a different way (governance/README.md, "The three checks"). This
folder shows that a person who writes no code can do the whole validation in the App alone: one wizard agent, `App validation`,
that a person makes and runs only in the App (the Skills library, the wizard and the Triggers tab). One task of it does the work of
the three checks on one bundle and fills the three evidence items (domino-agent-service #529). The rules that the three checks share
are in [governance/rules.md](../rules.md). All the data is fake.

It is a wizard agent: a harness agent (opencode) that a person makes in the agent service App's wizard. A wizard agent can't have
an own tool or a custom subagent, so its skills use what the wizard gives: the shell, the built-in subagent ("Subagents" on) and
"Start Domino jobs" (for `governance/scan.py`). This folder is its reference copy in git, so that it can be made again on a new
deployment. The live script reads the agent back and compares it with this copy.

| File | What it holds |
|---|---|
| `skills/architecture-and-access/SKILL.md` | A store skill: the checklist of the check Architecture and access. It reads the routes with the shell, in place of the own tool `route_table` of `governance/check-architecture-and-access/`, and gives their review to the built-in subagent, with the brief of the custom subagent `route-reviewer` |
| `skills/vulnerability-scan/SKILL.md` | A store skill: the checklist of the check Vulnerability scan, from the steps of `governance/check-vulnerability-scan/`. It runs the scan in a Domino Job, pushes its doc to the task branch and attaches it as a Report. Its schedule part scans again for the bundles in Approval |
| `instructions.md` | The agent's system prompt: the three skills in order, then one result in three parts |
| `agent.json` | The reference settings: the agent as the wizard's Save sends it (`POST /api/agents`), with placeholders, and with no value of a deployment (an ID, the hardware tier). Each key has its row in the steps below. |
| `subscription.json` | The event subscription: the body of `POST /api/agents/{id}/triggers`, as the Triggers tab's form sends it, with the second project's ID as a placeholder |
| `schedule.json` | The weekly re-scan: the body of `POST /api/agents/{id}/triggers` for the schedule |
| `compare.py` | Fills the placeholders, and compares what the App stores with `agent.json`, `subscription.json` and `schedule.json`. Stdlib only |
| `README.md` | This page |

The first skill is the store skill `purpose-and-data` of check 1, as it is: its text is in
`governance/check-purpose-and-data/SKILL.md`, and this agent does not change it.

## What a task does

When the analyst moves the bundle of the second project, `aml-validation-wizard`, to the Validation stage of the policy "App
deployment policy", the subscription starts one task. The task does the three store skills in order, each one to its end:

1. `purpose-and-data`: what the App is for and what data it holds, compared with the Intake answers. Its doc is
   `docs/validation/purpose-and-data-<bundle ID>.md`.
2. `architecture-and-access`: all access, the tech stack, the design and the dependencies. It reads the routes with read-only shell
   commands, and gives the route table to the built-in subagent once (the `task` tool, `subagent_type` `general`), which only reads
   and gives a verdict for each route. Its doc is `docs/validation/architecture-and-access-<bundle ID>.md`.
3. `vulnerability-scan`: known vulnerabilities in the code and the dependencies. It runs `python governance/scan.py` in a Domino Job
   (`domino_run_job`), calls `domino_wait_job` until the Job ends, and reads the summary between its two marker lines
   (governance/README.md, "The scan" and "A failed scan"). Its doc is `docs/validation/vulnerability-scan-<bundle ID>.md`.

Each skill pushes its doc to the task branch `agent/<task key>` (`domino_git_push`) and attaches it to the bundle as a `Report` from
`GBP`, with the task branch and the push's commit. Each one files its real findings, with their names by the finding names of
`governance/rules.md`, and fills its own evidence item by its name: "Validation: Purpose and data", "Validation: Architecture and
access" and "Validation: Vulnerability scan", each with its four fields (Verdict, Highest severity, Summary, Doc location). The
gateway finds their IDs in the bundle's policy, so no skill searches for an ID. Each finding of the Vulnerability scan has the line
`Key: <key>` first in its description, so that a later run finds it again.

At the end, the task calls `domino_report_result` once, with one result in three parts: Purpose and data, Architecture and access,
Vulnerability scan. Each part starts with the line `## <check name>`, then the four lines of `governance/rules.md`, "The result",
for that check. With the demo branch and the Intake's Data class Internal, the task finds the planted S1 of Purpose and data (Data
class Internal for Restricted data) and the planted S0 of the Vulnerability scan (`yaml.full_load`, pyyaml 5.3.1, PYSEC-2021-142).

A task of the schedule names no bundle. It does only the schedule part of the skill `vulnerability-scan`: it scans again, finds the
bundles in the stage Approval of the task's own project (by that project's ID, never a bundle of another project), files each new
finding on them by its key, and fills no evidence item. The main demo's project has a bundle in Approval too: its Monday check fails
when a second agent files a finding there. The gateway also refuses it: with "Resources not attached to the task" set to "No
access", a bundle of another project is not this agent's.

## The placeholders

The repo is public, so the reference files have no user name and no Domino ID. `compare.py` fills these:

| Placeholder | Its value |
|---|---|
| `__SERVICE_ACCOUNT__` | The service account that the agent acts as: the one of the three checks (`agent.json`) |
| `__ANALYST__` | The analyst who moves the bundle's stage (`agent.json`, "People") |
| `__APPROVER__` | The approver (`agent.json`, "Editors") |
| `__PD_SKILL_ID__`, `__PD_SKILL_VERSION__` | The ID and version of the store skill `purpose-and-data`, from `GET /api/skills` (`agent.json`) |
| `__AA_SKILL_ID__`, `__AA_SKILL_VERSION__` | The same for the store skill `architecture-and-access` (`agent.json`) |
| `__VS_SKILL_ID__`, `__VS_SKILL_VERSION__` | The same for the store skill `vulnerability-scan` (`agent.json`) |
| `__WIZARD_PROJECT_ID__` | The ID of the second project, `aml-validation-wizard` (`subscription.json`) |
| `__INSTRUCTIONS__` | The text of `instructions.md`: `compare.py` fills it by itself |

## Before you make it

- **The second project:** `aml-validation-wizard`, a copy of the demo project `aml-validation-demo`: a Git-based project on the same
  repository, with the demo branch of this repo as its default branch. Its own bundle of the App follows the policy "App deployment
  policy", with the Intake filled. The three checks never see its bundles: their subscriptions filter on the demo project. This
  agent's subscription filters on the second project, so it never sees a bundle of the demo project.
- **The service account's rights:** the service account of the three checks is a Contributor of the second project, has an LLM
  Gateway grant on the model alias `google/gemini-3.8-flash`, and may submit results, attach files and file findings on the bundle
  (a governance role).
- **The service account's Git credential:** its Git credential for github.com, whose token has write access to this repo (the
  push). The service account maps it to the second project's repository, with its own token:
  `PUT /v4/projects/{projectId}/repository/{repoId}/credentialMapping` `{"credentialId": ...}`. With no mapping, the push fails, and
  Domino refuses the scan Job.
- **The model:** the wizard lists only the models that you can call ("Listed with your access"). Make sure that you can call
  `google/gemini-3.8-flash` before you start. Not `sonnet`: Anthropic's cyber safeguards refuse this work (domino-agent-service
  #270).
- **The store skills must exist first:** the wizard's step 3 lists only the skills of the store. `purpose-and-data` is there from
  check 1 (its README, "Before you make it"): do not change it. Add the two new ones by hand on the Skills library page. For each
  one, click "New skill", with the Name of the YAML on top of its `SKILL.md` (`architecture-and-access`, then `vulnerability-scan`)
  and its description. Then open the skill, click "Edit" on its SKILL.md, paste the whole of its `SKILL.md`, and click "Save new
  version". The live script puts each text in the clipboard. A second add with the same name is refused ("A skill named ... already
  exists"): open the skill and save a new version.
- A Job always gets the store skill's newest text. The version that the agent names is the one that the store had when you ticked
  the skill.
- **The platform App** (the smoke App) has the project setting `SMOKE_AUDIT_POLL_SECONDS` (10 in the demo): it polls the audit trail,
  so a stage move reaches the agent. It also has `SMOKE_PUSH_DRY_RUN=0`, else each push is a dry run and the docs are not attached.
- **The shared parts:** the second project's default branch has `governance/rules.md`, `governance/validation-doc.md`,
  `governance/README.md` and `governance/scan.py`. The skills read them in the project folder.

## Make it in the wizard

On the Agents page, click "New agent". The wizard has six steps. In each table, the first column is the wizard's label, the second
is what to set, and the third is the setting's key in `agent.json`. A row with no key is not compared. Do not click "Apply preset"
on step 5: "Project sandbox" sets Project datasets to Read only and turns Git push off.

### 1. Basics

| Setting | Set it to | In agent.json |
|---|---|---|
| "What runs the agent?" | the card "Domino Agent Harness (opencode)": the Save sends no value for it, and the App stores `harness` | `lane` |
| "Name" | `App validation`, exactly: no check has this name | `name` |
| "Description" | the `description` of agent.json | `description` |
| "Where can it work?" | "Any project" | `scope` |
| "Project required as trigger input" | checked (the default) | `inputs` |
| "Inputs" | only the project input: add no other input | `guardrails.access.inputs` |
| "Tags" | none | `tags` |

### 2. Model & runtime

| Setting | Set it to | In agent.json |
|---|---|---|
| "Model access" | the first choice: it says "Whoever triggers it" now, and "Agent identity" after step 4. The model calls use the grants of the service account | `model.access` |
| "Custom endpoint" | off | `model.source` |
| "LLM Gateway models" | `google/gemini-3.8-flash` only: add it, and remove the model that the wizard chose | `model.models` |
| "Environment" | "Domino Agent Runtime (opencode)" | `execution.environment` |
| "Hardware tier" | the default | not compared: its ID is the deployment's |
| "Max minutes per round" | `60`: one task does three checks and a scan | `execution.maxRuntimeMin` |
| "Max turns per round" | `300` | `execution.maxTurns` |
| "Wait for answers (min)" | `0`: nobody answers a task of a trigger | `execution.idleWaitMin` |

### 3. Instructions & behaviors

| Setting | Set it to | In agent.json |
|---|---|---|
| "System prompt" | the whole text of instructions.md | `systemPrompt` |
| "Suggested prompts (optional)" | none | `directTrigger.starterPrompts` |
| "Skills" | tick `purpose-and-data`, `architecture-and-access` and `vulnerability-scan`, in this order, and no other skill | `skills` |
| "Planning" | "Start right away" | `guardrails.planFirst` |
| "Task completion" | "A person closes the task" | `completion` |
| "Error recovery" | "Fail and report": nobody unblocks a task of a trigger | `onError` |
| "Check-ins" | "Only when needed" | `guardrails.checkInOften` |
| "New tasks start as" | "Background job" (the default) | not compared: it is only for a task that a person starts in the App |
| "Notifications" | none | `directTrigger.writeBack` |

### 4. Identity & sharing

| Setting | Set it to | In agent.json |
|---|---|---|
| "Acts as" | "A service account" | `identity.mode` |
| "Service account" | the service account of the three checks | `identity.serviceAccount.userName` |
| "<account>'s token" | tick "Create one for me" (below) | not compared: the App never shows a token |
| "Who can use it" | "Specific people" | `access.mode` |
| "People" | the analyst who moves the stage | `access.users` |
| "Editors" | the approver | `access.editors` |

The token: tick the checkbox "Create one for me". It lets the App create a token for the service account with your own permission
to manage service accounts, when you save. The fallback: paste a token of the service account in "Paste access token". Tokens that
Domino creates for service accounts last 24 hours. Before a later run, open the agent, edit it, and tick "Rotate: create a new
token for me".

### 5. Tools & permissions

| Setting | Set it to | In agent.json |
|---|---|---|
| "Project files" | "Read & write": the docs go in the project's files, and Git push needs it | `guardrails.access.project` |
| "Project datasets" | "No access": no doc goes to a dataset | `guardrails.access.data` |
| "Other resources attached to the task" | "Read & write": the event's bundle is attached to the task, and its writes (the attachments, the findings, the evidence) need it | `guardrails.access.named` |
| "Resources not attached to the task" | "No access": no bundle of another project | `guardrails.access.other` |
| "Shell" | on (the default): the skill architecture-and-access reads the routes with it | `guardrails.tools.bash` |
| "Web fetch" | off | `guardrails.tools.web` |
| "Subagents" | on (the default): the built-in subagent reviews the routes | `guardrails.tools.subagents` |
| "Start Domino jobs" | on: the scan runs in a Domino Job | `guardrails.tools.jobs` |
| "Git push" | on: each doc leaves the Job only through the push, to the task branch | `guardrails.tools.push` |
| "Tool servers" | none | not compared |
| "Outbound traffic" | "Domino services only" | `guardrails.network` |

With "Start Domino jobs" and "Git push" both on, the wizard shows a warning: the agent can push code and then run it as the service
account. Keep both on: the agent runs only `python governance/scan.py` (instructions.md), and it pushes only its docs.

### 6. Review

| Setting | Set it to | In agent.json |
|---|---|---|
| "Create agent" | click it: the App saves the agent and opens its Triggers tab | not compared: it sends the settings above |

The Hardware tier and the token are not compared: the Hardware tier's ID is the deployment's, and the App never shows a token.

## The Triggers tab

### The subscription

In "Event subscriptions", click "Add subscription", and fill the form:

| Setting | Set it to | In subscription.json |
|---|---|---|
| "Event subscriptions" | "Add subscription" | `type` |
| "Name" | `Bundle enters Validation` | `name` |
| "Event" | "Governance: Bundle stage changed" | `event.eventType` |
| "Only when (optional)" | "Add condition" two times: `toStage` equals `Validation`, and `project.id` equals the ID of the second project | `event.filter` |
| "Task title (optional)" | the `titleTemplate` of subscription.json | `titleTemplate` |
| "Instruction to the agent (optional)" | the `instructionTemplate` of subscription.json | `instructionTemplate` |
| "Pin resources to every task" | none | `defaultResources` |
| "Notifications" | none | `writeBack` |
| "Create trigger" | on: a new subscription is on | `enabled` |

The filter compares strings exactly. The instruction ends with the line `Bundle ID: {{bundle.id}}`.

### The schedule

In "Schedules", click "Add schedule", and fill the form:

| Setting | Set it to | In schedule.json |
|---|---|---|
| "Schedules" | "Add schedule" | `type` |
| "Name" | `Weekly re-scan of approved Apps` | `name` |
| "Cron schedule" | `0 6 * * 1`: each Monday at 06:00 | `schedule.cron` |
| "Time zone" | `UTC` | `schedule.timezone` |
| "Project (optional)" | `aml-validation-wizard`, the second project by its name | `project` |
| "Task title (optional)" | the `titleTemplate` of schedule.json | `titleTemplate` |
| "Instruction to the agent (optional)" | the `instructionTemplate` of schedule.json: it names only the task's own project | `instructionTemplate` |
| "Pin resources to every task" | none | `defaultResources` |
| "Notifications" | none | `writeBack` |
| "Create trigger" | on: a new schedule is on | `enabled` |

"Run now" on the Triggers tab fires the schedule once, at once. The task still acts as the service account, in the second project.

## Who must be in "People" and "Editors"

- The analyst who moves the stage is in "People". Else the stage move starts no task: "<analyst> is not allowed to use agent ...".
- The approver is an editor ("Editors"), or the owner, so that the approver can read the agent's tasks and its Activity log.

## Validation status

The approver does not click "Validation status" for this agent. It finds each check's task by the agent's name, which is the
check's name, so for `App validation` it shows "not started" three times. The approver reads the three evidence items on the
bundle page: they are the full result, with the three Reports.

## The compare (the live script)

After the person saves the agent, the live script reads it back with `GET /api/agents/{id}` as the owner, saves the answer, and
compares it with `compare.py diff agent.json`:

```bash
python3 governance/app-validation/compare.py diff agent.json agent-read-back.json \
  --set __SERVICE_ACCOUNT__=<account> --set __ANALYST__=<analyst> --set __APPROVER__=<approver> \
  --set __PD_SKILL_ID__=<skill ID> --set __PD_SKILL_VERSION__=<skill version> \
  --set __AA_SKILL_ID__=<skill ID> --set __AA_SKILL_VERSION__=<skill version> \
  --set __VS_SKILL_ID__=<skill ID> --set __VS_SKILL_VERSION__=<skill version>
```

It prints each setting that differs (`<key>: wants <value>, has <value>`) and exits 1, or prints "Same as agent.json." and exits 0.
Each key of `agent.json` must be in the answer, with the same value. A key that only the answer has is not compared: the IDs, the
owner, the hardware tier, the times. Text is the same when it is the same with no space at its ends.

The triggers in the same way, with the answer of `GET /api/agents/{id}/triggers` (it compares the trigger with the same type and
name): `python3 compare.py diff subscription.json triggers.json --set __WIZARD_PROJECT_ID__=<ID>`, and
`python3 compare.py diff schedule.json triggers.json`.

No reference file holds the token. So the script also checks the stored token's status: `identityCredential.status` is `active`, and
`identityCredential.account` is the service account.

## The check

```
python tests/check_app_validation.py
AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_app_validation.py
```

One line per case, with a non-zero exit code on any failure. It uses the stdlib only: the two store skills (their limits, the names
of `governance/checks.json`, no ID search, the order of their tools, no own tool and no custom subagent, the shell and the built-in
subagent, the scan, and the schedule part with only the task's own project), the instructions, each value of `agent.json`, the two
trigger files, `compare.py` (run with no site-packages), the steps on this page (one row for each key, with the wizard's label), and
no Domino host, ID or token in the folder. With `AGENT_SERVICE_REPO` (a domino-agent-service checkout, any OS), it also checks each
tool name against the service's gateway and relay, the longest wait of `domino_wait_job`, the built-in subagent's name, and each
label in quotes in the tables against the wizard's code. Nothing calls a Domino host.
