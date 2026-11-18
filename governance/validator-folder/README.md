# The agent folder validator

One of the two App validators of the App validation demo (domino-agent-service spec #260, Implementation Decision 8). It is a harness
agent (opencode), "App validator (agent folder)", and this folder is its definition: `domino-agent deploy` registers it from git
(domino-agent-service ADR 0037). When an analyst moves an App's governance bundle to the Validation stage of the App deployment
policy, its event subscription starts a task. The task validates the App and fills the evidence item "Validation (agent folder)".
The other validator is the LangGraph validator (framework lane). All the data is fake.

| File | What it holds | Deployed |
|---|---|---|
| `definition.md` | The settings, as YAML between two `---` lines. Each field is on domino-agent-service's reference page, `docs/definition-file.md`. | Yes |
| `instructions.md` | The instructions: the validator's rules. They become the agent's system prompt. | Yes |
| `skills/app-validation/SKILL.md` | The checklist, an own skill: the steps from the bundle to the filled evidence item, with the tool of each step. | Yes |
| `subscription.json` | The event subscription: the body of `POST /api/agents/{id}/triggers`, with its title and instruction templates. | No: the owner makes it |
| `README.md` | This page. | No |

## What a task does

The checklist's steps, in order. The shared parts are in `governance/` (its README has the severity scale and the finding names).

1. It reads the bundle and its policy (`domino_get_bundle`, `domino_get_policy`). It finds its evidence item by its name, and each
   field (Verdict, Critical vulns, Summary, Doc location) by its label.
2. It reads the App's code, its start script and its requirements.
3. It runs the scan in a Domino Job (`domino_run_job` with `python governance/scan.py`, then `domino_wait_job`), and reads the
   summary between its two marker lines.
4. It sorts each hit into a real finding (with a severity, S0 to S3) or a false hit (with the reason).
5. It writes the doc from `governance/validation-doc.md` to `docs/validation/agent-folder-<bundle ID>.md`.
6. It commits and pushes the doc to its task branch, `agent/<task key>` (`domino_git_push`).
7. It attaches the doc to the bundle: a `Report` from `GBP`, with the task branch and the push's commit
   (`domino_write_bundle_attachment`).
8. It files each real finding, named `[folder] <title>` (`domino_write_governance_finding`).
9. It fills its own evidence item (`domino_write_policy_result`).
10. Its result (`domino_report_result`) starts with three lines: `Verdict: ...`, `Critical vulns: ...`, `Doc location: ...`. The
    scripted check of the policy (`governance/validation_status.py`) shows them to the approver.

Where it can't do the whole job, it says so under "What the validator could not check" (in the doc and in the result):

- **The Intake values.** No gateway tool reads a bundle's evidence values, so the doc's "Users and data class" says "Not read".
- **A failed scan.** When the scan Job fails, or a tool could not run, it follows "A failed scan" in `governance/README.md`, as the
  LangGraph validator does: the verdict is `do not approve`, no finding comes from the scan, and critical vulns `no` says "No S0
  finding; dependencies not scanned".
- **A dry-run push.** When the platform App pushes in dry-run mode, the commit is not on the remote. The validator then attaches
  nothing, its Doc location says "Not in the repo", and its result holds the whole doc.
- **The App version's commit.** An event task reads the demo project's default branch, not the commit of the App version under
  review.

## Before it can run

The folder holds the agent's behaviour, and no user names: no service account, no sharing and no trigger. The owner adds these once,
after the first deploy. A later deploy keeps them.

| What the owner adds | How | Without it |
|---|---|---|
| The service account and its token | In the wizard's Identity & sharing step: pick the service account, and add its token. Store a new token before the old one expires. | The deploy says "Can't run yet", and each stage move starts no task: the agent can't run yet. |
| The service account's rights | The service account is a Contributor of the demo project, has an LLM Gateway grant on the model alias `sonnet`, and may submit results, attach files and file findings on the bundle (a governance role). | Domino refuses the Job, the model calls or the writes on the bundle. |
| The service account's Git credential | A Git credential for github.com in the service account's Domino account, with write access to this repo: Domino needs it to start a Job of a Git-based project, and the push needs write access. | Domino refuses the Job, or the push is refused. |
| The analyst | Share the agent, as a user, with each analyst who moves the stage. | The stage move starts no task: "<analyst> is not allowed to use agent ...". |
| The approver | Share the agent with the approver as an owner or an editor. | The scripted check shows "not started": a user of the agent can't read its tasks. |
| The subscription | Copy `subscription.json`, replace `__DEMO_PROJECT_ID__` with the demo project's ID, and send it with `POST /api/agents/{id}/triggers`, as the owner or an editor. | No stage move starts a task. |
| The poller | The platform App (the smoke App) has the project setting `SMOKE_AUDIT_POLL_SECONDS` (10 in the demo). | No stage move reaches the agent. |
| Real pushes | The platform App has the project setting `SMOKE_PUSH_DRY_RUN=0`. | Each push is a dry run: the doc is not in the repo, and the validator doesn't attach it. |
| The shared parts | The demo project's default branch has `governance/scan.py` and `governance/validation-doc.md` (the demo branch is rebased on the validators). | The scan Job fails, or the doc has no template. |

The access rows are in `definition.md`. An edit in the wizard is a commit to the agent's branch, so keep these values there too:

| Row | Value | Why |
|---|---|---|
| Project files | Read & write | The doc goes in the project's files, and the push needs write. A bundle of the task's project that is not on the task falls under this row. |
| Project datasets | No access | The validator reads no dataset. |
| Other resources attached to the task | Read & write | The event's bundle is attached to the task, so this row decides it. Its writes (the attachment, the findings, the evidence) need Read & write: with Read only, the gateway denies each one. |
| Resources not attached to the task | No access | The validator works only on the task's project and the event's bundle. |

`on-error: fail`: nobody answers an event task, so a denied call ends the task with a report, and never waits for a person.

## Deploy it

In a Domino Workspace in this repo, on a commit (the folder must have no changes that aren't committed), with the `domino-agent`
command (`pip install domino-agent`). On a laptop, also set `DOMINO_TOKEN`.

```
export AGENT_SERVICE_URL=https://<apps host>/apps-internal/<App ID>      # the platform App's URL, as Domino gives it
domino-agent deploy --dry-run governance/validator-folder
domino-agent deploy governance/validator-folder
```

The first deploy prints `Created App validator (agent folder) (agt_...)` and a notice: it can't run yet, because it acts as a
service account and none is chosen. Then add what the table above lists.

## The check

```
python tests/check_validator_folder.py
AGENT_SERVICE_REPO=/path/to/domino-agent-service python tests/check_validator_folder.py
```

One line per case, with a non-zero exit code on any failure. Its own part uses the stdlib only: the files that deploy uploads, the
checklist's rules and the order of its tools, the instructions' rules, the subscription's file, no Domino host or ID in the folder,
and this page. With `AGENT_SERVICE_REPO` (a domino-agent-service checkout, any OS), it also checks each tool name against the service's
gateway and relay. The rest needs Linux: it starts the agent service with a fake Domino (the service's seam helper,
`tests/agent_folder_seam.py`), commits the folder in a temporary clone, and then:

- `domino-agent deploy --dry-run` passes the service's folder rules, and `deploy` registers the agent: its settings, its skill and
  "can't run yet".
- The owner makes the subscription from `subscription.json`. A stage move starts no task before the token, nor for an analyst who
  may not use the agent. After both, it starts one task as the service account, with the bundle ID in its title, and its Job.
- The Job's spec has the skill, the access rows, the permissions and the limits. The gateway's decisions for this task allow the
  attachment, the findings and the evidence on the event's bundle, `run_job` and `git_push`, and no project dataset.
- A stage move to another stage, or in another project, starts nothing.

On a Mac, run it with Docker, in the image of the service's checks (in domino-agent-service, `./tests/linux_checks.sh` builds it
once; `docker images domino-agent-service-checks` lists it), from the root of this repo:

```
docker run --rm -v /path/to/domino-agent-service:/service:ro -v "$PWD:/aml:ro" -w /aml -e AGENT_SERVICE_REPO=/service \
  -e PYTHONDONTWRITEBYTECODE=1 domino-agent-service-checks:<tag> python tests/check_validator_folder.py
```

Nothing calls a Domino host. The live run is domino-agent-service #270.
