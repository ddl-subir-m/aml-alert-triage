"""Case server check: the case-management system, seen by an MCP client over streamable HTTP.

Each group starts the server as its own process with a temporary AML_DB_PATH, and calls it the way the platform
does: MCP over streamable HTTP. No case reads the server's tables.

  TOOLS    the tool list
  ALERT    get_alert, with alert 4 closed in the seed
  PROFILE  get_customer_profile
  TXNS     get_transactions and its window of days
  DATA     the seed's four alerts: the evidence shows each one's pattern
  SEED     the seed loads only into an empty state file; a restart keeps the state
  START    the server refuses to start without its state folder
  APP      the Domino App's start script (app.sh)

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
from datetime import date, datetime, timedelta, timezone
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


def days_ago(n):
    """The date n days before today (UTC), as the case-management system writes dates: 2026-10-25."""
    return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()


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

        err, alert = call(base, "get_alert", {"alert_id": "A-1004"})
        acted_at = alert.get("acted_at", "") if not err else ""
        check("ALERT get_alert answers alert 4, closed in the seed: who acted, when (12 days before the load, in UTC), "
              "its reason code and its rationale",
              not err and {k: v for k, v in alert.items() if k != "acted_at"} == {
                  "alert_id": "A-1004", "customer_id": "C-2004", "rule": "large_amount", "score": 0.35, "status": "closed",
                  "flagged_transaction_ids": ["T-30041"], "acted_by": "jordan.reyes", "reason_code": "explained_activity",
                  "rationale": "The customer sold her car to a dealer. The deposit matches the bill of sale on file."}
              and acted_at.startswith(days_ago(12) + "T") and acted_at.endswith("Z"), alert)


def check_profile():
    with server(new_state("profile")) as base:
        check("TOOLS the server lists get_customer_profile", "get_customer_profile" in tools(base))

        err, profile = call(base, "get_customer_profile", {"customer_id": "C-2001"})
        check("PROFILE get_customer_profile answers alert 1's customer: name, segment, KYC risk rating, occupation, "
              "expected monthly activity, country and PEP flag",
              not err and profile == {"customer_id": "C-2001", "name": "Dana Whitfield", "segment": "retail",
                                      "kyc_risk_rating": "low", "occupation": "Software engineer at a logistics company",
                                      "expected_monthly_activity_usd": 14000, "country": "US", "pep": False}, profile)

        err, why = call(base, "get_customer_profile", {"customer_id": "C-404"})
        check("PROFILE an unknown customer ID is a tool error that names the ID",
              err and "No customer C-404" in str(why), (err, why))


def check_transactions():
    with server(new_state("transactions")) as base:
        check("TOOLS the server lists get_transactions", "get_transactions" in tools(base))

        err, answer = call(base, "get_transactions", {"customer_id": "C-2001"})
        listed = answer.get("transactions", []) if not err else []
        payroll = next((t for t in listed if t.get("transaction_id") == "T-30001"), None)
        check("TXNS get_transactions answers each transaction with its ID, date, amount, currency, type, counterparty, "
              "country and memo; the seed's 4 days ago is a date 4 days before today",
              payroll == {"transaction_id": "T-30001", "date": days_ago(4), "amount": 11850, "currency": "USD",
                          "type": "ach_credit", "counterparty": "Northwind Logistics Inc", "country": "US",
                          "memo": "PAYROLL NORTHWIND LOGISTICS"}, answer)

        ids = [t.get("transaction_id") for t in listed]
        check("TXNS ... by default, the transactions of the last 90 days, without the payroll deposit of 94 days ago",
              not err and answer.get("days") == 90 and answer.get("customer_id") == "C-2001"
              and set(ids) == {"T-30001", "T-30002", "T-30003", "T-30005", "T-30006", "T-30007", "T-30008"}, answer)
        dates = [t["date"] for t in listed]
        check("TXNS ... oldest first", len(dates) > 1 and dates == sorted(dates), ids)

        err, answer = call(base, "get_transactions", {"customer_id": "C-2001", "days": 120})
        check("TXNS ... a 120-day window has the payroll deposit of 94 days ago",
              not err and any(t.get("transaction_id") == "T-30004" and t.get("date") == days_ago(94)
                              for t in answer.get("transactions", [])), answer)

        err, why = call(base, "get_transactions", {"customer_id": "C-404"})
        check("TXNS an unknown customer ID is a tool error that names the ID",
              err and "No customer C-404" in str(why), (err, why))

        err, why = call(base, "get_transactions", {"customer_id": "C-2001", "days": 0})
        check("TXNS a window of 0 days is a tool error that says what days can be",
              err and "days must be" in str(why), (err, why))


def evidence(base, alert_id):
    """What the agent reads for one alert -> (the alert, its customer's profile, its flagged transactions that the 90-day
    window lists, the customer's other transactions in the window)."""
    answers = []
    for tool, args in (("get_alert", {"alert_id": alert_id}), ("get_customer_profile", None), ("get_transactions", None)):
        err, answer = call(base, tool, args or {"customer_id": answers[0]["customer_id"]})
        if err:
            raise RuntimeError(f"{tool} for {alert_id}: {answer}")
        answers.append(answer)
    alert, profile, window = answers
    flagged = [t for t in window["transactions"] if t["transaction_id"] in alert["flagged_transaction_ids"]]
    others = [t for t in window["transactions"] if t["transaction_id"] not in alert["flagged_transaction_ids"]]
    return alert, profile, flagged, others


def check_seeded_alerts():
    # The four alerts of spec #1. The agent's judgment isn't checked here: only that the evidence shows each pattern.
    with server(new_state("seeded-alerts")) as base:
        seen = {a: evidence(base, a) for a in ("A-1001", "A-1002", "A-1003", "A-1004")}
        check("DATA each alert's flagged transactions belong to its customer, in the 90-day window",
              all(len(flagged) == len(alert["flagged_transaction_ids"]) > 0 for alert, _, flagged, _ in seen.values()),
              {a: (alert["flagged_transaction_ids"], [t["transaction_id"] for t in flagged])
               for a, (alert, _, flagged, _) in seen.items()})

        alert, profile, flagged, _ = seen["A-1001"]
        dates = sorted(date.fromisoformat(t["date"]) for t in flagged)
        check("DATA alert 1 is a clear false positive: a large-amount rule flagged regular salary deposits (one payer, one "
              "amount, a month apart, within the profile's expected monthly activity)",
              alert["status"] == "open" and alert["rule"] == "large_amount" and len(flagged) >= 3
              and len({(t["type"], t["counterparty"], t["amount"]) for t in flagged}) == 1
              and all("PAYROLL" in t["memo"] for t in flagged)
              and all(10000 < t["amount"] <= profile["expected_monthly_activity_usd"] for t in flagged)
              and all(28 <= (b - a).days <= 31 for a, b in zip(dates, dates[1:])), (alert, profile, flagged))

        alert, profile, flagged, _ = seen["A-1002"]
        dates = [date.fromisoformat(t["date"]) for t in flagged]
        check("DATA alert 2 is structuring: 6 or more cash deposits just under 10,000 within 14 days, more than 5 times "
              "the profile's expected monthly activity",
              alert["status"] == "open" and alert["rule"] == "structuring" and len(flagged) >= 6
              and all(t["type"] == "cash_deposit" and 9000 <= t["amount"] < 10000 for t in flagged)
              and (max(dates) - min(dates)).days <= 14
              and sum(t["amount"] for t in flagged) > 5 * profile["expected_monthly_activity_usd"], (alert, profile, flagged))

        alert, profile, flagged, others = seen["A-1003"]
        check("DATA alert 3 is unclear: one large outgoing wire to a country that the customer's profile and other "
              "transactions don't have",
              alert["status"] == "open" and len(flagged) == 1 and flagged[0]["type"] == "wire_out"
              and flagged[0]["amount"] > 2 * profile["expected_monthly_activity_usd"] and len(others) >= 3
              and flagged[0]["country"] not in {profile["country"]} | {t["country"] for t in others},
              (alert, profile, flagged, others))


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


for group in (check_alert, check_profile, check_transactions, check_seeded_alerts, check_seed, check_start,
              check_app_script):
    try:
        group()
    except Exception as e:  # a case that can't run is a failure, never a skip
        check(f"{group.__name__} ran to the end", False, f"{type(e).__name__}: {e}")

print(f"\n{len(failed)} failed: {', '.join(failed)}  (server logs in {ROOT})" if failed else "\nall checks passed")
sys.exit(1 if failed else 0)
