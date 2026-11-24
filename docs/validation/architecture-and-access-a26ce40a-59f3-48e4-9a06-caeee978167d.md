# Validation of aml-case-management: Architecture and access

Check: Architecture and access. Bundle: a26ce40a-59f3-48e4-9a06-caeee978167d. Written: 2026-11-24 16:04 (UTC).

## App and version

App aml-case-management, repository aml-validation-demo, commit 665311f74d7b7bf0aa62b9fa1f10fe441e0d31b0.

## Evidence

- Verdict: do not approve
- Highest severity: S1
- Summary: Do not approve because route POST /reset allows any caller who can open the App to delete all state. Real findings: [Architecture and access] Anyone who can open the App can delete all state in POST /reset (S1), [Architecture and access] A write with no domino-username, recorded as no identity in close_alert and escalate_to_sar (S2), and [Architecture and access] mcp installed from PyPI at App start in app.sh (S2).
- Doc location: agent/AGT-139, docs/validation/architecture-and-access-a26ce40a-59f3-48e4-9a06-caeee978167d.md

## What this check could not check

- The commit of the App version under review: the task reads the project's default branch (`demo/app-validation`), not the version's commit.
- What only the running App shows: the Domino Apps proxy behavior, live HTTP identity headers, and who can open the App (configured via Domino App settings, not in code).

## Architecture and access

### Tech stack

- Language: Python 3 (`case_server/server.py:15`, `app.sh:7`).
- Frameworks: FastMCP / Model Context Protocol SDK (`case_server/server.py:22`, `case_server/requirements.txt:1`), Starlette (`case_server/server.py:25-26`).
- Server: FastMCP running over streamable-http on `0.0.0.0:8888` (`case_server/server.py:69-79, 171-174`, `app.sh:2, 17`).
- Storage: SQLite database (`case_server/store.py:3, 63`), located at `/mnt/data/aml-cases/cases.db` on Domino (`app.sh:16`).

### Architecture

The App is a case-management service for AML alert triage. The entry point is `app.sh`, which invokes `case_server/server.py`. The server exposes an MCP streamable-HTTP interface at `/mcp` with three read tools and two write tools, plus custom HTTP routes for system reset (`POST /reset`), YAML alert upload (`POST /upload`), and an HTML case board (`GET /` via `case_server/board.py`). State is stored in a single SQLite database initialized from `case_server/seed.json` on first run (`case_server/store.py:60-74`).

| Method | Path | Who can call it | What it changes |
|---|---|---|---|
| POST | /mcp (tool: get_alert) | Anyone who can open the App | nothing |
| POST | /mcp (tool: get_customer_profile) | Anyone who can open the App | nothing |
| POST | /mcp (tool: get_transactions) | Anyone who can open the App | nothing |
| POST | /mcp (tool: close_alert) | Anyone who can open the App | Updates alert status to closed, sets reason_code, rationale, acted_by, and acted_at in SQLite database |
| POST | /mcp (tool: escalate_to_sar) | Anyone who can open the App | Creates new SAR case in sar_cases table and updates alert status to escalated with acted_by and acted_at in SQLite database |
| POST | /reset | Anyone who can open the App | Drops all SQLite database tables and reloads initial seed data from seed.json |
| POST | /upload | Anyone who can open the App | nothing |
| GET | / | Anyone who can open the App | nothing |

### Access

Who can open the App is determined by Domino's App access setting ("project collaborators"), which is enforced by the Domino Apps proxy outside the codebase. Within the code, there are no role-based authorization checks or caller access restrictions on any MCP tool or HTTP route; anyone who can reach the App can call every endpoint.

For write operations (`close_alert` and `escalate_to_sar`), the server reads caller identity from the `domino-username` request header (`case_server/server.py:54-66, 110, 122`). If the header is missing, empty, or `Anonymous`, the code returns `"no identity (...)"` and persists that string into the audit columns (`acted_by` and `opened_by`) rather than refusing the write request (`case_server/store.py:185, 205`). The custom route `POST /reset` drops all tables and reloads seed data with no access check and records no identity (`case_server/server.py:128-133`, `case_server/store.py:75-85`).

### Dependencies

| Dependency | Version or range | How it is pinned | How and when it is installed |
|---|---|---|---|
| mcp | >=1.10,<2 | Range | Installed from PyPI via pip or uv at App startup by `app.sh:7-13` if missing from Environment |
| pyyaml | ==5.3.1 | Exact | Listed in `case_server/requirements.txt:2`; installed by `app.sh:7-13` if `mcp` check triggers installation |

### Findings

#### Real findings

| Name | Severity | Evidence | Fix |
|---|---|---|---|
| [Architecture and access] Anyone who can open the App can delete all state in POST /reset | S1 | `case_server/server.py:128-133`, `case_server/store.py:75-85`: `alerts = store.reset()`, dropping all tables and reloading seed data with no authentication or caller authorization check. | Remove `POST /reset` from production or restrict it to authorized administrators with audit logging. |
| [Architecture and access] A write with no domino-username, recorded as no identity in close_alert and escalate_to_sar | S2 | `case_server/server.py:54-66, 110, 122`, `case_server/store.py:185, 205`: when `domino-username` is missing, empty, or `Anonymous`, `acting_identity()` returns `"no identity (...)"` and writes it to `acted_by` / `opened_by`. | Refuse write requests with an error when `domino-username` is missing, empty, or `Anonymous` instead of recording `"no identity"`. |
| [Architecture and access] mcp installed from PyPI at App start in app.sh | S2 | `app.sh:7-13`: `uv pip install --system --quiet -r case_server/requirements.txt` installs `mcp>=1.10,<2` dynamically from PyPI if missing. | Pre-install required dependencies into the certified Domino Environment image rather than running pip install from PyPI at container startup. |

#### False hits

| What | Why it is not a finding |
|---|---|
| Unrestricted access on GET / (case board) | `GET /` is a read-only monitoring dashboard that displays case status. It performs no state modifications and all output values are safely escaped (`case_server/board.py:50, 97-132`). Read access is intended for users authorized to open the App. |
| Unrestricted access on POST /upload | While `POST /upload` parses request body input, it does not modify database state or change application data (`case_server/server.py:137-146`). The unsafe YAML deserialization vulnerability is governed by the check "Vulnerability scan", not "Architecture and access". |
