# aml-alert-triage

The AML alert triage reference workflow for the Domino Agent Service: an agent on the framework lane triages transaction monitoring
alerts, through a fake case-management system that runs as a Domino-hosted tool server. Escalating an alert to a SAR case needs a
reviewer's approval. The agent is one definition and three 1-line entry points: it runs on LangGraph, CrewAI or the Anthropic SDK
(see "The agent").

The data is fake. The spec is issue #1; the setup steps come with the build.

## Case-management system

A fake case-management system, served as an MCP server over streamable HTTP at `/mcp` (`case_server/`). On Domino it is the
App `aml-case-management`. It has three read tools and two write tools.

Read tools:

- `get_alert(alert_id)`: the alert's customer, rule, score, status (`open`, `closed` or `escalated`) and flagged transaction
  IDs. A closed or escalated alert also has who acted (`acted_by`) and when (`acted_at`, a UTC time such as
  `2026-10-17T15:04:05Z`). A closed alert also has its `reason_code` and `rationale`. An escalated alert also has its
  `sar_case_id`.
- `get_customer_profile(customer_id)`: the name, segment, KYC risk rating, occupation, expected monthly activity (in USD),
  country and PEP flag.
- `get_transactions(customer_id, days=90)`: the customer's transactions of the last `days` days (1 to 3650), oldest first.
  Each has its ID, date, amount, currency, type, counterparty, country and memo.

Write tools:

- `close_alert(alert_id, reason_code, rationale)`: closes an open alert. The reason code is `false_positive`,
  `explained_activity` or `duplicate`, and the rationale can't be empty. It answers with the closed alert.
- `escalate_to_sar(alert_id, narrative, transaction_ids)`: opens a SAR case for an open alert. The narrative and the list of
  transaction IDs can't be empty, and each transaction must be one of the alert's customer. It answers with the SAR case: its
  ID (`sar_case_id`, such as `SAR-5001`), the `narrative`, the `transaction_ids`, who opened it (`opened_by`), when
  (`opened_at`), and `"result": "escalated"`.

An unknown alert or customer ID is an MCP tool error that names the ID. So is a `days` value out of range, and each refusal
below. The error text starts with `Error executing tool <tool>: `, then the reason.

### Status rules

An alert's status moves only from `open` to `closed`, or from `open` to `escalated`. Both are final.

| Call | On an open alert | On a closed alert | On an escalated alert |
|---|---|---|---|
| `close_alert` | Closes it | Refused | Refused |
| `escalate_to_sar` | Opens a SAR case | Refused | Opens no other SAR case. Answers with the first one and `"result": "already escalated"` (not an error) |

So an alert has at most one SAR case, and a replayed escalation does no harm: the case-management system itself refuses a
second SAR case, not only the platform. Each refusal names the alert's decision: who acted, when, and the reason code or the SAR
case ID.

### Who acted

Each close and each SAR case records who acted and when (a UTC time). Who acted is the `domino-username` header, which the Apps
proxy sets to the acting identity. A missing or empty header, or `Anonymous`, is no identity, and the record says so and why:

| The request has | The record says |
|---|---|
| No `domino-username` header (the server runs locally) | `no identity (the request had no domino-username header)` |
| An empty `domino-username` header | `no identity (the domino-username header was empty)` |
| `domino-username: Anonymous` | `no identity (the domino-username header was Anonymous)` |

These texts have spaces, so they can never be a Domino user name. The server logs one line for each tool call: its arguments,
the names of its request headers (never their values: one is a token), and for a write, who acted.

On Domino, who acted is the acting identity. The live check (#7) measured it on this App with extended identity off: the Apps proxy
set `domino-username` on each call from the platform, and each close and SAR case named the analyst, also the escalation that the
platform sent after a reviewer's approval. (domino-agent-service had measured no `domino-username` for an API caller on an App with
extended identity on: its `docs/STATUS.md`, September 28, 2026.)

### Reset

`POST /reset` loads the seed again: every alert open except alert 4, and no SAR cases. It drops every table and makes them
again, so it also works on a state file from an older build, whose tables may not fit. It answers with each alert's status:

```json
{"result": "loaded the seed", "alerts": {"A-1001": "open", "A-1002": "open", "A-1003": "open", "A-1004": "closed"}}
```

It is an HTTP route, not one of the server's tools, so the tools route never offers it to an agent. Anyone who can open the
App can call it. SAR case IDs start again at `SAR-5001`.

### Case board

`GET /` is the case board: one read-only page that shows the system of record, so people can watch it change while an agent
works (for example in a demo). On Domino it is the App's URL, without `mcp`.

- **Alerts:** each alert's customer, rule, score and status, its decision (the reason code and rationale, or the SAR case), who
  acted and when (UTC).
- **SAR cases:** each SAR case's alert, who opened it and when, its transactions and its narrative. With none, the page says so.
- The page reloads itself every 5 seconds. An alert that was closed or escalated in the last 2 minutes is marked **New**.
- It changes nothing: `POST /` is refused. Like `/reset`, it is an HTTP route, not a tool, so no agent sees it. Anyone who can
  open the App can open it.
- Each value is escaped, so a rationale or a narrative that an agent wrote shows as text, never as HTML.

### The seed: four alerts

The seed (`case_server/seed.json`) has fake customers, transactions and four alerts. Each alert takes a different path through
the platform once:

| Alert | Customer | What the evidence shows | Expected triage |
|---|---|---|---|
| `A-1001` | `C-2001` | A clear false positive: a large-amount rule flagged three monthly salary deposits of 11,850 from the same employer, within the profile's expected activity. | `close_alert` with `false_positive` or `explained_activity` |
| `A-1002` | `C-2002` | Structuring: 8 cash deposits from 9,400 to 9,900 in 8 days (77,450 in all), at 3 branches and an ATM, for a rideshare driver who expects 4,500 a month. | `escalate_to_sar`, which waits for a reviewer |
| `A-1003` | `C-2003` | Unclear: a wire of 46,000 to Cyprus (memo `PER AGREEMENT 2026-14`), a country new for the customer. The profile neither explains it nor rules it out, and the transactions show no pattern: no other one is above the expected monthly activity. | A question to the analyst (`ask_human`) |
| `A-1004` | `C-2004` | Already closed in the seed, by `jordan.reyes`, 12 days before the load, with `explained_activity` (the customer sold her car). | A report, and no write |

