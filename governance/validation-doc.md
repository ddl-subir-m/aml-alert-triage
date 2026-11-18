<!--
The template of the validation doc (domino-agent-service spec #260, Implementation Decision 7). Both App validators fill it: the agent
folder validator (short name "folder") and the LangGraph validator (short name "LangGraph").
How to fill it: replace each {{field}} with text, keep every heading in its order, and delete every comment like this one.
The severity scale, the finding names and the rule for "critical vulns" are in governance/README.md.
-->
# Validation of {{app}}

Validator: {{validator}}. Bundle: {{bundle_id}}. Written: {{written_at}} (UTC).

## App and version

<!-- The App's name, its repository, and the commit that was read and scanned (the "commit:" line of the scan summary). -->
{{app_and_version}}

## Purpose

<!-- What the App does, in two or three sentences, from its code and README. Say where this differs from the Intake evidence. -->
{{purpose}}

## Users and data class

<!-- From the bundle's Intake evidence (users, data class), as the analyst filled it. Say "not filled" for an empty item. -->
{{users_and_data_class}}

## Tech stack

<!-- The language, the frameworks, the server and the storage. -->
{{tech_stack}}

## Architecture

<!-- The parts and how they connect: the entry point, the routes or tools, where the state is, and who can call what. -->
{{architecture}}

## Dependencies

<!-- A table: | Dependency | Version or range | How it is installed |. For example: from a requirements file, by the start script when
the App starts, or already in the Domino Environment. -->
{{dependencies}}

## Scan results

<!-- A table: | Tool | Version | Hits |, from the summary of governance/scan.py, and the scan Job's number. For a tool that could not
run, say why. -->
{{scan_results}}

## Findings

### Real findings

<!-- A table: | Name | Severity | Evidence | Fix |. The name is the one filed with write_governance_finding: it starts with the
validator's short name. Severity: S0 to S3. Evidence: file:line, and the scanner hit or the code that shows it. "None" when there are
none. -->
{{real_findings}}

### False hits

<!-- A table: | Hit | Why it is false |. One row for each scanner hit that is not a real finding, with the reason. "None" when every
hit is real. -->
{{false_hits}}

## Critical vulns

<!-- critical_vulns is "yes" or "no": "yes" when at least one real finding is S0. The reason names those findings, or says why no
finding is S0. -->
Critical vulns: {{critical_vulns}}

{{critical_vulns_reason}}

## Verdict for the approver

<!-- verdict is one of: approve, approve after fixes, do not approve. The reason names the findings that decide it. This is advice:
the approver decides. -->
Verdict: {{verdict}}

{{verdict_reason}}

## What the validator could not check

<!-- The limits of this validation. For example: the commit of the App version under review (the task reads the project's default
branch), what only the running App shows (the Apps proxy, the identity headers, who can open the App), and a tool that could not run.
-->
{{could_not_check}}
