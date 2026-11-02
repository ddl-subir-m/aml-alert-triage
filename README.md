# aml-alert-triage

The AML alert triage reference workflow for the Domino Agent Service: a LangGraph agent on the framework lane triages transaction
monitoring alerts, through a fake case-management system that runs as a Domino-hosted tool server. Escalating an alert to a SAR case
needs a reviewer's approval.

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
   the owner of the project that holds the App, or, on `agent-framework-smoke` with the view-as switch on, the person who
   published it (domino-agent-service #82). So the owner does this step and the next two, in the browser, as themselves (the
   list refuses the view-as switch). Open the platform App's Tool servers page. Add a tool server with the name `aml`, the MCP
   URL from step 2, and no secret. Save it, reload the page, then edit `aml`: the form lists a tool server's tools only after
   it is saved. The URL is on this deployment's Apps host, so the platform treats it as a Domino-hosted tool server: each
   call carries a short-lived token for the acting identity, and the Apps proxy checks that identity's access to the App. The
   agent then sees the tools as `aml_get_alert`, `aml_get_customer_profile`, `aml_get_transactions`, `aml_close_alert` and
   `aml_escalate_to_sar`.
4. **Mark the tools.** On the same page, mark the three read tools as `read` (`get_alert`, `get_customer_profile`,
   `get_transactions`) and the two write tools as `write` (`close_alert`, `escalate_to_sar`).
5. **Turn approval on for `escalate_to_sar` only.** An escalation then waits for a reviewer (maker-checker). A close needs no
   approval. The approvers are the agent's owner and editors, minus the analyst who asked: see "Register the agent" below.

Then register the agent (below).

To load the seed again on Domino, call `POST /reset` on the App, from a Workspace in a project that can open it:

```bash
curl -s -X POST "https://apps.cloud-dogfood.domino.tech/apps-internal/<App ID>/reset" \
  -H "Authorization: Bearer $(curl -s http://localhost:8899/access-token | sed 's/^Bearer //')"
```

#### Where the platform differs from these steps

