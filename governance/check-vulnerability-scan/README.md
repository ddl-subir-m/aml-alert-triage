# The LangGraph validator

One of the two App validators of the App validation demo (domino-agent-service spec #260, Implementation Decision 9). It is a
framework agent, `App validator (LangGraph)`, made in the wizard. Its code is in this folder: a fixed LangGraph graph. When an
analyst moves an App's governance bundle to the Validation stage of the App deployment policy, its event subscription starts a task.
The graph validates the App, writes a validation doc to a dataset snapshot, attaches the doc to the bundle, files the real findings
and fills the evidence item "Validation (LangGraph)". The other validator is the agent folder validator (harness lane,
`governance/validator-folder/`). All the data is fake.

| File | What it holds |
|---|---|
| `graph.py` | The fixed graph. Its entry point is `governance/validator-langgraph/graph.py:build_graph`. |
| `analyze.md` | The analyze step's prompt: the rules that the model follows. The graph reads it at run time. |
| `agent.json` | The agent's settings, as the wizard makes them: the body of the platform App's `POST /api/agents`, less what the wizard adds (the Environment, the service account and its token). |
| `subscription.json` | The event subscription: the body of `POST /api/agents/{id}/triggers`, with its title and instruction templates. |
| `README.md` | This page. |

## What a task does

The graph has five steps, and each task runs them once, in this order. The model takes part in one step only (analyze). The code
calls each gateway tool through the relay (`domino_agui.contract.relay()`), so it sees a denial as one. The shared parts are in
`governance/` (its README has the severity scale, the finding names and the rule for critical vulns).

1. **collect.** The graph's own code (`list_files`, `read_file`, not tools of the model) reads the App's code: `app.sh` and
   `case_server/`. Then
   `get_bundle` and `get_policy`. It finds its evidence item by its name, and each field (Verdict, Critical vulns, Summary, Doc
   location) by its label. From the same answer, it keeps the Intake values that the analyst filled (Purpose, Users, Data class):
   each filled field has its value in `result.artifactContent`. The doc's "Users and data class" gives them ("not filled" for a field
   with no value), and the model compares the Intake purpose with the code.
2. **scan.** `run_job` with `python governance/scan.py`, then `wait_job` until the Job is done, then `get_job_logs`. It reads the
   summary between the two marker lines. The scan ran only when the Job succeeded and the summary says `result: both tools ran`.
3. **analyze.** One model call. The model reads the task, the bundle, the scan's summary, the App's code, the start of the repo's
   README, the shared rules and the doc's template, and gives its analysis through one tool, `validation_analysis` (the structured
   output): the doc's facts, the real findings (each with a severity, S0 to S3, and its source, scan or code), the false hits with
   the reason, and the verdict. Then the code applies the shared rules: each finding's name is `[LangGraph] <title>`, and critical
   vulns is `yes` when a real finding is S0.
4. **write.** It fills `governance/validation-doc.md` and writes the doc to the doc dataset's mount, as
   `validation-<bundle ID>-<UTC time>.md`. Then `write_dataset_snapshot`, `get_dataset_snapshot` every 5 seconds until the snapshot
   is active (at most 3 minutes), and `write_bundle_attachment` with the type `DatasetSnapshotFile` (the dataset, the snapshot and
   the file).