A transaction's date is stored in the seed as days before the load (`days_ago`), and becomes a date (UTC) when the seed loads.
So the 90-day window always finds the alerts' transactions. Alert 4's time of close (`acted_days_ago`) works the same way.
One payroll deposit of `C-2001` (`T-30004`) is 94 days old, outside the default window. A model's judgment can differ from the
expected triage.

Its state is one SQLite file. The first start with a missing or empty file loads the seed (`case_server/seed.json`, fake data).
After that, the file keeps the state across restarts: alert statuses, closes and SAR cases. To start from the seed again, call
`POST /reset` (or stop the server and delete the file).

| Variable | What it does |
|---|---|
| `AML_DB_PATH` | The state file (required). Its folder must exist: the server stops when it doesn't, and never makes it. |
| `HOST`, `PORT` | Where the server listens. Default `0.0.0.0` and `8888`, as a Domino App must. |
| `AML_SEED_PATH` | The seed for an empty state file. Default `case_server/seed.json`. The check uses it. |

### Run it locally

You need Python 3.10 or later with `mcp` (`pip install -r case_server/requirements.txt`).

```bash
mkdir -p /tmp/aml
AML_DB_PATH=/tmp/aml/cases.db PORT=8890 python case_server/server.py
```

The MCP URL is `http://localhost:8890/mcp`, and the case board is `http://localhost:8890/`. To try it without an MCP client:

```bash
curl -s -X POST http://localhost:8890/mcp -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_alert","arguments":{"alert_id":"A-1001"}}}'
```

To act as a person, add `-H 'domino-username: olivia.analyst'` (the Apps proxy sets it on Domino). To load the seed again:

```bash
curl -s -X POST http://localhost:8890/reset
```

In a Domino Workspace, don't use port 8899: it is the sidecar's token port.

### Run it on Domino

`app.sh` is the App's start script. It installs `mcp` only when the Environment lacks it (the Domino Standard Environment has
it), keeps the state on the AML project's dataset `aml-cases` (`/mnt/data/aml-cases/cases.db`), and starts the server on port
8888. When the dataset doesn't exist, the App stops with a message that says to create it. The repo has no root
`requirements.txt` on purpose: Domino would install it into the agent's Jobs too.

### Set it up on Domino

Do these steps in your browser, in this order. The AML project is the Domino project `aml-alert-triage`, with this repo as its
code. The platform App is `agent-framework-smoke` on cloud-dogfood.

1. **Create the dataset.** In the AML project, create the dataset `aml-cases`. The App keeps its state file there
   (`/mnt/data/aml-cases/cases.db`), so the state survives an App restart. Create it before you publish the App. If the App is
   already running, restart it after you create the dataset.
2. **Publish the App.** In the AML project, publish an App:
   - Name: `aml-case-management`.
   - Environment: the Domino Standard Environment. It has `mcp`, so `app.sh` installs nothing.
   - Start script: `app.sh`.
   - Access: "project collaborators". The Apps proxy then lets a call through only when its acting identity can open the
     App, so an analyst who isn't a collaborator of the AML project can't use the case-management system.
   - Extended identity: off. With it off, the Apps proxy doesn't pass the caller's token to the App's code
     (domino-agent-service ADR 0016, Consequences). The App needs no token: it reads who acted from `domino-username`.

   The App's first log line shows the `mcp` version, the state file, and `loaded the seed` (a new state file) or `kept the
   state`. Its MCP URL is the App's URL as Domino gives it, plus `mcp`:
   `https://apps.cloud-dogfood.domino.tech/apps-internal/<App ID>/mcp`. Don't add a slash at the end: the server answers
   `/mcp/` with a redirect that loses the App's path.
   The App's URL itself (without `mcp`) is the case board: open it in your browser to watch the alerts change.
3. **Add the tool server.** Only the platform App's owner can change its tool server list: anyone else gets a 403. The owner is
   the owner of the project that holds the App. So the owner does this step and the next two, in the browser. Open the platform
   App's Tool servers page. Add a tool server with the name `aml`, the MCP
   URL from step 2, and no secret. Save it, reload the page, then edit `aml`: the form lists a tool server's tools only after
   it is saved. The URL is on this deployment's Apps host, so the platform treats it as a Domino-hosted tool server: each
   call carries a short-lived token for the acting identity, and the Apps proxy checks that identity's access to the App. The
   agent then sees the tools as `aml_get_alert`, `aml_get_customer_profile`, `aml_get_transactions`, `aml_close_alert` and
   `aml_escalate_to_sar`.
4. **Mark the tools.** On the same page, mark the three read tools as `read` (`get_alert`, `get_customer_profile`,
   `get_transactions`) and the two write tools as `write` (`close_alert`, `escalate_to_sar`).
5. **Turn approval on for `escalate_to_sar` only.** An escalation then waits for a reviewer (maker-checker). A close needs no
   approval. The approvers are the agent's owner and editors, minus the analyst who asked: see "Create the agent" below.

Then create the agent (below).

To load the seed again on Domino, call `POST /reset` on the App, from a Workspace in a project that can open it:

```bash
curl -s -X POST "https://apps.cloud-dogfood.domino.tech/apps-internal/<App ID>/reset" \
  -H "Authorization: Bearer $(curl -s http://localhost:8899/access-token | sed 's/^Bearer //')"
```

#### Where the platform differs from these steps

