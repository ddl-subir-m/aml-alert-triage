# aml-alert-triage

The AML alert triage reference workflow for the Domino Agent Service: a LangGraph agent on the framework lane triages transaction
monitoring alerts, through a fake case-management system that runs as a Domino-hosted tool server. Escalating an alert to a SAR case
needs a reviewer's approval.

The data is fake. The spec is issue #1; the setup steps come with the build.

## Case-management system

A fake case-management system, served as an MCP server over streamable HTTP at `/mcp` (`case_server/`). On Domino it is the
App `aml-case-management`. Its tools so far:

- `get_alert(alert_id)`: the alert's customer, rule, score, status and flagged transaction IDs. An unknown ID is a tool error.

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
