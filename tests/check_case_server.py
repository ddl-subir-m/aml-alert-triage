"""Case server check: the case-management system, seen by an MCP client over streamable HTTP.

Each group starts the server as its own process with a temporary AML_DB_PATH, and calls it the way the platform
does: MCP over streamable HTTP. No case reads the server's tables.

  TOOLS    the tool list: three reads, two writes, and no reset
  ALERT    get_alert, with alert 4 closed in the seed
  PROFILE  get_customer_profile
  TXNS     get_transactions and its window of days
  CLOSE    close_alert and its reason codes
  ESC      escalate_to_sar: a SAR case, and transaction IDs of the alert's customer only
  STATUS   open moves to closed or to escalated, and both are final ("already escalated" is an answer, not an error)
  WHO      who acted: the domino-username header, and the record when it is missing, empty or Anonymous
  RESTART  a SAR case and a close survive a restart of the server
  RESET    POST /reset loads the seed again, also on a state file from an older build
  DATA     the seed's four alerts: the evidence shows each one's pattern
  SEED     the seed loads only into an empty state file; a restart keeps the state
  START    the server refuses to start without its state folder
  APP      the Domino App's start script (app.sh)

  python tests/check_case_server.py

Exit code: 0 all passed, 1 any failed. When a case fails, the server logs stay in the temporary folder that the last line
names. When all pass, the check deletes that folder.
"""
import asyncio
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
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
    headers = {"domino-username": user} if user is not None else {}
    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30, read=60)) as hc:
        async with streamable_http_client(f"{base}/mcp", http_client=hc) as (read, write, _):
            async with ClientSession(read, write) as s:
                await s.initialize()
                if tool is None:
                    return [t.name for t in (await s.list_tools()).tools]
                return await s.call_tool(tool, args)


def tools(base):
    """The names of the server's tools."""
    return asyncio.run(_call(base, None, None, None))


def call(base, tool, args=None, user=None):
    """Call one tool, as the Apps proxy would name user in domino-username (None: no such header) -> (is_error, answer).
    The answer is the structured result, or else the text (an error's reason)."""
    res = asyncio.run(_call(base, tool, args or {}, user))
    text = res.content[0].text if res.content else ""
    return res.isError, (res.structuredContent if res.structuredContent is not None else text)


def reset(base):
    """POST /reset -> (HTTP status, the answer's JSON or text)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{base}/reset", data=b"", method="POST"), timeout=30) as r:
            status, body = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode()
    try:
        return status, json.loads(body)
    except ValueError:
        return status, body


def new_state(name, empty_file=False):
    """A state file in a new folder of its own. The file doesn't exist yet, or is empty."""
    db = ROOT / name / "cases.db"
    db.parent.mkdir()
    if empty_file:
        db.touch()
    return db


def just_now(when):
    """True when `when` is a UTC time of the last minute, written as the case-management system writes times."""
    try:
        t = datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    return timedelta(0) <= datetime.now(timezone.utc) - t < timedelta(minutes=1)


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


ALERT_1 = {"alert_id": "A-1001", "customer_id": "C-2001", "rule": "large_amount", "score": 0.42,
           "flagged_transaction_ids": ["T-30001", "T-30002", "T-30003"]}


