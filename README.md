# aml-alert-triage

The AML alert triage reference workflow for the Domino Agent Service: a LangGraph agent on the framework lane triages transaction
monitoring alerts, through a fake case-management system that runs as a Domino-hosted tool server. Escalating an alert to a SAR case
needs a reviewer's approval.

The data is fake. The spec is issue #1; the setup steps come with the build.

## Case-management system

A fake case-management system, served as an MCP server over streamable HTTP at `/mcp` (`case_server/`). On Domino it is the
App `aml-case-management`. Its tools so far (all read tools):

- `get_alert(alert_id)`: the alert's customer, rule, score, status (`open`, `closed` or `escalated`) and flagged transaction
  IDs. A closed or escalated alert also has who acted (`acted_by`) and when (`acted_at`, a UTC time such as
  `2026-10-17T15:04:05Z`). A closed alert also has its `reason_code` and `rationale`.
- `get_customer_profile(customer_id)`: the name, segment, KYC risk rating, occupation, expected monthly activity (in USD),
  country and PEP flag.
- `get_transactions(customer_id, days=90)`: the customer's transactions of the last `days` days (1 to 3650), oldest first.
  Each has its ID, date, amount, currency, type, counterparty, country and memo.

An unknown alert or customer ID is an MCP tool error that names the ID. So is a `days` value out of range.

### The seed: four alerts

The seed (`case_server/seed.json`) has fake customers, transactions and four alerts. Each alert takes a different path through
the platform once:

| Alert | Customer | What the evidence shows | Expected triage |
|---|---|---|---|
| `A-1001` | `C-2001` | A clear false positive: a large-amount rule flagged three monthly salary deposits of 11,850 from the same employer, within the profile's expected activity. | `close_alert` with `false_positive` or `explained_activity` |
| `A-1002` | `C-2002` | Structuring: 8 cash deposits from 9,400 to 9,900 in 8 days (77,450 in all), at 3 branches and an ATM, for a rideshare driver who expects 4,500 a month. | `escalate_to_sar`, which waits for a reviewer |
| `A-1003` | `C-2003` | Unclear: a wire of 46,000 to Cyprus (memo `PER AGREEMENT 2026-14`), a country new for the customer. The profile neither explains it nor rules it out. | A question to the analyst (`ask_human`) |
| `A-1004` | `C-2004` | Already closed in the seed, by `jordan.reyes`, 12 days before the load, with `explained_activity` (the customer sold her car). | A report, and no write |

A transaction's date is stored in the seed as days before the load (`days_ago`), and becomes a date (UTC) when the seed loads.
So the 90-day window always finds the alerts' transactions. Alert 4's time of close (`acted_days_ago`) works the same way.
One payroll deposit of `C-2001` (`T-30004`) is 94 days old, outside the default window. A model's judgment can differ from the
expected triage.

Its state is one SQLite file. The first start with a missing or empty file loads the seed (`case_server/seed.json`, fake data).
After that, the file keeps the state across restarts. To start from the seed again, stop the server and delete the file.

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

The MCP URL is `http://localhost:8890/mcp`. To try it without an MCP client:

```bash
curl -s -X POST http://localhost:8890/mcp -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_alert","arguments":{"alert_id":"A-1001"}}}'
```

In a Domino Workspace, don't use port 8899: it is the sidecar's token port.

### Run it on Domino

`app.sh` is the App's start script. It installs `mcp` only when the Environment lacks it (the Domino Standard Environment has
it), keeps the state on the AML project's dataset `aml-cases` (`/mnt/data/aml-cases/cases.db`), and starts the server on port
8888. When the dataset doesn't exist, the App stops with a message that says to create it. The repo has no root
`requirements.txt` on purpose: Domino would install it into the agent's Jobs too.

### Check it

```bash
python tests/check_case_server.py
```

The case server check starts the server as a local process with a temporary `AML_DB_PATH`, and calls it with an MCP client over
streamable HTTP. It prints one line per case (`ok` or `FAIL`) and exits with 1 when any case fails. It needs the same Python and
`mcp` as the server.

