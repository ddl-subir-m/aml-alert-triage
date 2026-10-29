"""Case server check: the case-management system, seen by an MCP client over streamable HTTP.

Each group starts the server as its own process with a temporary AML_DB_PATH, and calls it the way the platform
does: MCP over streamable HTTP. No case reads the server's tables.

  TOOLS  the tool list
  ALERT  get_alert
  SEED   the seed loads only into an empty state file; a restart keeps the state
  START  the server refuses to start without its state folder
  APP    the Domino App's start script (app.sh)

Run: .venv/bin/python tests/check_case_server.py
Exit code: 0 all passed, 1 any failed. The server logs stay in the temporary folder that the last line names.
"""
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "case_server" / "server.py"
ROOT = Path(tempfile.mkdtemp(prefix="aml-check-"))
failed = []

signal.signal(signal.SIGTERM, lambda *a: sys.exit(1))  # a check stopped from outside still stops its servers


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{str(detail)[:600]}]" if detail and not ok else ""), flush=True)
    if not ok:
        failed.append(name)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def server_env(**env):
    """This process's environment with a free local port, and the changes in env. A value of None unsets a variable."""
    env = {**os.environ, "HOST": "127.0.0.1", "PORT": str(free_port()), **env}
    return {k: v for k, v in env.items() if v is not None}


def stop(p):
    p.terminate()
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()


@contextmanager
def server(db, cmd=None, **env):
    """The server running on the state file db (None: AML_DB_PATH unset) -> its base URL.
    It stops at the end of the block, so the next start can open the same file."""
    env = server_env(AML_DB_PATH=str(db) if db else None, **env)
    log = ROOT / f"server-{env['PORT']}.log"
    p = subprocess.Popen(cmd or [sys.executable, str(SERVER)], env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT)
    try:
        end = time.monotonic() + 30
        while True:
            try:
                socket.create_connection(("127.0.0.1", int(env["PORT"])), timeout=0.5).close()
                break
            except OSError:
                if p.poll() is not None or time.monotonic() > end:
                    raise RuntimeError(f"the server did not start: {log.read_text()[-600:]}")
                time.sleep(0.1)
        yield f"http://127.0.0.1:{env['PORT']}"
    finally:
        stop(p)


def run_to_exit(cmd, **env):
    """Run a server that must refuse to start -> CompletedProcess, with stdout and stderr together in stdout."""
    return subprocess.run(cmd, env=server_env(**env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)


async def _call(base, tool, args, user):
    headers = {"domino-username": user} if user else {}
    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30, read=60)) as hc:
        async with streamable_http_client(f"{base}/mcp", http_client=hc) as (read, write, _):
            async with ClientSession(read, write) as s:
                await s.initialize()
                if tool is None:
                    return [t.name for t in (await s.list_tools()).tools]
                return await s.call_tool(tool, args)


def tools(base):
    """The names of the server's MCP tools."""
    return asyncio.run(_call(base, None, None, None))


def call(base, tool, args=None, user=None):
    """Call one tool, as the Apps proxy would name user in domino-username -> (is_error, answer).
    The answer is the structured result, or else the text (an error's reason)."""
    res = asyncio.run(_call(base, tool, args or {}, user))
    text = res.content[0].text if res.content else ""
    return res.isError, (res.structuredContent if res.structuredContent is not None else text)


def new_state(name, empty_file=False):
    """A state file in a new folder of its own. The file doesn't exist yet, or is empty."""
    db = ROOT / name / "cases.db"
    db.parent.mkdir()
    if empty_file:
        db.touch()
    return db


# One function for each group of cases. Each group starts its own servers on its own state.

def check_alert():
    with server(new_state("alert")) as base:
        names = tools(base)
        check("TOOLS the server lists get_alert", "get_alert" in names, names)

        err, alert = call(base, "get_alert", {"alert_id": "A-1001"})
        check("ALERT get_alert answers alert 1: its customer, rule, score, status and flagged transaction IDs",
              not err and alert == {"alert_id": "A-1001", "customer_id": "C-2001", "rule": "large_amount", "score": 0.42,
                                    "status": "open", "flagged_transaction_ids": ["T-30001", "T-30002", "T-30003"]}, alert)

        err, why = call(base, "get_alert", {"alert_id": "A-404"})
        check("ALERT an unknown alert ID is a tool error that names the ID", err and "No alert A-404" in str(why), (err, why))


def check_seed():
    # A seed that differs from the one in git (AML_SEED_PATH): an answer shows which seed its state file got.
    other_seed = json.loads((REPO / "case_server" / "seed.json").read_text())
    next(a for a in other_seed["alerts"] if a["alert_id"] == "A-1001")["score"] = 0.99
    (ROOT / "other-seed.json").write_text(json.dumps(other_seed))

    with server(new_state("seed-empty-file", empty_file=True)) as base:
        err, alert = call(base, "get_alert", {"alert_id": "A-1001"})
        check("SEED an empty state file gets the seed", not err and alert.get("score") == 0.42, alert)

    db = new_state("seed-restart")
    with server(db, AML_SEED_PATH=str(ROOT / "other-seed.json")) as base:
        err, alert = call(base, "get_alert", {"alert_id": "A-1001"})
        check("SEED a new state file gets the seed", not err and alert.get("score") == 0.99, alert)

    with server(db) as base:
        err, alert = call(base, "get_alert", {"alert_id": "A-1001"})
        check("SEED ... a restart keeps the state, and doesn't load the seed again", not err and alert.get("score") == 0.99, alert)


def check_start():
    missing = ROOT / "no-such-folder"
    out = run_to_exit([sys.executable, str(SERVER)], AML_DB_PATH=str(missing / "cases.db"))
    check("START a missing state folder stops the server with a message that names the folder and the dataset aml-cases",
          out.returncode != 0 and str(missing) in out.stdout and "dataset aml-cases" in out.stdout, (out.returncode, out.stdout[-600:]))

    out = run_to_exit([sys.executable, str(SERVER)], AML_DB_PATH=None)
    check("START with no AML_DB_PATH the server stops and says to set it",
          out.returncode != 0 and "Set AML_DB_PATH" in out.stdout and "Traceback" not in out.stdout, (out.returncode, out.stdout[-600:]))


def check_app_script():
    # The Domino App's start script, with the python that runs this check first on the PATH.
    app = ["bash", str(REPO / "app.sh")]
    path = f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
    no_dataset = ROOT / "datasets-without-aml-cases"
    no_dataset.mkdir()
    out = run_to_exit(app, AML_DB_PATH=None, DOMINO_DATASETS_DIR=str(no_dataset), PATH=path)
    check("APP the start script keeps the state on the dataset aml-cases, and stops when the dataset is missing",
          out.returncode != 0 and str(no_dataset / "aml-cases") in out.stdout, (out.returncode, out.stdout[-600:]))

    datasets = ROOT / "datasets"
    (datasets / "aml-cases").mkdir(parents=True)
    with server(None, app, DOMINO_DATASETS_DIR=str(datasets), PATH=path) as base:
        err, alert = call(base, "get_alert", {"alert_id": "A-1001"})
        check("APP ... with the dataset, the start script serves the case-management system",
              not err and alert.get("alert_id") == "A-1001", alert)


for group in (check_alert, check_seed, check_start, check_app_script):
    try:
        group()
    except Exception as e:  # a case that can't run is a failure, never a skip
        check(f"{group.__name__} ran to the end", False, f"{type(e).__name__}: {e}")

print(f"\n{len(failed)} failed: {', '.join(failed)}  (server logs in {ROOT})" if failed else "\nall checks passed")
sys.exit(1 if failed else 0)