def check_close():
    with server(new_state("close")) as base:
        check("TOOLS the server lists close_alert", "close_alert" in tools(base))

        rationale = "Monthly payroll from the customer's employer, within the profile's expected activity."
        err, alert = call(base, "close_alert", {"alert_id": "A-1001", "reason_code": "false_positive", "rationale": rationale},
                          user="olivia.analyst")
        when = alert.get("acted_at") if not err else None
        check("CLOSE close_alert closes an open alert and answers with the closed alert: who acted (the domino-username "
              "header), when (now, UTC), the reason code and the rationale",
              not err and {k: v for k, v in alert.items() if k != "acted_at"} == {
                  **ALERT_1, "status": "closed", "acted_by": "olivia.analyst", "reason_code": "false_positive",
                  "rationale": rationale} and just_now(when), alert)
        err, again = call(base, "get_alert", {"alert_id": "A-1001"})
        check("CLOSE ... get_alert shows the same closed alert", not err and again == alert, again)

        err, why = call(base, "close_alert", {"alert_id": "A-1003", "reason_code": "looks_fine", "rationale": "x"})
        check("CLOSE a reason code that isn't false_positive, explained_activity or duplicate is a tool error that names "
              "the three", err and all(c in str(why) for c in ("looks_fine", "false_positive", "explained_activity",
                                                                 "duplicate")), (err, why))
        err, why = call(base, "close_alert", {"alert_id": "A-1003", "reason_code": "duplicate", "rationale": "  "})
        check("CLOSE an empty rationale is a tool error that says why", err and "rationale" in str(why), (err, why))
        err, why = call(base, "close_alert", {"alert_id": "A-404", "reason_code": "duplicate", "rationale": "x"})
        check("CLOSE an unknown alert ID is a tool error that names the ID", err and "No alert A-404" in str(why), (err, why))
        err, alert = call(base, "get_alert", {"alert_id": "A-1003"})
        check("CLOSE ... after those refusals, the alert is still open", not err and alert.get("status") == "open", alert)

        err, alert = call(base, "close_alert", {"alert_id": "A-1003", "reason_code": "explained_activity",
                                                "rationale": "The analyst confirmed the contract."}, user="olivia.analyst")
        check("CLOSE explained_activity closes an alert too", not err and alert.get("reason_code") == "explained_activity", alert)
        with server(new_state("close-duplicate")) as other:
            err, alert = call(other, "close_alert", {"alert_id": "A-1002", "reason_code": "duplicate",
                                                     "rationale": "The same deposits as an earlier alert."})
            check("CLOSE duplicate closes an alert too", not err and alert.get("reason_code") == "duplicate", alert)

        err, why = call(base, "close_alert", {"alert_id": "A-1001", "reason_code": "duplicate", "rationale": "Again."},
                        user="sam.other")
        check("STATUS close_alert on a closed alert is a tool error that says it is closed, and by whom",
              err and "A-1001" in str(why) and "closed" in str(why) and "olivia.analyst" in str(why), (err, why))
        err, alert = call(base, "get_alert", {"alert_id": "A-1001"})
        check("STATUS ... and the first close stands", not err and alert.get("reason_code") == "false_positive"
              and alert.get("acted_by") == "olivia.analyst", alert)
        err, why = call(base, "close_alert", {"alert_id": "A-1004", "reason_code": "false_positive", "rationale": "x"})
        err4, alert = call(base, "get_alert", {"alert_id": "A-1004"})
        check("STATUS close_alert on alert 4 (closed in the seed) is a tool error, and alert 4 doesn't change",
              err and "A-1004" in str(why) and "closed" in str(why) and not err4 and alert.get("acted_by") == "jordan.reyes"
              and alert.get("reason_code") == "explained_activity", (why, alert))


ALERT_2 = {"alert_id": "A-1002", "customer_id": "C-2002", "rule": "structuring", "score": 0.91,
           "flagged_transaction_ids": ["T-30015", "T-30016", "T-30017", "T-30018", "T-30019", "T-30020", "T-30021", "T-30022"]}
NARRATIVE = "Eight cash deposits from 9,400 to 9,900 in eight days, at four places, far above the expected activity."


def escalate(base, alert_id="A-1002", narrative=NARRATIVE, transaction_ids=None, user="olivia.analyst"):
    """escalate_to_sar on an alert, by default alert 2 with its flagged transactions -> (is_error, answer)."""
    return call(base, "escalate_to_sar", {"alert_id": alert_id, "narrative": narrative,
                                          "transaction_ids": ALERT_2["flagged_transaction_ids"] if transaction_ids is None
                                          else transaction_ids}, user=user)