- **The platform App in a new browser tab.** `agent-framework-smoke` runs without extended identity. So in a new tab, each of its
  pages except Tool servers answers "Domino didn't accept that token", and the view-as switch isn't on the page. Set the switch
  once in each tab: on the App's page, open the browser's console and run
  `sessionStorage.setItem('viewAs', '<your Domino user name>'); location.reload()`. The switch then shows at the top right, and
  you can change it there (domino-agent-service #90).
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

The agent is a LangGraph graph. Its entry point is `agent/graph.py:build_graph` (the definition's `framework.entrypoint`). The graph
is the loop of domino-agent-service's LangGraph example (`examples/langgraph/graph.py`): the model calls tools until an answer has
no tool call.

- Agent-side tools are the tools that the relay lists (MCP at `$AGENT_SERVICE_URL/mcp`, with `$SESSION_TOKEN`), such as the
  case-management system's read tools. The MCP client waits up to 300 seconds for an answer (the platform needs at least 60). A
  denial is the tool's answer.
- Client-side tools are the AG-UI run's tools, such as `aml_close_alert` and `aml_escalate_to_sar`. The graph doesn't run them: a
  call to one ends the AG-UI run, and its answer comes in a later AG-UI run (for an escalation, after a reviewer's approval).
- `ask_human` asks the analyst a question with an interrupt, with an optional expiry. When no answer comes in time, the agent is
  told so, and gets no answer. The tool's result is then "No answer came before the question expired, so it was cancelled." This
  differs from the platform's example, which adds "Carry on without it.": that pushes the model to decide without the answer,
  and spec #1 says an unanswered question never becomes a decision (story 8). What the agent does then is its system prompt's
  rule: leave the alert open and say why.
- The system prompt is the AG-UI run's context: the agent's system prompt from its definition (the AML instructions), the
  platform's operating rules and the task brief. The code has no AML instructions.
- The model client follows `AGENT_MODEL_FORMAT` (`anthropic` is Anthropic Messages, else OpenAI chat) and `AGENT_MODEL` (the alias).

The agent uses only the packages of the certified LangGraph Environment (domino-agent-service's
`environments/agent-langgraph.lock`). It has no requirements file, and the repo has none at its root: Domino installs a root
`requirements.txt` at the start of each Job, which would change the Environment's packages.

## Certification

Certification (domino-agent-service's ADR 0003 decision 8) proves that the agent follows the platform's agent contract: agent-side
tools through the relay, client-side tools across AG-UI runs and across Jobs with an approval, an interrupt, and a thread that
survives a Job restart. A scripted fake model drives each test, so it doesn't test the AML judgment.

| | |
|---|---|
| Date | October 29, 2026 |
| Agent | `agent/graph.py:build_graph`, at AML commit `da10cd0` (the commit after it, `2146489`, adds only this record) |
| Suite | domino-agent-service `main` at `7561668`: `tests/certify/certify.py` |
| Image | `domino-agents-langgraph:695987bf9f16`, built from domino-agent-service's committed `environments/agent-langgraph.dockerfile` on its local stand-in base (`python:3.12-slim`), not on the Domino Standard Environment |
| Platform | linux/arm64: Docker Desktop on an Apple silicon Mac |
| Model | the suite's scripted fake model, on the alias `gpt-5.4` (OpenAI chat, `ChatOpenAI`) and on `haiku` (Anthropic Messages, `ChatAnthropic`) |
| Versions | python 3.12.15, langgraph 1.2.16, ag-ui-langgraph 0.0.47, ag-ui-protocol 1.0.0, langchain-core 1.6.13, langchain-openai 1.7.2, langchain-anthropic 1.7.6, langchain-mcp-adapters 0.3.2, langgraph-checkpoint-sqlite 3.1.2, openai 3.36.0, anthropic 1.17.0 |

| Test | Proves | OpenAI chat | Anthropic Messages |
|---|---|---|---|
| C1 | The server boots in the sandbox, and `/health` reports the versions | pass (3 of 3 checks) | pass (3 of 3 checks) |
| C2 | A plain run has zero denied egress events | pass (2 of 2 checks) | pass (2 of 2 checks) |
| C3 | Model calls go through the model proxy with run tags, and `maxTurns` applies | pass (7 of 7 checks) | pass (7 of 7 checks) |
| C4 | The transcript shows the text and tool events | pass (4 of 4 checks) | pass (4 of 4 checks) |
| C5 | An agent-side tool goes through the relay and `decide()` | pass (4 of 4 checks) | pass (4 of 4 checks) |
| C6 | A client-side tool works across two AG-UI runs | pass (5 of 5 checks) | pass (5 of 5 checks) |
| C7 | A client-side tool that needs approval works across two Jobs, and the replay runs once | pass (5 of 5 checks) | pass (5 of 5 checks) |
| C8 | An interrupt, a reply, then the run continues | pass (3 of 3 checks) | pass (3 of 3 checks) |
| C9 | An expired interrupt resumes as `cancelled` | pass (3 of 3 checks) | pass (3 of 3 checks) |
| C10 | The thread survives a Job restart, and a plain turn works without the checkpoint | pass (3 of 3 checks) | pass (3 of 3 checks) |

A test passes when every one of its checks passes: 39 checks in each format, all passed. The certification took 95 seconds. The
suite's own output names a commit of its copy of the code, not an AML commit. C9 passes with this agent's own text for an expired
question, which differs from the platform's example (see "The agent" above).

Run it again with Docker running. The host needs Python 3 with the standard library only. `--code` is copied whole (only `.git`
and `__pycache__` are left out), so give it a clean copy of the committed code, never a folder with `.venv/`. Keep `--out` outside
the domino-agent-service clone; `PYTHONDONTWRITEBYTECODE=1` and `-B` keep the clone unchanged.

```
mkdir /tmp/aml-code && git archive HEAD | tar -x -C /tmp/aml-code      # in this repo
cd /path/to/domino-agent-service
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/certify/certify.py --framework langgraph --entrypoint agent/graph.py:build_graph \
  --code /tmp/aml-code --out /tmp/aml-certify
```

For one test in one format, add `--only C5 --formats openai`. Run it again when the agent's code changes, or when the certified
LangGraph Environment gets a new revision.

## Register the agent

The agent's definition is one file in git: `agent/definition.json`. It is the body that the platform App's `POST api/agents` takes:
the framework lane, LangGraph at `agent/graph.py:build_graph`, the tool server `aml`, the client-side tools `aml_close_alert` and
`aml_escalate_to_sar`, a Claude alias, a Domino Job on the certified LangGraph Environment, one required project input, project
access `read`, data access `none`, the identity `triggering_user`, restricted access, and the AML rules as its system prompt. A
change to the definition is a commit, and the agent page shows the system prompt.

`agent/register.py` creates the agent on the platform App, or updates it when the App has an agent with its name. It uses the stdlib
only, so it runs on the Domino Standard Environment.

### Before you register

1. The platform App (`agent-framework-smoke`) has its view-as switch on. In the project that holds the App, set the project variable
   `SMOKE_ALLOW_VIEW_AS=1`, then restart the App (publish a new version). The App's first log line then shows
   `AGENT_ALLOW_VIEW_AS=1`. A project's `AGENT_ALLOW_VIEW_AS` does nothing on that App.
2. The case-management App is on the platform App's tool server list with the name `aml` (the Tool servers page, in your browser).
   The App refuses an agent whose `toolServers` names a tool server that isn't on the list. Only the App's owner can change
   that list, and it doesn't take the view-as switch, so this script can't add it (step 3 of "Set it up on Domino").
3. You know the reviewer's Domino user name. The reviewer must be another person: the approvers of an escalation are the agent's
   owner and editors, minus the analyst who asked.

### Run it

In a Domino Workspace, in this repo:

```
python agent/register.py --print --reviewer <reviewer>
python agent/register.py --app https://<apps host>/apps-internal/<App ID> --reviewer <reviewer>
```

- `--print` shows the agent body that the script sends (the file, with you in its `users` list, the reviewer in its `editors`
  list, and the overrides). It calls nothing.
- `--app` is the platform App's URL as Domino gives it. A vanity URL set through the API doesn't route. A URL that you copy from
  the browser (with `#/...`) works too.
- `--model <alias>` uses another LLM Gateway alias. The default is `sonnet`. The smoke test runs on `haiku`.
- `--environment <ID>` uses another certified LangGraph Environment. The default is `6ae24cb24abd2d2682011252`.

The script calls the App as you. Each call has the Workspace's token (for the Apps proxy) and the header `X-Prototype-View-As` with
your own Domino user name (for the App). Your name comes from `DOMINO_STARTING_USERNAME`, else from Domino
(`GET /api/users/v1/self`). The steps:

1. `GET api/me`: the App has its view-as switch on, and knows you by your name. The script prints how the App knows you.
2. `GET api/agents`: it finds the agent by its name.
3. `POST api/agents` when there is none, else `PUT api/agents/<id>`, with the whole body.
4. It prints the agent's ID and its page: `<App URL>/#/agents/<id>`.

The person who runs the script is the analyst: it puts you in the agent's `users` list. You are also the agent's owner when the
script creates it. The reviewer is in its `editors` list.

### When it stops

| What it says | What to do |
|---|---|
| The App checked your token instead of the view-as header (401), or the view-as switch is off | Set `SMOKE_ALLOW_VIEW_AS=1` and restart the App (step 1 above) |
| The App didn't take the view-as header | Something between you and the App drops `X-Prototype-View-As`. Tell the platform team |
| A redirect (the Apps proxy's sign-in or consent page) | Open the App once in your browser, then run the script again |
| `toolServers names aml, which isn't in the tool server list` | Add the tool server `aml` (step 2 above), then run the script again |
| `Environment ... isn't certified for langgraph` | Run it again with `--environment` and an ID that the App lists |
| Two agents with its name | Delete all but one on the App, then run the script again |
| An agent with its name that you can't change | Ask its owner to add you as an editor, or to delete it |
| Any other refusal | The script prints the App's reason (`{"detail": ...}`) |

Exit code: 0 when the agent is registered (or printed), 1 when the App or the Workspace stopped it, 2 when an argument is wrong.

### Where the platform differs from spec #1

The script follows the platform App (domino-agent-service `origin/main`):

- **The model.** The spec says "a Claude alias". The App takes `{"source": "gateway", "models": ["<alias>"], "access": "acting"}`.
  `acting` uses the LLM Gateway grants of the identity that the agent acts as (the analyst), and needs no stored token.
- **The view-as switch off.** The spec says to check `viewAsEnabled`. With extended identity off, an App with the switch off doesn't
  answer `viewAsEnabled: false`: it ignores the header, checks the token that the Apps proxy changed, and answers 401 ("Domino didn't
  accept that token"). The script reads that 401 as "the switch is off". It also stops on `viewAsEnabled: false`.
- **The tool server first.** The App refuses the agent until `aml` is on its tool server list. So the operator adds `aml` on the Tool
  servers page before the script runs.
- **The Environment's revision.** The definition names only the Environment ID. The App picks the revision from its certified list
  (`AGENT_CERTIFIED_ENVIRONMENTS`), so a revision in the file would do nothing.
- **An update keeps old keys.** `PUT api/agents/<id>` replaces each key that the body has, and keeps the others. The script sends the
  whole file, so every key in it is replaced. A key that you remove from the file stays on the App.
- **Names aren't unique.** The App allows two agents with one name. The script stops when it finds two.

The Apps proxy passes `X-Prototype-View-As` to an App with extended identity off: in the live check (#7), the script printed "The App
knows you as subir_mansukhani (through the prototype view-as switch)".

The definition's other values are choices, not platform rules: at most 30 minutes and 20 model turns for each Job; `idleWaitMin: 0`
(a question to the analyst ends the Job at once, and the answer starts a new Job); `onError: fail`; and the guardrails' `named: read`
and `other: none` (as the smoke test has them).

### The check

```
python tests/check_registration.py
```

A stdlib script, one line per case, with a non-zero exit code on any failure. It checks every field of the definition and every AML
rule in its system prompt, the print mode, and the script's calls to a small fake App on 127.0.0.1: create, update, the view-as switch
off (both answers), the header dropped, a redirect, a refused request, two agents with one name, an agent you can't change, and your
name from Domino. It runs the script with `python -S`, so a package outside the stdlib fails it. Nothing calls a Domino host. The real
calls are proven in the live check.

## Live check

The live check (#7) ran the workflow on cloud-dogfood on October 29, 2026, with the steps above.

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
