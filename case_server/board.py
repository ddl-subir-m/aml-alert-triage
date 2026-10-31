"""The case board: one read-only HTML page with the alerts and the SAR cases, so people can watch the case-management system
change while an agent works (for example in a demo). The server serves it at GET /. It reloads itself every few seconds, and marks
each alert that changed in the last minutes. Every value is escaped: rationales and narratives are text that an agent wrote."""
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

RELOAD_SECONDS = 5
RECENT = timedelta(minutes=2)   # an alert closed or escalated this recently is marked New
NEW = '<span class="badge new">New</span>'
NOT_YET = '<span class="muted">Not yet</span>'
RECENT_ROW = ' data-recent="yes" class="recent"'

STYLE = """
:root { --heading: #3F4547; --body: #7F8385; --border: #DBE4E8; --primary: #3B3BD3; --surface: #FFFFFF; --page: #F7F8FA; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 16px 40px; background: var(--page); color: var(--heading);
       font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 20px; margin: 32px 0 12px; }
p { margin: 0; }
.lead { color: var(--body); font-size: 16px; }
.meta { color: var(--body); font-size: 12px; margin-top: 8px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; vertical-align: top; padding: 10px 12px; border-bottom: 1px solid var(--border); }
th { font-size: 12px; font-weight: 600; color: var(--body); white-space: nowrap; }
tr:last-child td { border-bottom: 0; }
tr.recent td { background: #FFFBEA; }
code { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }
.id { font-weight: 600; white-space: nowrap; }
.sub { display: block; color: var(--body); font-size: 12px; }
.muted { color: var(--body); }
.text { max-width: 420px; }
.nowrap { white-space: nowrap; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.open { background: #EDECFB; color: #1820A0; }
.closed { background: #E6F4EA; color: #1D6B3A; }
.escalated { background: #FDECEA; color: #A12A1F; }
.new { background: #FFF0C2; color: #6B4A00; margin-left: 4px; }
.empty { padding: 20px 16px; }
.empty strong { display: block; margin-bottom: 4px; }
footer { color: var(--body); font-size: 12px; margin-top: 24px; }
"""


def _when(value: str | None) -> str:
    """A UTC time as the case-management system writes it (2026-10-17T15:04:05Z), for people: 2026-10-17 15:04:05."""
    return escape((value or "").replace("T", " ").rstrip("Z"))


def _recent(alert: dict[str, Any], now: datetime) -> bool:
    try:
        acted = datetime.strptime(alert.get("acted_at") or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return now - acted <= RECENT


def _decision(alert: dict[str, Any]) -> str:
    if alert["status"] == "closed":
        return (f'<code>{escape(alert["reason_code"] or "")}</code>'
                f'<span class="sub text">{escape(alert["rationale"] or "")}</span>')
    if alert["status"] == "escalated":
        return f'SAR case <span class="id">{escape(alert["sar_case_id"] or "")}</span>'
    return '<span class="muted">Waiting for triage</span>'


def _alert_row(alert: dict[str, Any], now: datetime) -> str:
    recent = _recent(alert, now)
    status = escape(alert["status"])
    acted = alert["status"] != "open"
    return (f'<tr data-alert="{escape(alert["alert_id"])}" data-status="{status}"'
            f'{RECENT_ROW if recent else ""}>'
            f'<td class="id">{escape(alert["alert_id"])}</td>'
            f'<td>{escape(alert["customer_name"])}<span class="sub">{escape(alert["customer_id"])}</span></td>'
            f'<td><code>{escape(alert["rule"])}</code></td>'
            f'<td>{alert["score"]:.2f}</td>'
            f'<td class="nowrap"><span class="badge {status}">{status.capitalize()}</span>'
            f'{NEW if recent else ""}</td>'
            f'<td>{_decision(alert)}</td>'
            f'<td>{escape(alert["acted_by"] or "") if acted else NOT_YET}</td>'
            f'<td class="nowrap">{_when(alert.get("acted_at")) if acted else ""}</td></tr>')


def _sar_row(case: dict[str, Any]) -> str:
    return (f'<tr data-sar-case="{escape(case["sar_case_id"])}">'
            f'<td class="id">{escape(case["sar_case_id"])}</td>'
            f'<td class="id">{escape(case["alert_id"])}</td>'
            f'<td>{escape(case["opened_by"])}</td>'
            f'<td class="nowrap">{_when(case["opened_at"])}</td>'
            f'<td>{escape(", ".join(case["transaction_ids"]))}</td>'
            f'<td class="text">{escape(case["narrative"])}</td></tr>')


def render(board: dict[str, Any], now: datetime) -> str:
    """The case board's page. `board`: CaseStore.board(); `now`: a UTC time, for the New marks."""
    alerts = "".join(_alert_row(a, now) for a in board["alerts"])
    if board["sar_cases"]:
        sar_cases = ('<table><thead><tr><th>SAR case</th><th>Alert</th><th>Opened by</th><th>Opened at (UTC)</th>'
                     '<th>Transactions</th><th>Narrative</th></tr></thead><tbody>'
                     + "".join(_sar_row(c) for c in board["sar_cases"]) + "</tbody></table>")
    else:
        sar_cases = ('<div class="empty" data-empty="sar-cases"><strong>No SAR cases yet</strong>'
                     '<span class="muted">A SAR case opens when an escalation runs. On the platform, an escalation runs only '
                     'after a reviewer approves it.</span></div>')
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{RELOAD_SECONDS}">
<title>AML case board</title>
<style>{STYLE}</style>
</head>
<body>
<main>
<h1>AML case board</h1>
<p class="lead">The alerts and SAR cases of the case-management system. All the data is fake.</p>
<p class="meta">Updated {now.strftime("%H:%M:%S")} UTC. The page reloads every {RELOAD_SECONDS} seconds. An alert that changed in the
last {int(RECENT.total_seconds() // 60)} minutes is marked <span class="badge new">New</span>.</p>
<h2>Alerts</h2>
<div class="card"><table><thead><tr><th>Alert</th><th>Customer</th><th>Rule</th><th>Score</th><th>Status</th><th>Decision</th>
<th>Who acted</th><th>When (UTC)</th></tr></thead><tbody>{alerts}</tbody></table></div>
<h2>SAR cases</h2>
<div class="card">{sar_cases}</div>
<footer>Read only. Agents change the system only through its tools. To load the seed again, send <code>POST /reset</code>.</footer>
</main>
</body>
</html>
"""
