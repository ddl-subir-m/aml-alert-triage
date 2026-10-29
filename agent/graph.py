"""The AML agent: a LangGraph graph for the Domino Agent Service's framework lane.

    "framework": {"name": "langgraph", "entrypoint": "agent/graph.py:build_graph",
                  "clientTools": ["aml_close_alert", "aml_escalate_to_sar"]}

The graph is the loop of the platform's LangGraph example (domino-agent-service, examples/langgraph/graph.py). It calls the model
and does what each answer asks, until an answer has no tool call:
- the model client comes from AGENT_MODEL_FORMAT: ChatAnthropic (Anthropic Messages format) or ChatOpenAI (OpenAI chat format),
  for the alias in AGENT_MODEL. The base URLs and the keys come from the environment that the platform sets;
- agent-side tools are the tools that the relay lists (MCP at $AGENT_SERVICE_URL/mcp, with $SESSION_TOKEN), such as the
  case-management system's read tools. They run in this AG-UI run. A denial comes back as the tool's answer;
- client-side tools are the ones in the AG-UI run's tools (RunAgentInput.tools), which the bridge puts in state["tools"], such as
  aml_close_alert and aml_escalate_to_sar. The graph offers them to the model and doesn't run them: a call to one ends the AG-UI
  run, and its answer comes as a tool message in a later run (the next one, or a later Job after a reviewer's approval). A tool in
  both lists is client-side;
- ask_human, the agent's own tool, asks the analyst a question with interrupt(): the run ends with one interrupt (its message is
  the question, its expiresAt the model's expires_at). The reply text is the tool's result. When no reply comes before expiresAt,
  the result says so, without any reply;
- the model's system prompt is the AG-UI run's context (the agent's system prompt from its definition, the platform's operating
  rules and the task brief), which the bridge puts in state["ag-ui"]["context"]. The AML instructions live in the definition, not
  in this file.

The graph uses only the packages of the certified LangGraph Environment.
"""
import os
from datetime import timedelta
from typing import Annotated

from typing_extensions import TypedDict   # as MessagesState's

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

# The relay's MCP client. The read timeout is how long a call can wait for the relay's answer: wait_job holds a relay call open
# for up to 45 s, so it must be at least 60 s. The other timeout is for connect, write and pool.
CONNECT_TIMEOUT = timedelta(seconds=30)
READ_TIMEOUT = timedelta(seconds=300)

_relay = []   # the relay's tools, loaded once per agent server, in the first run (no network at import)

ASK = "ask_human"
ASK_HUMAN = {"type": "function", "function": {
    "name": ASK, "description": "Ask the analyst who started the task a question, and wait for the answer.",
    "parameters": {"type": "object", "required": ["question"], "properties": {
        "question": {"type": "string", "description": "The question"},
        "expires_at": {"type": "string", "description": "Optional: when the answer stops being useful (ISO 8601)"}}}}}
CANCELLED = "__agui_cancelled__"   # what interrupt() returns when the platform cancels the question (the bridge's sentinel)
# The tool's result when the question expires. It only says what happened. The platform's example adds "Carry on without it.";
# this text doesn't, because that pushes the model to decide without the answer. What to do then is the system prompt's rule.
NO_ANSWER = "No answer came before the question expired, so it was cancelled."


def plain_context(_, new):
    """The bridge's "ag-ui" keys, with each context entry as a plain dict. The bridge passes AG-UI's Context objects, which the
    checkpointer can't store."""
    new = dict(new or {})
    new["context"] = [c if isinstance(c, dict) else {"description": getattr(c, "description", None), "value": getattr(c, "value", None)}
                      for c in new.get("context") or []]
    return new


class State(MessagesState, TypedDict("AgUi", {"ag-ui": Annotated[dict, plain_context]}, total=False)):
    tools: list   # the client-side tools: RunAgentInput.tools, as the bridge copies them


def system_prompt(state):
    """The AG-UI run's context as one system message for the model ([] when there is none)."""
    text = "\n\n".join(str(c.get("value") or "") for c in (state.get("ag-ui") or {}).get("context") or []).strip()
    return [SystemMessage(text)] if text else []