def check_escalate():
    with server(new_state("escalate")) as base:
        check("TOOLS the server lists escalate_to_sar", "escalate_to_sar" in tools(base))

        err, sar_case = escalate(base)
        sar_case = sar_case if not err else {}
        sar_case_id = sar_case.get("sar_case_id", "")
        check("ESC escalate_to_sar opens a SAR case for an open alert and answers with its ID (SAR-<number>), who opened "
              "it (the domino-username header) and when (now, UTC)",
              not err and sar_case.get("result") == "escalated" and sar_case_id.startswith("SAR-") and sar_case_id[4:].isdigit()
              and {k: v for k, v in sar_case.items() if k not in ("sar_case_id", "opened_at", "result")} == {
                  "alert_id": "A-1002", "narrative": NARRATIVE, "transaction_ids": ALERT_2["flagged_transaction_ids"],
                  "opened_by": "olivia.analyst"} and just_now(sar_case.get("opened_at")), sar_case)
        err, alert = call(base, "get_alert", {"alert_id": "A-1002"})
        check("ESC ... get_alert shows the alert escalated: who acted, when, and the SAR case ID",
              not err and alert == {**ALERT_2, "status": "escalated", "acted_by": "olivia.analyst",
                                    "acted_at": sar_case.get("opened_at"), "sar_case_id": sar_case_id}, alert)

        err, again = escalate(base, narrative="A second narrative.", transaction_ids=["T-30015"], user="sam.other")
        check("STATUS a second escalate_to_sar on an escalated alert isn't an error: it answers with the first SAR case "
              "(its ID, narrative, transactions, who and when) and \"already escalated\"",
              not err and again == {**sar_case, "result": "already escalated"}, again)
        err, alert = call(base, "get_alert", {"alert_id": "A-1002"})
        check("STATUS ... and opens no second SAR case: the alert still names the first one, and who opened it",
              not err and alert.get("sar_case_id") == sar_case_id and alert.get("acted_by") == "olivia.analyst", alert)

        err, why = call(base, "close_alert", {"alert_id": "A-1002", "reason_code": "false_positive", "rationale": "x"})
        err2, alert = call(base, "get_alert", {"alert_id": "A-1002"})
        check("STATUS close_alert on an escalated alert is a tool error that names its SAR case, and the alert stays "
              "escalated", err and "escalated" in str(why) and sar_case_id in str(why) and not err2
              and alert.get("status") == "escalated", (why, alert))

        err, why = escalate(base, alert_id="A-1004", transaction_ids=["T-30041"])
        check("STATUS escalate_to_sar on a closed alert (alert 4) is a tool error that says it is closed",
              err and "A-1004" in str(why) and "closed" in str(why), (err, why))
        call(base, "close_alert", {"alert_id": "A-1001", "reason_code": "false_positive", "rationale": "Payroll."})
        err, why = escalate(base, alert_id="A-1001", transaction_ids=["T-30001"])
        err2, alert = call(base, "get_alert", {"alert_id": "A-1001"})
        check("STATUS escalate_to_sar on an alert that close_alert closed is a tool error, and the alert stays closed",
              err and "closed" in str(why) and not err2 and alert.get("status") == "closed"
              and "sar_case_id" not in alert, (why, alert))

        err, why = escalate(base, alert_id="A-1003", transaction_ids=["T-30037", "T-30001"])
        check("ESC a transaction ID of another customer is a tool error that names the ID and the alert's customer",
              err and "T-30001" in str(why) and "C-2003" in str(why) and "T-30037" not in str(why), (err, why))
        err, why = escalate(base, alert_id="A-1003", transaction_ids=["T-99999"])
        check("ESC an unknown transaction ID is a tool error that names the ID", err and "T-99999" in str(why), (err, why))
        err, why = escalate(base, alert_id="A-1003", transaction_ids=[])
        check("ESC an empty list of transaction IDs is a tool error that says why",
              err and "transaction" in str(why).lower(), (err, why))
        err, why = escalate(base, alert_id="A-1003", narrative=" ", transaction_ids=["T-30037"])
        check("ESC an empty narrative is a tool error that says why", err and "narrative" in str(why), (err, why))
        err, why = escalate(base, alert_id="A-404", transaction_ids=["T-30037"])
        check("ESC an unknown alert ID is a tool error that names the ID", err and "No alert A-404" in str(why), (err, why))
        err, alert = call(base, "get_alert", {"alert_id": "A-1003"})
        check("ESC ... after those refusals, the alert is still open", not err and alert.get("status") == "open", alert)

        err, next_sar_case = escalate(base, alert_id="A-1003", transaction_ids=["T-30037"])
        check("ESC the next SAR case has the next ID", not err and next_sar_case.get("result") == "escalated"
              and next_sar_case.get("sar_case_id") == f"SAR-{int(sar_case_id[4:]) + 1}", (sar_case_id, next_sar_case))


def check_who_acted():
    # The Apps proxy names the acting identity in domino-username. A local run sends no such header; a missing, empty or
    # Anonymous one is no identity, and the record says so (and why), so a missing name never looks like a person.
    with server(new_state("who-acted")) as base:
        err, alert = call(base, "close_alert", {"alert_id": "A-1001", "reason_code": "false_positive", "rationale": "Payroll."})
        who = alert.get("acted_by") if not err else None
        check("WHO a close with no domino-username header (a local run) records no identity, and says the header was "
              "missing", isinstance(who, str) and who.startswith("no identity") and "no domino-username header" in who,
              (err, alert))
        err, again = call(base, "get_alert", {"alert_id": "A-1001"})
        check("WHO ... get_alert shows the same record", not err and again.get("acted_by") == who and just_now(again.get("acted_at")),
              again)

        err, sar_case = escalate(base, user="")
        who = sar_case.get("opened_by") if not err else None
        check("WHO a SAR case with an empty domino-username header records no identity, and says the header was empty",
              isinstance(who, str) and who.startswith("no identity") and "empty" in who, (err, sar_case))
        err, alert = call(base, "get_alert", {"alert_id": "A-1002"})
        check("WHO ... get_alert shows the same record", not err and alert.get("acted_by") == who, alert)

        err, sar_case = escalate(base, alert_id="A-1003", transaction_ids=["T-30037"], user="Anonymous")
        who = sar_case.get("opened_by") if not err else None
        check("WHO a SAR case as Anonymous records no identity, and says the header was Anonymous",
              isinstance(who, str) and who.startswith("no identity") and "Anonymous" in who, (err, sar_case))


