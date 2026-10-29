# aml-alert-triage

The AML alert triage reference workflow for the Domino Agent Service: a LangGraph agent on the framework lane triages transaction
monitoring alerts, through a fake case-management system that runs as a Domino-hosted tool server. Escalating an alert to a SAR case
needs a reviewer's approval.

The data is fake. The spec is issue #1; the setup steps come with the build.

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
