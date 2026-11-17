"""A probe for the App validation demo, not the validator itself. It is the ready-made LangGraph graph of domino-agui (level 2) with four
own tools, to check what the framework lane has not done before:

1. An own tool reads the project's files in the sandbox (list_files, read_file).
2. The model calls the gateway tools run_job, wait_job and get_job_logs through the relay: a Job that runs pip-audit and bandit.
3. An own tool calls a gateway tool from code, not the model (run_from_code: run_job through relay_tools()).
4. An own tool writes a file in the project folder (write_file). The framework lane has no git push in v1, so the file stays in the Job.

The entry point is governance/probe/graph.py:build_graph. The definition is governance/probe/agent.json. The data is fake.
"""
from pathlib import Path

from domino_agui import contract
from domino_agui.langgraph import agent, relay_tools

ROOT = Path(__file__).resolve().parents[2]   # the project's root: this file is governance/probe/graph.py
SKIP = {".git", "__pycache__", ".venv", "node_modules"}
REPORTS = "governance/reports/"
LIMIT = 200


def _inside(path: str) -> Path:
    p = (ROOT / path).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise ValueError(f"{path!r} is outside the project folder")
    return p


def list_files(folder: str = ".") -> str:
    """The files under a folder of the project, as paths relative to the project's root, one on each line (at most 200)."""
    base = _inside(folder)
    files = sorted(str(p.relative_to(ROOT)) for p in base.rglob("*")
                   if p.is_file() and not SKIP & set(p.relative_to(ROOT).parts))
    if not files:
        return f"No files under {folder}"
    more = f"\n... and {len(files) - LIMIT} more" if len(files) > LIMIT else ""
    return "\n".join(files[:LIMIT]) + more


def read_file(path: str, max_chars: int = 20000) -> str:
    """The text of one project file, by its path relative to the project's root (at most max_chars characters)."""
    text = _inside(path).read_text(errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n... cut at {max_chars} of {len(text)} characters"
    return text


def write_file(path: str, text: str) -> str:
    """Writes a text file under governance/reports/ in the project folder. The file stays in this Job: the framework lane can't push."""
    if not path.startswith(REPORTS) or ".." in Path(path).parts:
        raise ValueError(f"write only under {REPORTS}, not {path!r}")
    p = _inside(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return f"wrote {len(text.encode())} bytes to {path}"


async def run_from_code(command: str = "echo started-from-code") -> str:
    """Starts a Domino job with this command by calling the gateway tool run_job from this code, not from the model. Returns run_job's
    answer (the job ID), or why it could not."""
    tools = {t.name: t for t in await relay_tools()}
    if "run_job" not in tools:
        return "The relay lists no run_job tool. It lists: " + ", ".join(sorted(tools))
    answer = await tools["run_job"].ainvoke({"command": command, "title": "probe: run_job from code"})
    return str(answer)


def probe_model(max_tokens=16000):
    """The ready-made chat model, with room to answer. ChatAnthropic gives an alias that has no model profile (such as "sonnet") only
    4,096 output tokens, and the probe's second answer ran out of them twice (AGT-112, AGT-113: the same 9,379 tokens each time)."""
    if contract.alias_format() == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=contract.model_alias(), max_tokens=max_tokens)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=contract.model_alias(), use_responses_api=False, max_tokens=max_tokens)


build_graph = agent(model=probe_model(), tools=[list_files, read_file, write_file, run_from_code])
