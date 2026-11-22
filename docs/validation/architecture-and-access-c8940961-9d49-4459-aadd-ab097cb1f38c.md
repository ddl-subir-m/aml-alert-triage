# Validation of aml-case-management: Architecture and access

Check: Architecture and access. Bundle: c8940961-9d49-4459-aadd-ab097cb1f38c. Written: 2026-11-22 22:12 (UTC).

## App and version

aml-case-management in repository aml-validation-wizard at commit 16838340ec90c6d99cb53d29ea8696655532fd12.

## Evidence

- Verdict: do not approve
- Highest severity: S1
- Summary: Anyone who can open the App can wipe and reset all application state via POST /reset without authorization checks. In addition, state-changing MCP write tools record 'no identity' when domino-username is omitted, empty, or anonymous, and mcp is unpinned at startup. Real findings: [Architecture and access] Anyone who can open the App can delete all state in POST /reset (S1); [Architecture and access] A write with no domino-username, recorded as no identity in close_alert and escalate_to_sar (S2); [Architecture and access] mcp installed from PyPI at App start in app.sh (S2).
- Doc location: agent/AGT-137, docs/validation/architecture-and-access-c8940961-9d49-4459-aadd-ab097cb1f38c.md

## What this check could not check

The App version that the bundle names (the recorded commit is the head of the project's default branch when the task started, not a commit that the bundle names), and what only the running App shows (the Apps proxy, the identity headers, and who can open the App).

## Architecture and access

### Tech stack

- Language: Python (>=3.10) (README.md line 128)
- Frameworks / Server: FastMCP / Starlette / MCP streamable-http (case_server/server.py lines 22, 26, 69-79, 174)
- Storage: SQLite file on Domino dataset mount (/mnt/data/aml-cases/cases.db) (app.sh line 16; case_server/store.py lines 60-74)

### Architecture

The App is started via `app.sh`, which optionally installs dependencies and executes `case_server/server.py` on host 0.0.0.0 and port 8888 (app.sh lines 7-17; case_server/server.py lines 168-174). The server exposes MCP protocol endpoints over streamable HTTP at `/mcp` for 5 tools (3 read tools and 2 write tools), as well as custom Starlette HTTP routes at `/`, `/reset`, and `/upload` (case_server/server.py lines 81-153). Persistent state is maintained in SQLite via `case_server/store.py`.

#### Route table

| Method | Path | Who can call it | What it changes |
|---|---|---|---|
| POST | /mcp (tool: get_alert) | Anyone who can open the App | nothing |
| POST | /mcp (tool: get_customer_profile) | Anyone who can open the App | nothing |
| POST | /mcp (tool: get_transactions) | Anyone who can open the App | nothing |
| POST | /mcp (tool: close_alert) | Anyone who can open the App | Updates alert status to CLOSED, records acted_by, acted_at, reason_code, and rationale in the alerts table |
| POST | /mcp (tool: escalate_to_sar) | Anyone who can open the App | Inserts a new row into sar_cases and updates alert status to ESCALATED with acted_by and acted_at in the alerts table |
| POST | /reset | Anyone who can open the App | Drops all tables, recreates schema, and reloads initial seed data, deleting all state changes and SAR cases |
| POST | /upload | Anyone who can open the App | nothing |
| GET | / | Anyone who can open the App | nothing |

### Access

Access to open the App is controlled by Domino project settings (project collaborators). Once the App is opened, none of the routes or MCP tools enforce role-based access checks or caller authorization in code (case_server/server.py lines 81-153). State-modifying MCP tools (`close_alert`, `escalate_to_sar`) extract caller identity from the `domino-username` header; if missing, empty, or set to 'Anonymous', the code records "no identity (...)" rather than refusing the operation (case_server/server.py lines 54-67, 110, 122). `POST /reset` drops and recreates all database tables without authentication or identity logging (case_server/server.py lines 128-134; case_server/store.py lines 75-85).

### Dependencies

| Dependency | Version or range | How it is pinned | How and when it is installed |
|---|---|---|---|
| mcp | >=1.10,<2 | Range (unpinned exact version) | Installed via pip/uv at startup by app.sh if missing in environment (app.sh lines 7-13; case_server/requirements.txt line 1) |
| pyyaml | ==5.3.1 | Exact | Pinned in case_server/requirements.txt, installed at startup if mcp is installed via app.sh (app.sh lines 9, 11; case_server/requirements.txt line 2) |

### Findings

#### Real findings

| Name | Severity | Evidence | Fix |
|---|---|---|---|
| [Architecture and access] Anyone who can open the App can delete all state in POST /reset | S1 | case_server/server.py lines 128-134; case_server/store.py lines 75-85 (drops all tables and reloads seed with no access check) | Remove POST /reset from production or restrict it to authenticated admin users with proper authorization checks |
| [Architecture and access] A write with no domino-username, recorded as no identity in close_alert and escalate_to_sar | S2 | case_server/server.py lines 54-67, 110, 122 (permits writes with 'no identity' when header is missing or anonymous) | Refuse state modifications when domino-username header is missing, empty, or Anonymous |
| [Architecture and access] mcp installed from PyPI at App start in app.sh | S2 | app.sh lines 7-13; case_server/requirements.txt line 1 (mcp>=1.10,<2 installed dynamically at runtime) | Include and pin the exact mcp dependency in the Domino environment image rather than installing floating versions at App startup |

#### False hits

| What | Why it is not a finding |
|---|---|
| Unsafe YAML loading in POST /upload | Known code vulnerabilities (such as CVE-2020-14343 / yaml.full_load code execution) belong to the Vulnerability scan check; POST /upload changes no access or application state |
| Read-only tools open to all App users | Alerts, customer profiles, and transactions are intended for AML analysts and compliance reviewers who are permitted to open the App |