def client_side(state):
    """The names of the client-side tools of this AG-UI run."""
    return {t["name"] for t in state.get("tools") or []}


def chat_model():
    model = os.environ["AGENT_MODEL"]
    if os.environ.get("AGENT_MODEL_FORMAT") == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=model, use_responses_api=False)   # chat completions: the format OpenAI-compatible models speak too


async def relay_tools():
    """Every tool the relay lists, under the relay's names (no prefix)."""
    if not _relay:
        client = MultiServerMCPClient({"domino": {
            "transport": "streamable_http", "url": os.environ["AGENT_SERVICE_URL"] + "/mcp",
            "headers": {"Authorization": "Bearer " + os.environ["SESSION_TOKEN"]},
            "timeout": CONNECT_TIMEOUT, "sse_read_timeout": READ_TIMEOUT}})
        _relay.extend(await client.get_tools())
    return _relay


def pending(state):
    """The last answer's tool calls that have no result yet."""
    msgs = state["messages"]
    i = next((i for i in range(len(msgs) - 1, -1, -1) if isinstance(msgs[i], AIMessage)), None)
    if i is None:
        return []
    done = {m.tool_call_id for m in msgs[i + 1:] if isinstance(m, ToolMessage)}
    return [c for c in msgs[i].tool_calls if c["id"] not in done]


def route(state):
    """What runs next: the relay for the open agent-side calls, then the question; the end of the run while client-side calls are
    open; else the model again after a new message or result, or the end of the run after its answer."""
    calls, client = pending(state), client_side(state)
    if any(c["name"] not in client and c["name"] != ASK for c in calls):
        return "relay"
    if any(c["name"] == ASK for c in calls):
        return "ask_human"
    if calls:   # client-side calls only: the platform answers them in a later AG-UI run
        return END
    return END if isinstance(state["messages"][-1], AIMessage) else "agent"


async def agent(state):
    """One model call, with every tool the model can use."""
    client, names = state.get("tools") or [], client_side(state)
    tools = [t for t in await relay_tools() if t.name not in names] + [
        {"type": "function", "function": {"name": t["name"], "description": t.get("description") or "",
                                          "parameters": t.get("parameters") or {"type": "object", "properties": {}}}} for t in client]
    model = chat_model().bind_tools(tools + [ASK_HUMAN])
    return {"messages": [await model.ainvoke(system_prompt(state) + state["messages"])]}


async def relay(state):
    """Each open agent-side call, through the relay. ainvoke with the call gives the ToolMessage (a tool error, such as a denial,
    is a ToolMessage too), and the bridge sends it as the call's result."""
    tools, client = {t.name: t for t in await relay_tools()}, client_side(state)
    out = []
    for call in pending(state):
        if call["name"] in client or call["name"] == ASK:
            continue
        if call["name"] in tools:
            out.append(await tools[call["name"]].ainvoke(call))
        else:
            out.append(ToolMessage(f"There is no tool named {call['name']}.", tool_call_id=call["id"], status="error"))
    return {"messages": out}


def ask_human(state):
    """The question, as one interrupt. On the resume this node runs again from its start, and interrupt() returns the answer."""
    call = next(c for c in pending(state) if c["name"] == ASK)
    args = call["args"] or {}
    answer = interrupt({"reason": ASK, "message": str(args.get("question") or ""),
                        **({"expiresAt": args["expires_at"]} if args.get("expires_at") else {})})
    if isinstance(answer, dict) and answer.get(CANCELLED):
        answer = NO_ANSWER
    return {"messages": [ToolMessage(str(answer), tool_call_id=call["id"], name=ASK)]}


def build_graph(checkpointer):
    """The compiled graph, with the checkpointer that the platform's adapter gives (its thread lives in the state folder)."""
    g = StateGraph(State)
    g.add_node("agent", agent)
    g.add_node("relay", relay)
    g.add_node("ask_human", ask_human)
    for node in (START, "agent", "relay", "ask_human"):
        g.add_conditional_edges(node, route, ["agent", "relay", "ask_human", END])
    return g.compile(checkpointer=checkpointer)