def check_restart():
    db = new_state("restart")
    with server(db) as base:
        err, sar_case = escalate(base)
        err2, closed = call(base, "close_alert", {"alert_id": "A-1001", "reason_code": "false_positive", "rationale": "Payroll."},
                            user="olivia.analyst")
        if err or err2:
            raise RuntimeError(f"the writes before the restart failed: {sar_case} {closed}")

    with server(db) as base:
        err, alert = call(base, "get_alert", {"alert_id": "A-1002"})
        check("RESTART a SAR case survives a restart of the server: the alert is still escalated to it, with who and when",
              not err and alert == {**ALERT_2, "status": "escalated", "acted_by": "olivia.analyst",
                                    "acted_at": sar_case["opened_at"], "sar_case_id": sar_case["sar_case_id"]}, alert)
        err, again = escalate(base, narrative="After the restart.", user="sam.other")
        check("RESTART ... and a second escalate_to_sar after the restart answers with that SAR case and \"already escalated\"",
              not err and again == {**sar_case, "result": "already escalated"}, again)
        err, alert = call(base, "get_alert", {"alert_id": "A-1001"})
        check("RESTART a closed alert survives a restart too", not err and alert == closed, alert)


def check_reset():
    with server(new_state("reset")) as base:
        names = tools(base)
        check("TOOLS the server lists the five tools (three reads, two writes) and no reset",
              sorted(names) == ["close_alert", "escalate_to_sar", "get_alert", "get_customer_profile", "get_transactions"],
              names)

        err, sar_case = escalate(base)
        call(base, "close_alert", {"alert_id": "A-1001", "reason_code": "false_positive", "rationale": "Payroll."})
        call(base, "close_alert", {"alert_id": "A-1003", "reason_code": "duplicate", "rationale": "Seen before."})
        if err:
            raise RuntimeError(f"the escalation before the reset failed: {sar_case}")

        status, answer = reset(base)
        check("RESET POST /reset answers 200 with each alert's status in the seed",
              status == 200 and isinstance(answer, dict) and answer.get("alerts") == {
                  "A-1001": "open", "A-1002": "open", "A-1003": "open", "A-1004": "closed"}, (status, answer))
        seen = {a: call(base, "get_alert", {"alert_id": a}) for a in ("A-1001", "A-1002", "A-1003", "A-1004")}
        check("RESET ... after it, every alert is open except alert 4, which is closed as in the seed",
              all(not err and alert.get("status") == "open" and "acted_by" not in alert
                  for a, (err, alert) in seen.items() if a != "A-1004")
              and seen["A-1004"][1].get("acted_by") == "jordan.reyes", seen)
        err, again = escalate(base)
        check("RESET ... and there are no SAR cases: escalating alert 2 again opens a new one, with the first SAR case ID",
              not err and again.get("result") == "escalated" and again.get("sar_case_id") == sar_case["sar_case_id"], again)

    # A state file from an older build, whose tables don't fit this one. The server starts on it (it has an alerts table,
    # so the seed doesn't load); POST /reset makes the tables again.
    db = new_state("older-build")
    old = sqlite3.connect(db)
    old.execute("CREATE TABLE alerts (alert_id TEXT PRIMARY KEY, status TEXT)")
    old.execute("INSERT INTO alerts VALUES ('A-1001', 'open')")
    old.commit()
    old.close()
    with server(db) as base:
        status, answer = reset(base)
        err, alert = call(base, "get_alert", {"alert_id": "A-1001"})
        err2, sar_case = escalate(base)
        check("RESET a state file from an older build gets new tables and the seed: get_alert and escalate_to_sar work",
              status == 200 and not err and alert == {**ALERT_1, "status": "open"} and not err2
              and sar_case.get("result") == "escalated", (status, answer, alert, sar_case))


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


for group in (check_alert, check_profile, check_transactions, check_close, check_escalate, check_who_acted, check_restart, check_reset,
              check_seeded_alerts, check_seed, check_start,
              check_app_script):
    try:
        group()
    except Exception as e:  # a case that can't run is a failure, never a skip
        check(f"{group.__name__} ran to the end", False, f"{type(e).__name__}: {e}")

if failed:
    print(f"\n{len(failed)} failed: {', '.join(failed)}  (server logs in {ROOT})")
    sys.exit(1)
shutil.rmtree(ROOT, ignore_errors=True)  # the logs are kept only when a case failed
print("\nall checks passed")
