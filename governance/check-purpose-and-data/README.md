# Check 1: Purpose and data

One of the three checks of the App validation demo (domino-agent-service spec #388, Implementation Decision 8). The rules that the
three checks share are in [governance/rules.md](../rules.md), and what each check owns is in [governance/README.md](../README.md).
This check owns what the App is for and what data it holds, compared with the Intake answers (Purpose, Users, Data class). It does
not review code security.

It is a wizard agent: a harness agent (opencode) that a person makes in the agent service App's wizard, with no code. The person makes
it once, with the steps on this page. This folder is its reference copy in git, so that it can be made again on a new deployment.
The live script reads the agent back and compares it with this copy. All the data is fake.

| File | What it holds |
|---|---|
| `SKILL.md` | The store skill `purpose-and-data`: the checklist, from the bundle to the filled evidence item. A wizard agent can't have an own skill, so its checklist is a skill of the App's skills store. |
| `instructions.md` | The agent's system prompt: its rules. |
| `agent.json` | The reference settings: the agent as the wizard's Save sends it (`POST /api/agents`), with placeholders, and with no value of a deployment (an ID, the hardware tier). Each key has its row in the steps below. |
| `subscription.json` | The event subscription: the body of `POST /api/agents/{id}/triggers`, as the Triggers tab's form sends it, with the demo project's ID as a placeholder. |
| `compare.py` | Fills the placeholders, and compares what the App stores with `agent.json` and `subscription.json`. Stdlib only. |
| `README.md` | This page. |

## What a task does

When the analyst moves an App's governance bundle to the Validation stage of the policy "App deployment policy", the subscription
starts a task. The task does the steps of the store skill, in order:

1. It reads the bundle and its policy (`domino_get_bundle`, `domino_get_policy`). It finds its evidence item "Validation: Purpose and
   data" by its name, and each field (Verdict, Highest severity, Summary, Doc location) by its label. It reads the Intake values that
   the analyst filled (Purpose, Users, Data class).
2. It reads the App's README, its start script, its code and the sample data that the code loads.
3. It classifies the data by the kind of data that the App is built to hold, not by whether the sample data is fake.
4. It compares this with the Intake. An Intake Data class lower than the data's class is S1.
5. It writes the doc from `governance/validation-doc.md` (the shared top part and its own middle part) to
   `docs/validation/purpose-and-data-<bundle ID>.md`.
6. It pushes the doc to its task branch, `agent/<task key>` (`domino_git_push`).
7. It attaches the doc to the bundle: a `Report` from `GBP`, with the task branch and the push's commit
   (`domino_write_bundle_attachment`).
8. It files each real finding, with its name by the finding names of `governance/rules.md` (`domino_write_governance_finding`).
9. It fills its own evidence item (`domino_write_policy_result`).
10. Its result (`domino_report_result`) starts with the four lines of `governance/rules.md`, "The result". The scripted check
    "Validation status" shows them to the approver.

What it can't check goes under "What this check could not check", in the doc and in the result: the commit of the App version under
review (an event task reads the demo project's default branch), the data in the running App (it reads the code and the sample data),
and a push in dry-run mode (then it attaches nothing, and its result holds the whole doc).

## The placeholders

The repo is public, so the reference files have no user name and no Domino ID. `compare.py` fills these:

| Placeholder | Its value |
|---|---|
| `__SERVICE_ACCOUNT__` | The service account that the agent acts as (`agent.json`) |
| `__ANALYST__` | The analyst who moves the bundle's stage (`agent.json`, "People") |
| `__APPROVER__` | The approver (`agent.json`, "Editors") |
| `__SKILL_ID__`, `__SKILL_VERSION__` | The store skill's ID and version, from `GET /api/skills` (`agent.json`) |
| `__DEMO_PROJECT_ID__` | The demo project's ID (`subscription.json`) |
| `__INSTRUCTIONS__` | The text of `instructions.md`: `compare.py` fills it by itself |

## Before you make it

- **The store skill must exist first:** the wizard's step 3 lists only the skills of the store. The live script adds it with the
  skills API: `POST /api/skills` with `name` `purpose-and-data`, the `description` of the YAML on top of `SKILL.md`, the whole of
  `SKILL.md` as `content`, and `scope` `personal`.
- A second add with the same name is refused (400, "A skill named 'purpose-and-data' already exists"). So the script finds the skill
  by its name in `GET /api/skills`, and when its text differs, it sends the new text with `PUT /api/skills/{id}`.
- By hand: on the Skills library page, click "New skill", with the Name `purpose-and-data` and the description. Then open the skill,
  click "Edit" on its SKILL.md, paste the whole of `SKILL.md`, and click "Save new version".
- A Job always gets the store skill's newest text. The version that the agent names is the one that the store had when you ticked
  the skill.
- **The model:** the wizard lists only the models that you can call ("Listed with your access"). Make sure that you can call
  `google/gemini-3.8-flash` before you start. The service account needs its own grant on it, because the model calls use its
  grants. Not `sonnet`: Anthropic's cyber safeguards refuse this work (domino-agent-service #270).
- **The service account's rights:** the service account is a Contributor of the demo project, has an LLM Gateway grant on the model
  alias `google/gemini-3.8-flash`, and may submit results, attach files and file findings on the bundle (a governance role).
- **The service account's Git credential:** a Git credential for github.com in the service account's Domino account, whose token
  has write access to this repo (the push). Then the service account maps it to the project's repository, with its own token:
  `PUT /v4/projects/{projectId}/repository/{repoId}/credentialMapping` `{"credentialId": ...}`. With no mapping, the push fails.
- **The platform App** (the smoke App) has the project setting `SMOKE_AUDIT_POLL_SECONDS` (10 in the demo): it polls the audit trail,
  so a stage move reaches the agent. It also has `SMOKE_PUSH_DRY_RUN=0`, else each push is a dry run: the doc is not in the repo,
  and the task doesn't attach it.
- **The shared parts:** the demo project's default branch has `governance/rules.md`, `governance/validation-doc.md` and
  `governance/README.md`. The checklist reads them in the project folder.

## Make it in the wizard

On the Agents page, click "New agent". The wizard has six steps. In each table, the first column is the wizard's label, the second
is what to set, and the third is the setting's key in `agent.json`. A row with no key is not compared. Do not click "Apply preset"
on step 5: "Project sandbox" sets Project datasets to Read only and turns Git push off.

### 1. Basics

| Setting | Set it to | In agent.json |
|---|---|---|
| "What runs the agent?" | the card "Domino Agent Harness (opencode)": the Save sends no lane for it, and the App stores `harness` | `lane` |
| "Name" | `Purpose and data`, exactly: the scripted check Validation status finds the check's task by this name | `name` |
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
| "Max minutes per round" | `45` | `execution.maxRuntimeMin` |
| "Max turns per round" | `120` | `execution.maxTurns` |
| "Wait for answers (min)" | `0`: nobody answers an event task | `execution.idleWaitMin` |

### 3. Instructions & behaviors

| Setting | Set it to | In agent.json |
|---|---|---|
| "System prompt" | the whole text of instructions.md | `systemPrompt` |
| "Suggested prompts (optional)" | none | `directTrigger.starterPrompts` |
| "Skills" | tick `purpose-and-data`, and no other skill | `skills` |
| "Planning" | "Start right away" | `guardrails.planFirst` |
| "Task completion" | "A person closes the task" | `completion` |
| "Error recovery" | "Fail and report": nobody unblocks an event task | `onError` |
| "Check-ins" | "Only when needed" | `guardrails.checkInOften` |
| "New tasks start as" | "Background job" (the default) | not compared: it is only for a task that a person starts in the App |
| "Notifications" | none | `directTrigger.writeBack` |

### 4. Identity & sharing

| Setting | Set it to | In agent.json |
|---|---|---|
| "Acts as" | "A service account" | `identity.mode` |
| "Service account" | the service account of the demo | `identity.serviceAccount.userName` |
| "<account>'s token" | tick "Create one for me" (below) | not compared: the App never shows a token |
| "Who can use it" | "Specific people" | `access.mode` |
| "People" | the analyst who moves the stage | `access.users` |
| "Editors" | the approver | `access.editors` |

The token: tick the checkbox "Create one for me". It lets the App create a token for the service account with your own permission
to manage service accounts, when you save. The fallback: paste a token of the service account in "Paste access token" (the live
script can make one and put it in the clipboard). Tokens that Domino creates for service accounts last 24 hours. Before a later run,
open the agent, edit it, and tick "Rotate: create a new token for me".

### 5. Tools & permissions

| Setting | Set it to | In agent.json |
|---|---|---|
| "Project files" | "Read & write": the doc goes in the project's files, and Git push needs it | `guardrails.access.project` |
| "Project datasets" | "No access": the check reads no dataset | `guardrails.access.data` |
| "Other resources attached to the task" | "Read & write": the event's bundle is attached to the task, and its writes (the attachment, the findings, the evidence) need it | `guardrails.access.named` |
| "Resources not attached to the task" | "No access" | `guardrails.access.other` |
| "Shell" | on (the default) | `guardrails.tools.bash` |
| "Web fetch" | off | `guardrails.tools.web` |
| "Subagents" | off: it is on by default | `guardrails.tools.subagents` |
| "Start Domino jobs" | off: the check starts no Job | `guardrails.tools.jobs` |
| "Git push" | on: the doc leaves the Job only through the push, to the task branch | `guardrails.tools.push` |
| "Tool servers" | none | not compared |
| "Outbound traffic" | "Domino services only" | `guardrails.network` |

### 6. Review

Click "Create agent". The App opens the agent's Triggers tab. The Hardware tier and the token are not compared: the Hardware tier's ID
is the deployment's, and the App never shows a token.

## The subscription, on the Triggers tab

The live script makes the subscription through the API: `python3 compare.py fill subscription.json --set __DEMO_PROJECT_ID__=<ID>`
gives the body of `POST /api/agents/{id}/triggers`, which the owner or an editor sends. In the App, the same subscription is: in
"Event subscriptions", click "Add subscription", and fill the form "New event subscription":

| Setting | Set it to | In subscription.json |
|---|---|---|
| "Event subscriptions" | "Add subscription" | `type` |
| "Name" | `Bundle enters Validation` | `name` |
| "Event" | "Governance: Bundle stage changed" | `event.eventType` |
| "Only when (optional)" | "Add condition" two times: `toStage` equals `Validation`, and `project.id` equals the demo project's ID | `event.filter` |
| "Task title (optional)" | the `titleTemplate` of subscription.json | `titleTemplate` |
| "Instruction to the agent (optional)" | the `instructionTemplate` of subscription.json | `instructionTemplate` |
| "Pin resources to every task" | none | `defaultResources` |
| "Notifications" | none | `writeBack` |
| "Create trigger" | on: a new subscription is on | `enabled` |

The filter compares strings exactly. The title is the check's name and the bundle ID, so that "Validation status" finds the task.

## Who must be in "People" and "Editors"

- The analyst who moves the stage is in "People". Else the stage move starts no task: "<analyst> is not allowed to use agent ...".
- The approver is an editor ("Editors"), or the owner. Else "Validation status" shows the check as "not started": a person in
  "People" only can't read the agent's tasks.

## The compare (the live script)

After the person saves the agent, the live script reads it back with `GET /api/agents/{id}` as the owner, saves the answer, and
compares it with `compare.py diff agent.json`:

```bash
python3 governance/check-purpose-and-data/compare.py diff agent.json agent-read-back.json \
  --set __SERVICE_ACCOUNT__=<account> --set __ANALYST__=<analyst> --set __APPROVER__=<approver> \
  --set __SKILL_ID__=<skill ID> --set __SKILL_VERSION__=<skill version>
```

It prints each setting that differs (`<key>: wants <value>, has <value>`) and exits 1, or prints "Same as agent.json." and exits 0.
Each key of `agent.json` must be in the answer, with the same value. A key that only the answer has is not compared: the IDs, the
owner, the hardware tier, the times. Text is the same when it is the same with no space at its ends.

The subscription in the same way: `python3 compare.py diff subscription.json triggers.json --set __DEMO_PROJECT_ID__=<ID>`, with
the answer of `GET /api/agents/{id}/triggers` (it compares the trigger with the same type and name).

No reference file holds the token. So the script also checks the stored token's status: `identityCredential.status` is `active`, and
`identityCredential.account` is the service account.

When the wizard can't be used, `python3 compare.py fill agent.json --set ...` gives the body of `POST /api/agents`. Add
`identityCredentialToken` (the service account's token) to it in memory, never in a file. The check makes the agent this way.

## The check

```
python tests/check_purpose_and_data.py
AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_purpose_and_data.py
```

One line per case, with a non-zero exit code on any failure. Its own part uses the stdlib only: the store skill's rules and the order
of its tools, the instructions' rules, the reference settings (each value of decision 8), the subscription's file, `compare.py` (run
with no site-packages), the steps on this page (one row for each key of `agent.json` and of `subscription.json`, with the wizard's
label), and no Domino host, ID or token in the folder. The names, the evidence item, the field labels, the verdicts and the
severities come from `governance/checks.json`. With `AGENT_SERVICE_REPO` (a domino-agent-service checkout, any OS), it also checks
each tool name against the service's gateway and relay, and each label in quotes in the tables against the wizard's code. The rest
needs Linux: it starts the agent service with a fake Domino (the service's seam helper, `tests/agent_folder_seam.py`), and then:

- The store skill is added through the skills API. The agents API takes the reference settings, filled by `compare.py`, as the
  wizard's Save sends them, with the service account's token. `compare.py diff` finds no difference in the stored agent.
- The subscription is made from `subscription.json`. A stage move to Validation in the demo project starts one task as the service
  account, and its Job. A move to another stage, or in another project, starts none. An analyst who is not in "People" starts none.
- The Job's spec has the store skill's text, Run a Job off, Git push on, the access rows and the limits. The gateway allows the
  attachment, the findings and the evidence on the event's bundle, and the push, and no project dataset.

On a Mac, run it with Docker, in the image of the service's checks (in domino-agent-service, `./tests/linux_checks.sh` builds it
once; `docker images domino-agent-service-checks` lists it), from the root of this repo:

```
docker run --rm -v /path/to/domino-agent-service:/service:ro -v "$PWD:/aml:ro" -w /aml -e AGENT_SERVICE_REPO=/service \
  -e PYTHONDONTWRITEBYTECODE=1 domino-agent-service-checks:<tag> python tests/check_purpose_and_data.py
```

Nothing calls a Domino host. The live run is domino-agent-service #397.