- **The Workspace token.** The `POST /reset` call above works: the live check (#7) measured that the Apps proxy takes a
  Workspace's token for an App with extended identity off.

### Check it

```bash
python tests/check_case_server.py
```

The case server check starts the server as a local process with a temporary `AML_DB_PATH`, and calls it with an MCP client over
streamable HTTP. It prints one line per case (`ok` or `FAIL`) and exits with 1 when any case fails. It needs the same Python and
`mcp` as the server.

It covers each tool's answer on the seed, unknown IDs, the 90-day window, the seed's four alerts, the reason codes, the status
rules (close, escalate, "already escalated" with the first SAR case, each refusal), transaction IDs of another customer, who acted
(from `domino-username`, and with no identity), a SAR case and a close that survive a restart, `POST /reset` (also on a state
file from an older build), the case board (each alert's row, the SAR cases, the New mark, escaped text, read only), the missing state folder, `app.sh`, and
that none of the server's tools resets the system.

## The agent

The agent is one definition, `agent/definition.json`, and three entry points: one for each framework. Each entry point is a 1-line
file that names a ready-made agent of domino-agui, the platform's helper library (domino-agent-service ADR 0030). The repo has no
other agent code. The library is on PyPI (https://pypi.org/project/domino-agui/). Its source is on GitHub
(https://github.com/ddl-subir-m/domino-agui).

| Variant | Framework (as the wizard names it) | File: its one line | Entry point |
|---|---|---|---|
| LangGraph | LangGraph | `agent/graph.py`: `from domino_agui.langgraph import build_graph` | `agent/graph.py:build_graph` |
| CrewAI | CrewAI | `agent/flow.py`: `from domino_agui.crewai import build_flow` | `agent/flow.py:build_flow` |
| Anthropic SDK | Domino AG-UI SDK | `agent/handler.py`: `from domino_agui.loop import handler` | `agent/handler.py:handler` |

The three ready-made agents do the same things for the platform (the agent contract, in domino-agent-service's GLOSSARY):

- The model client follows `AGENT_MODEL_FORMAT` (`anthropic` is Anthropic Messages, else OpenAI chat) and `AGENT_MODEL` (the alias).
  The definition's alias is `sonnet`, a Claude model, so the Anthropic SDK variant calls the Anthropic SDK.
- Agent-side tools are the tools that the relay lists (MCP at `$AGENT_SERVICE_URL/mcp`, with `$SESSION_TOKEN`), such as the
  case-management system's read tools. The relay client waits up to 300 seconds for an answer (the platform needs at least 60). A
  denial is the tool's answer.
- Client-side tools are the AG-UI run's tools, such as `aml_close_alert` and `aml_escalate_to_sar`. The agent doesn't run them: a
  call to one ends the AG-UI run, and its answer comes in a later AG-UI run (for an escalation, after a reviewer's approval).
- `ask_human` asks the analyst a question with an interrupt, with an optional expiry. When no answer comes in time, the agent is
  told so, and gets no answer. The tool's result is then "No answer came before the question expired, so it was cancelled." It says
  only what happened: spec #1 says an unanswered question never becomes a decision (story 8). What the agent does then is its system
  prompt's rule 7: leave the alert open and say why. (The text was this repo's own; the library took it, ADR 0030 decision 6.)
- The system prompt is the AG-UI run's context: the agent's system prompt from its definition (the AML instructions), the
  platform's operating rules and the task brief. The code has no AML instructions, so the three variants follow the same rules.

Each variant uses only the packages of its framework's certified Environment (domino-agent-service's
`environments/agent-<framework>.lock`). The repo has no requirements file at its root: Domino installs a root `requirements.txt` at
the start of each Job, which would change the Environment's packages. The ready-made agents came with domino-agui 0.2.0, so a
variant runs only on an Environment revision that has them. On an older revision, the import fails. On cloud-dogfood, revision #4
and later of each Environment have them (domino-agent-service #155, November 11, 2026). Revision #7 installs domino-agui 0.2.0 from
PyPI (domino-agent-service #193, November 13, 2026).

## Certification

Certification (domino-agent-service's ADR 0003 decision 8) proves that an agent follows the platform's agent contract: agent-side
tools through the relay, client-side tools across AG-UI runs and across Jobs with an approval, an interrupt, an expired question, a
thread that survives a Job restart, and the ready-made agent's own model and tools (C1 to C11). A scripted fake model drives each
test, so it doesn't test the AML judgment.

The three entry points are the same lines as domino-agent-service's examples (`examples/langgraph/graph.py`,
`examples/crewai/flow.py`, `examples/domino_agui/anthropic_agent.py`). So the platform's certification of each Environment covers
this repo's code too: C1 to C11 pass in both formats for all three, on a laptop and in Domino Jobs on revision #7 of each Environment
on cloud-dogfood (November 13, 2026, domino-agent-service #193), and before that on revision #4 (November 11, 2026, #155). Its
records are domino-agent-service's `docs/certification/<framework>.md`.

On November 10, 2026, C1 ran on each variant, in both formats, in the new images (domino-agui 0.2.0):

| | |
|---|---|
| Date | November 10, 2026 |
| Agent | this repo's `agent/` folder at AML commit `9e9ac10` as `--code`, so the entry points were `graph.py:build_graph`, `flow.py:build_flow` and `handler.py:handler` |
| Suite | domino-agent-service `feat/148-ready-made-agents` at `2af79f9`: `tests/certify/certify.py --only C1` |
| Images | built from that commit's `environments/agent-<framework>.dockerfile` on its local stand-in base (`python:3.12-slim`), not on the Domino Standard Environment |
| Platform | linux/arm64: Docker Desktop on an Apple silicon Mac |
| Model | the suite's scripted fake model, on the alias `gpt-5.4` (OpenAI chat) and on `haiku` (Anthropic Messages) |

| Variant | Image | Versions | OpenAI chat | Anthropic Messages |
|---|---|---|---|---|
| LangGraph | `domino-agents-langgraph:a666dd37ec5d` | langgraph 1.2.16, ag-ui-langgraph 0.0.47, domino-agui 0.2.0 | pass (3 of 3 checks) | pass (3 of 3 checks) |
| CrewAI | `domino-agents-crewai:414fa79b03fa` | crewai 1.15.28, ag-ui-crewai 1.0.0, litellm 1.105.3, domino-agui 0.2.0 | pass (3 of 3 checks) | pass (3 of 3 checks) |
| Anthropic SDK | `domino-agents-domino-agui:71d95ad2c406` | domino-agui 0.2.0, anthropic 2.1.0, openai 3.36.0 | pass (3 of 3 checks) | pass (3 of 3 checks) |

C1's checks: the task finishes and its result is the model's answer, the agent server started in the sandbox on the project's commit
and the certified revision, and `/health` reports the versions. So each 1-line file loads in its framework's image and serves a turn.
The suite's own output names a commit of its copy of the code, not an AML commit.

On October 29, 2026, the hand-written LangGraph graph that `agent/graph.py` was then (AML commit `da10cd0`) passed C1 to C10 in both
formats: 39 checks in each, in 95 seconds, on domino-agent-service `main` at `7561668`. That code is in this repo's git history.

Run it again with Docker running, with domino-agent-service's own Python (its `.venv`). `--code` is copied whole (only `.git` and
`__pycache__` are left out), so give it a clean copy of the committed code, never a folder with `.venv/`. Keep `--out` outside the
domino-agent-service clone; `PYTHONDONTWRITEBYTECODE=1` and `-B` keep the clone unchanged. One run for each variant:

```
mkdir /tmp/aml-code && git archive HEAD | tar -x -C /tmp/aml-code      # in this repo
cd /path/to/domino-agent-service
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B tests/certify/certify.py --framework langgraph --entrypoint agent/graph.py:build_graph \
  --code /tmp/aml-code --out /tmp/aml-certify-langgraph
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B tests/certify/certify.py --framework crewai --entrypoint agent/flow.py:build_flow \
  --code /tmp/aml-code --out /tmp/aml-certify-crewai
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B tests/certify/certify.py --framework domino-agui --entrypoint agent/handler.py:handler \
  --code /tmp/aml-code --out /tmp/aml-certify-domino-agui
```

For one test in one format, add `--only C5 --formats openai`. Run it again when an entry point changes, or when a certified
Environment gets a new revision.

## Create the agent

These steps create this workflow's agent. The steps for any framework agent are in domino-agent-service's author guide,
`docs/build-a-framework-agent.md` (https://github.com/etanlightstone/domino-agent-service/blob/main/docs/build-a-framework-agent.md).

Create the agent in the platform App's wizard. `agent/register.py` does the same through the App's API, from the definition file
`agent/definition.json`: use it when you want the definition in git, or when you don't use the UI. Create one variant, or all three:
each variant is its own agent, with its own name.

| Variant | Name | Framework (in the wizard) | Entry point | `register.py --framework` |
|---|---|---|---|---|
| LangGraph | `AML alert triage` | LangGraph | `agent/graph.py:build_graph` | `langgraph` (the default) |
| CrewAI | `AML alert triage (CrewAI)` | CrewAI | `agent/flow.py:build_flow` | `crewai` |
| Anthropic SDK | `AML alert triage (Domino AG-UI SDK)` | Domino AG-UI SDK | `agent/handler.py:handler` | `domino-agui` |

The LangGraph variant keeps the name and the entry point that it had, so the agent that exists stays that variant. The name's
suffix is the wizard's name for the framework.

Both ways make the same agent for a variant: the framework lane, the variant's framework and entry point, the tool server `aml`,
the client-side tools `aml_close_alert` and `aml_escalate_to_sar`, a Claude alias, a Domino Job on an Environment certified for
the framework, one required project input, project access `read`, data access `none`, the identity `triggering_user`, restricted
access, and the AML rules as its system prompt. Only the name, the framework, the entry point and the Environment differ between
the variants.

The platform App (`agent-framework-smoke`) has extended identity (domino-agent-service #138): each person opens it as themselves,
with no view-as switch and no console command.

### Before you create it

1. The case-management App is on the platform App's tool server list with the name `aml`, with its tools marked and approval on
   `escalate_to_sar` (steps 3 to 5 of "Set it up on Domino"). The wizard offers only the tool servers on the list, and the App
   refuses an agent that names another one.
2. You know the Domino user name of each reviewer. A reviewer must be another person: the approvers of an escalation are the
   agent's owner and editors, minus the analyst who asked. Any one of them approves or denies: one decision is enough.
3. Each reviewer can open the platform App. When its access is "Invited users only", invite them. The first time a person opens
   the App, Domino shows a consent page: they allow it.
4. The platform App has an Environment certified for the variant's framework, on a revision with the ready-made agents
   (domino-agui 0.2.0; see "The agent"). The wizard lists the certified Environments, and the script asks the App for them
   (`GET api/platform/certified-environments`). On cloud-dogfood, the platform App `agent-framework-smoke` certifies revision #7
   of the three Environments (domino-agent-service #193, November 13, 2026).

### In the wizard

Open the platform App as the analyst. You are the agent's owner. Do these steps once for each variant that you create, with the
variant's name, framework and entry point from the table above.

1. **Agents > New agent.**
2. **Basics.** Click "Your own agent code" (the framework lane). Name: the variant's name, for example `AML alert triage (CrewAI)`.
   Where can it work: Any project. Keep "Project required as trigger input" on. Next.
3. **Model & runtime.**
   - Framework: the variant's framework (LangGraph, CrewAI or Domino AG-UI SDK). Entry point: the variant's, for example
     `agent/flow.py:build_flow`. The field's example is the same path.
   - Environment: the Environment certified for that framework. When the App has exactly one, it is already selected. With none,
     the list is empty and Next stays off (see "Before you create it").
   - Model: `sonnet`. Model access: Whoever triggers it.
   - Max minutes per Job: 30. Max model calls per Job: 20. Wait for answers: 0 (a question to the analyst ends the Job at once,
     and the answer starts a new Job).
   - Next.
4. **Instructions & behaviors.**
   - System prompt: paste the AML rules. They are the definition file's `systemPrompt`, the same for each variant. To print them,
     run this in the repo:

     ```
     python3 -c "import json; print(json.load(open('agent/definition.json'))['systemPrompt'])"
     ```

     The label says "(optional)", but this agent needs the prompt: the AML rules are in the prompt, not in the code (see "The
     agent").
   - Error recovery: Fail and report.
   - Next.
5. **Identity & sharing.** Acts as: Whoever triggers it. Editors: add each reviewer. Next.
6. **Tools & permissions.**
   - Project files: Read only. Project datasets: No access. Other resources attached to the task: Read only. Not attached: No
     access.
   - Tool servers: tick `aml` (All tools).
   - Client-side tools: the wizard picks `aml_escalate_to_sar` by itself, because it needs approval. Add `aml_close_alert`.
   - Next.
7. **Review.** The Framework card shows the framework, the entry point, the Environment and its revision, and both client-side
   tools. Click **Create agent**. The agent's page opens.

To change the agent later, open its page and click Edit. The lane and the framework can't change after the agent is created: for
another framework, create that variant.

### Created in the wizard, November 10, 2026

The operator walked these steps on cloud-dogfood. Every step passed.

| | |
|---|---|
| Platform App | `agent-framework-smoke`, App `6af33a0370d68c5d28c8ca16`, with extended identity, from domino-agent-service PR #144 (`ce294da`, merged as `a728409`) |
| Case-management App | `aml-case-management`, App `6ae3f1feac77996e856a5725`, after `POST /reset` |
| Agent | `AML alert triage (wizard)`, model alias `sonnet`, LangGraph Environment `6ae24cb24abd2d2682011252` revision `6ae24cbd4abd2d2682011256` |
| Analyst | `subir_mansukhani`, the agent's owner |
| Reviewer | `subir_mansukhani_test`, an editor, in a second browser profile |

| Step | Result |
|---|---|
| The wizard | The framework list showed LangGraph, CrewAI and Domino AG-UI SDK. CrewAI had no certified Environment, and Next stayed off. An entry point without `:build_graph` showed an error. The wizard picked `aml_escalate_to_sar` by itself. The Review step showed the Framework card. |
| A-1001 | 3 reads, then `aml_close_alert`. Decision: closed. The case board showed A-1001 closed. |
| A-1002 | 3 reads, then `aml_escalate_to_sar` waited for approval. The reviewer approved it in the Inbox, and the next Job sent it. Decision: escalated, with a SAR case ID. The case board showed A-1002 escalated. |
| Edit | The wizard opened with the lane and the framework greyed. Max model calls per Job changed from 20 to 25, and both client-side tools stayed. |

### With the API: `register.py`

The agent's definition is one file in git: `agent/definition.json`, for the three variants. It is the body that the platform App's
`POST api/agents` takes, less what the script sets for a variant: the name's suffix, the framework block's name and entry point, and
the Environment. A change to the definition is a commit, and the agent page shows the system prompt.

`agent/register.py` creates one variant on the platform App, or updates it when the App has an agent with the variant's name. It uses
the stdlib only, so it runs on the Domino Standard Environment. Do the steps of "Before you create it" first.

#### Run it

In a Domino Workspace, in this repo:

```
python agent/register.py --print --reviewer <reviewer> --framework crewai
python agent/register.py --app https://<apps host>/apps-internal/<App ID> --reviewer <reviewer>
python agent/register.py --app https://<apps host>/apps-internal/<App ID> --reviewer <reviewer> --framework crewai
python agent/register.py --app https://<apps host>/apps-internal/<App ID> --reviewer <reviewer> --framework domino-agui
python agent/register.py --app https://<apps host>/apps-internal/<App ID> --reviewer <reviewer 1> --reviewer <reviewer 2>
```

- `--framework langgraph|crewai|domino-agui` is the variant (the table in "Create the agent"): the name's suffix, and the framework
  block's name and entry point. The client-side tools are the same for each. Without it, the script creates or updates the
  LangGraph variant, `AML alert triage`, as before.

- `--reviewer` is required. Give it once for each reviewer. Each run sets the whole `editors` list, so name every reviewer each
  time: a reviewer that you leave out is no longer an editor. An editor can also change the agent, not only approve.
- `--print` shows the agent body that the script sends (the file as the variant, with you in its `users` list, the reviewers in its
  `editors` list, and the overrides). It calls nothing, so it doesn't ask the App for the Environment: without `--environment`, the
  Environment is a placeholder that names `GET api/platform/certified-environments`.
- `--app` is the platform App's URL as Domino gives it. A vanity URL set through the API doesn't route. A URL that you copy from
  the browser (with `#/...`) works too.
- `--model <alias>` uses another LLM Gateway alias. The default is `sonnet`. The smoke test runs on `haiku`.
- `--environment <ID>` uses that Environment, and the script doesn't ask the App for one. It must be certified for the variant's
  framework. Without it, the script takes the certified one that the App lists (step 2 below).
- `--view-as` is for a platform App without extended identity (`smoke.py deploy --no-extended-identity`). The Apps proxy then
  changes your token on its way to the App, so the script also sends your user name in the header `X-Prototype-View-As`, and the
  App's view-as switch must be on: set the project variable `SMOKE_ALLOW_VIEW_AS=1` in the project that holds the App, then
  publish the App again. The live check (#7) ran this way.

The script calls the App as you, with the Workspace's token. With extended identity, the Apps proxy gives the App a token of yours
that Domino accepts. Your name comes from `DOMINO_STARTING_USERNAME`, else from Domino (`GET /api/users/v1/self`). The steps:

1. `GET api/me`: the App knows you by your token (with `--view-as`: by the header, with its view-as switch on). The script prints
   how the App knows you.
2. `GET api/platform/certified-environments` (not with `--environment`): the App's certified Environments, one entry for each
   Environment and framework. The script takes the last one listed for the variant's framework (for a revision, the App also takes
   the last one listed), and prints its name, ID and revision. When the App lists none for the framework, the script stops and
   prints the App's answer.
3. `GET api/agents`: it finds the agent by the variant's name.
4. `POST api/agents` when there is none, else `PUT api/agents/<id>`, with the whole body.
5. It prints the agent's ID and its page: `<App URL>/#/agents/<id>`.

The person who runs the script is the analyst: it puts you in the agent's `users` list. You are also the agent's owner when the
script creates it. The reviewers are in its `editors` list.

#### When it stops

| What it says | What to do |
|---|---|
| Domino didn't accept the token that the Apps proxy gave the App (401) | The App runs without extended identity. Publish it with extended identity (`smoke.py deploy`), or use `--view-as` (above) |
| The App sees you as another person | Run the script in a Workspace that you started |
| With `--view-as`: the App checked your token instead of the header (401), or its view-as switch is off | Set `SMOKE_ALLOW_VIEW_AS=1` and publish the App again |
| With `--view-as`: the App didn't take the header | Something between you and the App drops `X-Prototype-View-As`. Tell the platform team |
| A redirect (the Apps proxy's sign-in or consent page) | Open the App once in your browser, then run the script again |
| `toolServers names aml, which isn't in the tool server list` | Add the tool server `aml` (step 1 of "Before you create it"), then run the script again |
| The App has no Environment certified for the framework (it prints the App's list) | An operator certifies an Environment revision for that framework and adds it to `AGENT_CERTIFIED_ENVIRONMENTS` (on cloud-dogfood, domino-agent-service #155). Then run the script again |
| The App didn't list its certified Environments | The App is older than the list (`GET api/platform/certified-environments`): publish the current one, or give `--environment` |
| `Environment ... isn't certified for <framework>` (with `--environment`) | Run it again without `--environment`: the script then takes the certified one |
| Two agents with its name | Delete all but one on the App, then run the script again |
| An agent with its name that you can't change | Ask its owner to add you as an editor, or to delete it |
| Any other refusal | The script prints the App's reason (`{"detail": ...}`) |

Exit code: 0 when the agent is created or updated (or printed), 1 when the App or the Workspace stopped it, 2 when an argument is
wrong.

#### Where the platform differs from spec #1

The script follows the platform App (domino-agent-service `origin/main`):

- **The model.** The spec says "a Claude alias". The App takes `{"source": "gateway", "models": ["<alias>"], "access": "acting"}`.
  `acting` uses the LLM Gateway grants of the identity that the agent acts as (the analyst), and needs no stored token.
- **The tool server first.** The App refuses the agent until `aml` is on its tool server list. So the operator adds `aml` on the Tool
  servers page before the script runs.
- **The Environment and its revision.** The definition names no Environment: the script sets the variant's Environment ID, from the
  App's certified list (or `--environment`). The App picks the revision from its certified list (`AGENT_CERTIFIED_ENVIRONMENTS`), so
  a revision in the body would do nothing.
- **An update keeps old keys.** `PUT api/agents/<id>` replaces each key that the body has, and keeps the others. The script sends the
  whole file, so every key in it is replaced. A key that you remove from the file stays on the App.
- **Names aren't unique.** The App allows two agents with one name. The script stops when it finds two.

The definition's other values are choices, not platform rules: at most 30 minutes and 20 model turns for each Job; `idleWaitMin: 0`
(a question to the analyst ends the Job at once, and the answer starts a new Job); `onError: fail`; and the guardrails' `named: read`
and `other: none` (as the smoke test has them).

#### The check

```
python tests/check_registration.py
```

A stdlib script, one line per case, with a non-zero exit code on any failure. It checks every field of the definition and every AML
rule in its system prompt, each entry point's one line (and that the repo has no other agent code), the print mode for each
`--framework` (with a placeholder Environment, and no call), and the script's calls to a small fake App on 127.0.0.1: create and
update with your token only (extended identity) and with `--view-as`, each variant with the Environment that the App lists last for
its framework, `--environment` (no list asked), no certified Environment, an App without the list, an update found by the variant's
name, a 401 in each way, the App that sees another person, the view-as switch off (both answers), the header dropped, a redirect, a
refused request (with the hint for an Environment that isn't certified), two agents with one name, an agent you can't change, and
your name from Domino. It runs the script with `python -S`, so a package outside the stdlib fails it. Nothing calls a Domino host.
The real calls are proven in the live check.

## Live check

To run it again, follow the runbook in domino-agent-service, `tests/live_framework/README.md`
(https://github.com/etanlightstone/domino-agent-service/blob/main/tests/live_framework/README.md). It links to the steps in this
README. The sections below are the records of each run.

The live check (#7) ran the workflow on cloud-dogfood on October 29, 2026, with the steps above as they were then: `register.py`
through the view-as switch (`--view-as` today).

| | |
|---|---|
| Platform App | `agent-framework-smoke`, App `6ae3e34d4abd2d2682012349`, domino-agent-service `main` at `cb9d366`, published with `smoke.py deploy --no-extended-identity` and `SMOKE_ALLOW_VIEW_AS=1` |
| Case-management App | `aml-case-management`, App `6ae3f1feac77996e856a5725`, AML `main` at `a06e213`, on the Domino Standard Environment, state on the dataset `aml-cases` |
| Agent | `agt_8acd4c27ef`, registered with `agent/register.py`, model alias `sonnet`, LangGraph Environment revision `6ae24cbd4abd2d2682011256` |
| Analyst | `subir_mansukhani`, the agent's owner, who started each task |
| Reviewer | `etan_lightstone`, an editor, through the view-as switch |

| Alert | Task | What happened | Result |
|---|---|---|---|
| A-1001 | AGT-101 | 3 reads, then `close_alert` with `explained_activity`. Each call has a decided row and a completed row, acting as the analyst. The record names the analyst. | Pass |
| A-1002 | AGT-102 | 3 reads, then `escalate_to_sar`, held. The reviewer approved it. The next Job's claim sent it once, and SAR-5001 opened, by the analyst. The decided and completed rows have the same SHA-256. The case App's log has one `escalate_to_sar`. | Pass |
| A-1003 | AGT-103, AGT-106 | 3 reads, then `escalate_to_sar` (the $30,000 securities sale, then the $46,000 wire to Cyprus, as possible layering), in both runs. The agent asked no question. | Model judgment (below) |
| A-1004 | AGT-104 | 1 read. It reported the alert as already closed (by `jordan.reyes`, `explained_activity`), and wrote nothing. | Pass |
| A-1002, after `POST /reset` | AGT-105 | 3 reads, then `escalate_to_sar`, held. The reviewer rejected it. The task failed with "Not done: etan_lightstone rejected aml_escalate_to_sar (sha256 e9632761aed4), so it never ran." No other write, and the alert stayed open. | Pass, with a difference (below) |
| A-1001, steered | AGT-107 | The task told the agent to ask one question first. 3 reads, then a question about the deposits, and the Job ended. The analyst's reply started a new Job, and the agent closed A-1001 with `explained_activity`, by the analyst. | Pass (the question path) |

Each task's result was the summary (Decision, Rationale, Evidence, Action taken), and the transcript showed each call.

Measured:

- **Who acted.** The Apps proxy set `domino-username` on every call to the case-management App, so each close and SAR case named the
  analyst ("Who acted" above).
- **The view-as header.** `register.py` printed "The App knows you as subir_mansukhani (through the prototype view-as switch)": the
  Apps proxy passes `X-Prototype-View-As` to an App with extended identity off.
- **The Workspace token.** `POST /reset` from a Workspace in the AML project worked.

Where the platform differs from spec #1:

- **A denial ends the task.** Spec #1 says that after a denial, the agent reports it and who denied it. On the platform, a reject
  ends the task at once (domino-agent-service ADR 0001): the agent doesn't run again, and the platform's summary names who rejected
  the call. When the analyst continues the task after a reject (AGT-103, round 2), the agent learns only that "a person rejected
  it", so its report says "rejected by a reviewer" (domino-agent-service #88). It followed its rule: no other write, and the alert
  stayed open, although the analyst had explained the wire.
- **A message while an approval waits.** A message sent to a task that waits on an approval is saved in the conversation, and the
  agent never gets it (domino-agent-service #89). Send it after the decision, as feedback.

Model judgment (it doesn't fail the check):

- **A-1003.** `sonnet` escalated A-1003 in 2 runs of 2 and never asked the analyst. So a steered task proved the question path:
  AGT-107 told the agent to ask first (the table above). The question ended the Job, the reply started a new Job, and the agent
  decided with the answer.
  After the live check, the seed's `T-30035` (the $30,000 securities sale) became an invoice of 10,600, so no large amount comes in
  before the wire. Rule 6 of the system prompt now also says when the evidence is unclear: one transaction doesn't fit the profile,
  but the transactions show no pattern. Then the agent asks what the transaction is for before it escalates. The rehearsal (below)
  ran it live: the agent asked in 3 runs of 3.
- **AGT-102's wording.** After the approved escalation ran, its "Action taken" still said that the escalation "requires reviewer
  approval before it runs", and it didn't name the approver.
  After the live check, the system prompt says that an answer with a SAR case ID means that a reviewer approved the escalation and
  it ran, so "Action taken" says so. The agent still can't name the approver: the platform gives it only the tool's answer. The
  task page names the approver. The rehearsal (below) ran it live: "Action taken" said that a reviewer approved the escalation
  and that SAR-5001 is open.

### Rehearsal, November 2, 2026

The demo rehearsal ran A-1003 three times on cloud-dogfood, after the changes of PR #10. It checked the two changes that the live
check asked for: the A-1003 question and the "Action taken" wording.

| | |
|---|---|
| Platform App | `agent-framework-smoke`, App `6ae3e34d4abd2d2682012349`, domino-agent-service `main` at `8c34ea3`, published with `smoke.py deploy --no-extended-identity` and `SMOKE_ALLOW_VIEW_AS=1` |
| Case-management App | `aml-case-management`, App `6ae3f1feac77996e856a5725`, a new version from AML `main` at `a078450`, then `POST /reset` |
| Agent | A new agent, registered with `agent/register.py` from `a078450`, model alias `sonnet`, LangGraph Environment revision `6ae24cbd4abd2d2682011256` |
| Analyst | `subir_mansukhani`, who started each task |
| Reviewer | `etan_lightstone`, an editor, through the view-as switch |

| Task | What happened | Result |
|---|---|---|
| The analyst explains | 3 reads, then a question about the business purpose of the wire. The analyst explained the wire, and the agent closed A-1003. | Pass |
| The analyst can't explain | 3 reads, then the question. Its message said that the transactions show "no structuring or rapid in-and-out pattern". The analyst answered that the counterparty is unknown and that the customer couldn't explain the wire. The agent called `escalate_to_sar`, held. The reviewer approved it, the next Job sent it once, and SAR-5001 opened, by the analyst. "Action taken" said that a reviewer approved the escalation and that SAR-5001 is open. | Pass |
| No answer | 3 reads, then the question. Nobody answered. | Pass |

Each was a new task, on an open A-1003.

- **A-1003.** The agent asked the analyst in 3 runs of 3. In the live check, it asked in 0 runs of 2.
- **"Action taken".** It no longer says that an escalation that ran waits for approval. It still doesn't name the approver.
- **The platform App's store.** The platform App published from `8c34ea3` had a new store: no agent, and no tool server `aml`.
  The tool server `aml` was added again (step 3 of "Set it up on Domino"), and `register.py` created a new agent. The live
  check's agent `agt_8acd4c27ef` and its tasks aren't in that store.

### Three frameworks, November 11, 2026

The live check of domino-agent-service #155 ran the workflow on each variant (#15), on cloud-dogfood.

| | |
|---|---|
| Platform App | `agent-framework-smoke`, App `6af33a0370d68c5d28c8ca16`, domino-agent-service `feat/148-ready-made-agents` at `50b5e86` (at `69bb8f7` for AGT-124), published with `smoke.py deploy`: extended identity on, the view-as switch off |
| Case-management App | `aml-case-management`, App `6ae3f1feac77996e856a5725`, reset (`POST /reset`) before each variant |
| Agents | AML `main` at `4e4f012`, registered with `agent/register.py` (one run for each `--framework`), model alias `sonnet`: LangGraph `agt_bcdeda48d8`, CrewAI `agt_c0824e63fe`, Anthropic SDK `agt_65272ade7c` |
| Environments | revision #3 of each (domino-agui 0.2.0); revision #4 of `agent-service-ddl-agui` for AGT-124 |
| Analyst | `subir_mansukhani`, the agents' owner, who started each task |
| Reviewer | `subir_mansukhani_test`, an editor, as a second real person (no view-as) |

| Step | LangGraph | CrewAI | Anthropic SDK |
|---|---|---|---|
| A-1001: close | AGT-110: closed, `false_positive` | AGT-114: closed, `explained_activity` | AGT-120: closed, `explained_activity` |
| A-1002: escalate; the reviewer approves | AGT-111: SAR-5001 | AGT-115: SAR-5001 | AGT-121: SAR-5001 |
| A-1003: the question expires (`expires_at` 3 minutes ahead, the reply after it) | AGT-117: left open, nothing written | AGT-116: left open, nothing written | AGT-122: left open, nothing written |
| A-1003: the question is answered | AGT-113: closed, `explained_activity`, with the answer | AGT-118: decided to close with the answer (below) | AGT-123: FAIL on revision #3 (below); AGT-124: closed, `explained_activity`, with the answer, on revision #4 |

All three variants pass. Notes:

- **The expired question.** In each variant the reply came after `expiresAt`. The task showed "The reply didn't reach the agent as
  its answer: the answer came after the question's expiresAt", the agent got the expired-question text, and its summary said that no
  answer came (rule 7). AGT-112 (LangGraph) doesn't count: its reply came before `expiresAt`, so it was a real answer.
- **The question path without a steer.** In each variant the agent asked on A-1003 by itself (rule 6), unlike the live check of
  October 29.
- **AGT-118 (CrewAI).** The case server refused its `close_alert`, because AGT-119 (one more LangGraph run, by the same analyst) had
  closed A-1003 16 seconds before. The flow had decided with the answer, and its summary said that the alert was already closed.
- **AGT-123 (Anthropic SDK): a platform defect, fixed.** The agent asked, and closed A-1003 with the answer. `aml_close_alert` is
  client-side, so the summary came from the next AG-UI run, and that run had lost the question and the answer: the summary said that
  the agent never asked and that the confirmation was "fabricated". The fix is in domino-agui (`run.remember()`, domino-agent-service
  ADR 0009, amended). On revision #4, AGT-124 closed A-1003, and its summary cites the answer.
- **A-1001's reason.** The model chose `false_positive` or `explained_activity`. Both close the alert.

### Three frameworks on revision #7, November 13, 2026

The live check of domino-agent-service #193 ran the workflow on each variant again, on revision #7 of each Environment. These
images install domino-agui 0.2.0 from PyPI (https://pypi.org/project/domino-agui/), not from a copy in the platform's repo.

| | |
|---|---|
| Platform App | `agent-framework-smoke`, App `6af33a0370d68c5d28c8ca16`, domino-agent-service `feat/182-domino-agui-pypi` at `adf271f`, published with `smoke.py deploy`: extended identity on, the view-as switch off |
| Case-management App | `aml-case-management`, App `6ae3f1feac77996e856a5725`, reset (`POST /reset`) before each variant |
| Agents | AML `main` at `50f1fe0`, registered again with `agent/register.py` (one run for each `--framework`), model alias `sonnet`: LangGraph `agt_bcdeda48d8`, CrewAI `agt_c0824e63fe`, Anthropic SDK `agt_65272ade7c` |
| Environments | revision #7 of each (domino-agui 0.2.0 from PyPI), certified in Domino Jobs #271 to #274 |
| Analyst | `subir_mansukhani`, the agents' owner, who started each task |
| Reviewer | `subir_mansukhani_test`, an editor, as a second real person (no view-as) |

| Step | LangGraph | CrewAI | Anthropic SDK |
|---|---|---|---|
| A-1001: close | AGT-127: closed, `explained_activity` | AGT-131: closed, `explained_activity` | AGT-135: closed, `explained_activity` |
| A-1002: escalate; the reviewer approves | AGT-128: SAR-5001 | AGT-132: SAR-5001 | AGT-136: SAR-5001 |
| A-1003: the question expires (`expires_at` 3 minutes ahead, the reply after it) | AGT-129: left open, nothing written | AGT-133: left open, nothing written | AGT-137: left open, nothing written |
| A-1003: the question is answered | AGT-130: closed, `explained_activity`, with the answer | AGT-134: closed, `explained_activity`, with the answer | AGT-138: closed, `explained_activity`, with the answer |

All three variants pass: 12 tasks of 12. Notes:

- **The expired question.** In each variant the reply came after `expiresAt`. The task showed "The reply didn't reach the agent as
  its answer: the answer came after the question's expiresAt", the agent got the expired-question text, not the reply, and its
  summary said that no answer came (rule 7).
- **The answered question.** In each variant the agent asked on A-1003 by itself (rule 6). With the analyst's answer (a house
  purchase, and the analyst saw the contract) it closed A-1003, and its summary cites the answer. The Anthropic SDK variant's
  summary comes from the next AG-UI run, so AGT-138 shows that the fix for AGT-123 works on revision #7 too.
- **One task for each alert at a time.** Each A-1003 task started after the one before it ended, so no close collided (as AGT-118
  did on November 11).
- **AGT-129's instruction** lost its first letter when it was typed ("riage alert A-1003. ..."). The agent triaged A-1003 all the
  same.