## The agent

The agent is a LangGraph graph. Its entry point is `agent/graph.py:build_graph` (the definition's `framework.entrypoint`). The graph
is the loop of domino-agent-service's LangGraph example (`examples/langgraph/graph.py`): the model calls tools until an answer has
no tool call.

- Agent-side tools are the tools that the relay lists (MCP at `$AGENT_SERVICE_URL/mcp`, with `$SESSION_TOKEN`), such as the
  case-management system's read tools. The MCP client waits up to 300 seconds for an answer (the platform needs at least 60). A
  denial is the tool's answer.
- Client-side tools are the AG-UI run's tools, such as `aml_close_alert` and `aml_escalate_to_sar`. The graph doesn't run them: a
  call to one ends the AG-UI run, and its answer comes in a later run (for an escalation, after a reviewer's approval).
- `ask_human` asks the analyst a question with an interrupt, with an optional expiry. When no answer comes in time, the agent is
  told so, and gets no answer.
- The system prompt is the AG-UI run's context: the agent's system prompt from its definition (the AML instructions), the
  platform's operating rules and the task brief. The code has no AML instructions.
- The model client follows `AGENT_MODEL_FORMAT` (`anthropic` is Anthropic Messages, else OpenAI chat) and `AGENT_MODEL` (the alias).

The agent uses only the packages of the certified LangGraph Environment (domino-agent-service's
`environments/agent-langgraph.lock`). It has no requirements file, and the repo has none at its root: Domino installs a root
`requirements.txt` at the start of each run, which would change the Environment's packages.

## Certification

Certification (domino-agent-service's ADR 0003 decision 8) proves that the agent follows the platform's agent contract: agent-side
tools through the relay, client-side tools across AG-UI runs and across Jobs with an approval, an interrupt, and a thread that
survives a Job restart. A scripted fake model drives each test, so it doesn't test the AML judgment.

| | |
|---|---|
| Date | October 29, 2026 |
| Agent | `agent/graph.py:build_graph`, at AML commit `00ea0c2` on `ticket/5-agent-graph` (the next commit adds only this record) |
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

A test passes when every one of its checks passes: 39 checks in each format, all passed. The run took 96 seconds. The suite's own
output names a commit of its copy of the code, not an AML commit.

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
   The App refuses an agent whose `toolServers` names a tool server that isn't on the list. That list doesn't take the view-as
   switch, so this script can't add it.
3. You know the reviewer's Domino user name. The reviewer must be another person: the approvers of an escalation are the agent's
   owner and editors, minus the analyst who asked.

### Run it

In a Domino Workspace, in this repo:

```
python agent/register.py --print --reviewer <reviewer>
python agent/register.py --app https://<apps host>/apps-internal/<App ID> --reviewer <reviewer>
```

- `--print` shows the agent body that the script sends (the file, with you as its user, the reviewer as its editor, and the
  overrides). It calls nothing.
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

You are the agent's owner when the script creates it, and its user. The reviewer is its editor.

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
  servers page before the script runs. Before domino-agent-service #68 merges, a tool server entry needs a secret, so the case-management
  App can't be added with no secret, and the registration waits for #68.
- **The Environment's revision.** The definition names only the Environment ID. The App picks the revision from its certified list
  (`AGENT_CERTIFIED_ENVIRONMENTS`), so a revision in the file would do nothing.
- **An update keeps old keys.** `PUT api/agents/<id>` replaces each key that the body has, and keeps the others. The script sends the
  whole file, so every key in it is replaced. A key that you remove from the file stays on the App.
- **Names aren't unique.** The App allows two agents with one name. The script stops when it finds two.

Not measured yet: whether the Apps proxy passes `X-Prototype-View-As` to an App with extended identity off. The live check (#7) shows
it: the script prints how the App knows you, and stops when the App doesn't know you by your name.

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