5. **findings.** `write_governance_finding` for each real finding, then `write_policy_result` for "Validation (LangGraph)" only. Its
   result (the task's summary) starts with three lines: `Verdict: ...`, `Critical vulns: ...`, `Doc location: dataset <ID>,
   snapshot <ID>, file <name>`. The scripted check of the policy (`governance/validation_status.py`) shows them to the approver.

Its own model sets `max_tokens` to 16000. The ready-made model of domino-agui sets none, and an alias then gets only 4,096 output
tokens: an answer that stops there ends the run with no error (domino-agui#1). The tool is offered, not forced: Claude's newest
models refuse a forced tool choice. The model's answer stays out of the task's transcript: the result is the last step's text.

Where it can't do the whole job, it says so, in the doc ("What the validator could not check"), in the evidence item's Summary and
in the result ("Not done"), and goes on:

- **The scan.** When the scan Job fails (or doesn't start, or doesn't end in about 20 minutes), the graph follows "A failed scan" in
  `governance/README.md`, as the agent folder validator does: the doc's scan results say why, the verdict is `do not approve`, no
  finding comes from the scan, and critical vulns `no` says "No S0 finding; dependencies not scanned". The model still reviews the
  code.
- **The model's analysis.** An answer with no `validation_analysis` call is asked again once. When the second one can't be used
  either, the verdict is `do not approve`, and no finding is filed.
- **The snapshot.** A snapshot that fails is not attached, and the doc's location says so.
- **The App version's commit.** An event task reads the demo project's default branch, not the commit of the App version under
  review. The doc names the commit that the scan read.

A task validates once. A message to a task that has validated starts no step again (each one would file the findings again): its
result is the same. A new move of the bundle to Validation starts a new task, so a new validation.

## Before it can run

### The doc dataset

The doc goes to a dataset of the demo project: for example `validation-docs`. Make it once. A Git-based project's Job mounts its
own datasets at `/mnt/data/<dataset name>`, so that dataset is at `/mnt/data/validation-docs`. The graph reads the dataset from the
task's instruction. The live script replaces the subscription's placeholders:

| Placeholder | The value |
|---|---|
| `__DEMO_PROJECT_ID__` | The demo project's ID: the subscription's filter |
| `__DOC_DATASET_ID__` | The doc dataset's ID |
| `__DOC_DATASET_PATH__` | Where the Job mounts the doc dataset: `/mnt/data/<dataset name>` |

The instruction then has these lines, which the graph reads: `Bundle ID: <the event's bundle>`, `Evidence item: Validation
(LangGraph)`, `Doc dataset ID: <ID>` and `Doc dataset path: /mnt/data/<dataset name>`. With no doc dataset, the graph still files the
findings and fills the evidence item, and its Doc location says "not written". With no line `Bundle ID: ...`, the task fails at once.

### Make it in the wizard

Open the platform App as the agent's owner.

1. **Agents > New agent.**
2. **Basics.** Click "Your own agent code" (the framework lane). Name: `App validator (LangGraph)`, exactly: the scripted check
   finds the validator's tasks by this name. Where can it work: Any project. Keep "Project required as trigger input" on.
3. **Model & runtime.** Framework: LangGraph. Entry point: `governance/validator-langgraph/graph.py:build_graph`. Environment: the
   one certified for LangGraph (a revision with domino-agui 0.2.0). Model: `google/gemini-3.8-flash`. Model access: Agent identity. Max minutes per
   Job: 45. Max model calls per Job: 10. Wait for answers: 0.
4. **Instructions & behaviors.** System prompt: the `systemPrompt` of `agent.json` (the graph adds `analyze.md` to it):

   ```
   python3 -c "import json; print(json.load(open('governance/validator-langgraph/agent.json'))['systemPrompt'])"
   ```

   Error recovery: Fail and report (nobody answers an event task).
5. **Identity & sharing.** Acts as: A service account. Pick it, and add its token. Editors: the approver (a user of the agent can't
   read its tasks, and the scripted check then says "not started"). Users: each analyst who moves the stage (else the stage move
   starts no task).
6. **Tools & permissions.** Start Domino jobs: on. The access rows:
   - Project files: Read & write. A bundle of the task's project that is not on the task falls under this row.
   - Project datasets: Read & write. The doc's snapshot is a write, and the attachment reads the dataset.
   - Other resources attached to the task: Read & write. The event's bundle is attached to the task, so this row decides it: the
     attachment, the findings and the evidence item need Read & write.
   - Resources not attached to the task: No access.

   No tool server, and no client-side tool.
7. **Review.** Click **Create agent**.

Then make the subscription: copy `subscription.json`, replace the three placeholders, and send it with `POST
/api/agents/{id}/triggers`, as the owner or an editor.

### What else it needs

| What | Without it |
|---|---|
| The service account is a Contributor of the demo project, can read and write the doc dataset, has an LLM Gateway grant on `google/gemini-3.8-flash`, and may submit results, attach files and file findings on the bundle. | Domino refuses the Job, the snapshot, the model calls or the writes on the bundle. |
| The service account has a Git credential for github.com in its Domino account: Domino needs it to start a Job of a Git-based project. | Domino refuses the scan Job. |
| A token for the service account, stored before the old one expires. | Each stage move starts no task: the agent can't run yet. |
| The platform App (the smoke App) has the project setting `SMOKE_AUDIT_POLL_SECONDS` (10 in the demo). | No stage move reaches the agent. |
| The demo project's default branch has this folder and `governance/` (the demo branch is rebased on the validators). | The Job can't load the entry point, or the scan fails. |

When no service account can be used, the fallback of spec #260 is owner mode with a stored token (Acts as: The owner), with the test
account as the owner. Then the agent can't be open to anyone in Domino.

## The check

```
AGENT_SERVICE_REPO=/path/to/domino-agent-service .venv/bin/python tests/check_validator_langgraph.py
```

One line per case, with a non-zero exit code on any failure. Its own part uses the stdlib only: `agent.json` (every setting above,
and the name that the scripted check looks for), `subscription.json` (its filter, its two templates and its three placeholders), and
this page. The rest needs `AGENT_SERVICE_REPO`, the path of a domino-agent-service checkout. Without it, the check prints a `SKIP:`
line.

The graph part runs on any OS, in a Python that has the agent-langgraph Environment's packages (a venv with the pins of
domino-agent-service's `environments/agent-langgraph.lock`). It runs the
graph as a framework-lane Job runs it, with the platform's own parts and no Domino host: the platform's serve module loads the entry
point from this repo and serves it with the LangGraph adapter; the platform's AG-UI client and stream rules play the driver, and its
translator gives the task's result; the relay is the Job's own (its relay and its Gateway: each call decided on the task's policy, and
made as the gateway makes it), with a fake Domino that answers in Domino's API shape; the model is the certification seam's fake LLM
Gateway. domino-agui comes from the service's `tests/fetch_domino_agui.py`, at the pinned version. The cases:

- **A clean App.** The five steps run once each, in order. The gateway calls are `get_bundle`, `get_policy`, `run_job`, `wait_job`
  until the Job is done, `get_job_logs`, `write_dataset_snapshot`, `get_dataset_snapshot` until the snapshot is active,
  `write_bundle_attachment`, one `write_governance_finding` for each real finding, and `write_policy_result`, and no other. The model
  call has `max_tokens` 16000 and one offered tool, and reads the scan, the code and the shared rules. The doc is the template
  filled, in the snapshot, with the Intake values that the fake Domino's latest results hold. The evidence item's four fields and
  the result's three lines.
- **The scan Job fails.** The doc and the evidence item say so, the verdict is `do not approve`, no scanner finding is filed, and
  critical vulns `no` says "No S0 finding; dependencies not scanned".
- **No usable analysis, the demo branch (an S0 finding makes critical vulns yes), a failed snapshot with no Intake value filled, a
  message to a task that has validated, an instruction with no bundle, a `wait_job` answer that isn't the Job's state, the model in
  the OpenAI format, and an answer cut at its output limit.**

The service part needs Linux: it starts the agent service with a fake Domino (the service's seam helper, `tests/agent_folder_seam.py`).
The wizard's create (`POST /api/agents`) takes `agent.json` with a certified Environment and a service account: the framework lane's
rules pass (and refuse the same definition with Git push on). The subscription from `subscription.json` starts one task for a move
to Validation, as the service account, with the bundle ID in its title, and the App's task search finds it by the bundle ID. A move to
another stage starts nothing. The Job's instruction and its gateway policy are the ones that the graph part runs with. On a Mac, run
it with Docker, in the image of the service's checks (in domino-agent-service, `./tests/linux_checks.sh` builds it once; `docker
images domino-agent-service-checks` lists it), from the root of this repo:

```
docker run --rm -v /path/to/domino-agent-service:/service:ro -v "$PWD:/aml:ro" -w /aml -e AGENT_SERVICE_REPO=/service \
  -e PYTHONDONTWRITEBYTECODE=1 domino-agent-service-checks:<tag> python tests/check_validator_langgraph.py
```

That image has no LangGraph, so there the graph part prints a `SKIP:` line. `KEEP=1` keeps the graph part's temporary folder (the
agent server's log, and each case's doc). Nothing calls a Domino host. The live run is domino-agent-service #270.
