# Validation of aml-case-management: Purpose and data

Check: Purpose and data. Bundle: c8940961-9d49-4459-aadd-ab097cb1f38c. Written: 2026-11-22 22:09 (UTC).

## App and version

aml-case-management in repository aml-validation-wizard at commit 16838340ec90c6d99cb53d29ea8696655532fd12.

## Evidence

- Verdict: do not approve
- Highest severity: S1
- Summary: The Intake classifies the App's data as Internal, but the App is built to store and process financial crime investigation records, PEP flags, and SAR cases, which classify as Restricted. Real finding: [Purpose and data] Data class Internal for Restricted data in the Intake (S1).
- Doc location: agent/AGT-137, docs/validation/purpose-and-data-c8940961-9d49-4459-aadd-ab097cb1f38c.md

## What this check could not check

The commit of the App version under review (the task reads the project's default branch, not the version's commit), and what only the running App shows (the Apps proxy, the identity headers, who can open the App, and data in the running App state).

## Purpose and data

### Purpose

The App is a case-management system for AML alert triage, providing an MCP tool server and a case board UI where analysts and agents review alerts, inspect customer KYC profiles and transactions, close alerts with rationales, or escalate alerts to SAR investigation cases (README.md lines 16-38; case_server/server.py lines 81-125). The Intake Purpose states: "Case management for AML alert triage: analysts review alerts, then close or escalate each one. Fake data." The App's purpose aligns with the Intake Purpose.

### Users

The App is used by AML analysts and compliance reviewers via web browser/case board, as well as automated triage agents via MCP tool endpoints (README.md lines 8-10, 88-96; case_server/server.py lines 70-125). The Intake Users states: "AML analysts and compliance reviewers". The users align with the Intake.

### Data class

The App is built to store and process customer KYC profiles including PEP flags (case_server/store.py lines 33-35, 240), financial transaction histories (case_server/store.py lines 36-39, 248-250), monitoring alert statuses and rationales (case_server/store.py lines 42-45, 174-188), and SAR investigation cases with narratives and suspect transaction links (case_server/store.py lines 48-50, 189-210). Financial crime investigation records, suspicious activity reports, and PEP flags fall under Restricted data. While the sample data in the repository is fake (seed.json line 2), the data schema and operations are built for Restricted data. The Intake Data class is filled as Internal, which is lower than Restricted.

### Findings

#### Real findings

| Name | Severity | Evidence | Fix |
|---|---|---|---|
| [Purpose and data] Data class Internal for Restricted data in the Intake | S1 | Intake field "Data class" is Internal; case_server/store.py lines 48-50 (sar_cases table) and lines 33-35 (customers table with PEP flag) define SAR investigation cases and PEP flags | Update the Intake Data class to Restricted to reflect the financial crime and SAR investigation records handled by the App |

#### False hits

| What | Why it is not a finding |
|---|---|
| Sample data contains fake names and transactions | Fake sample data is used for testing and demonstration, but data classification is judged by the kind of data the App is built to hold |
