<!--
The template of a check's doc (domino-agent-service spec #388, Implementation Decision 7). Each of the three checks fills it.
How to fill it: keep the shared top part (from the title to "What this check could not check") and only the middle part that has your
check's name. Delete the other two middle parts. Replace each {{field}} with text, keep every heading of your parts in its order, and
delete every comment like this one.
The doc's file name names the check and the bundle ID. The evidence fields, the severity scale, the finding names and the rule for a
failed scan are in governance/README.md.
-->
# Validation of {{app}}: {{check}}

Check: {{check}}. Bundle: {{bundle_id}}. Written: {{written_at}} (UTC).

## App and version

<!-- The App's name, its repository, and the commit that the check read (for the Vulnerability scan: the "commit:" line of the scan
summary). -->
{{app_and_version}}

## Evidence

<!-- The same values as the evidence item "Validation: <check name>" and the first four lines of the result, but the doc location.
verdict: approve, do not approve or could not check. highest_severity: S0, S1, S2, S3 or none (the highest severity of this check's
real findings). summary: three to five sentences, with the verdict's reason and the real findings by name and severity. doc_location:
the doc is written before its push or its snapshot, so here it names only the file and where it goes (the task branch, or the doc
dataset), with no commit and no snapshot. This is advice: the approver decides. -->
- Verdict: {{verdict}}
- Highest severity: {{highest_severity}}
- Summary: {{summary}}
- Doc location: {{doc_location}}

## What this check could not check

<!-- The limits of this check. Always: the commit of the App version under review (the task reads the project's default branch, not
the version's commit), and what only the running App shows (the Apps proxy, the identity headers, who can open the App). Also each
tool that could not run, each part that a tool did not check, and each call that failed or that Domino denied. -->
{{could_not_check}}

## Purpose and data

<!-- The middle part of the check "Purpose and data": what the App is for and what data it holds, compared with the Intake answers.
For an Intake field that the analyst did not fill, say "not filled". -->

### Purpose

<!-- What the App is for, in two or three sentences, from its code and its README. Then the Intake's Purpose, as the analyst filled
it, and where the two differ. -->
{{purpose}}

### Users

<!-- Who uses the App, from its code and its README, against the Intake's Users. Say where they differ. -->
{{users}}

### Data class

<!-- The kind of data that the App is built to hold, and its class: Public, Internal, Confidential or Restricted. Judge it by the kind
of data, not by whether the sample data is fake: when the README says that the data is fake, say so, and still give the class of the
data that the App is built to hold. Then the Intake's Data class, and whether it is lower. -->
{{data_class}}

### Findings

#### Real findings

<!-- A table: | Name | Severity | Evidence | Fix |. The name is the one filed with write_governance_finding:
[Purpose and data] <what> in <where>. Severity: S0 to S3, on the scale of governance/README.md. Evidence: the file and line, or the
Intake field, that shows it. "None" when there are none. -->
{{real_findings}}

#### False hits

<!-- A table: | What | Why it is not a finding |. Each thing that looked like a problem and is not one, with the reason. "None" when
there is none. -->
{{false_hits}}

## Architecture and access

<!-- The middle part of the check "Architecture and access": all access, the tech stack, the design, and the dependencies with how
they are pinned and installed. -->

### Tech stack

<!-- The language, the frameworks, the server and the storage. -->
{{tech_stack}}

### Architecture

<!-- The parts and how they connect: the entry point, the routes or tools, where the state is, and who can call what. -->
{{architecture}}

### Access

<!-- Who can open the App (its Domino access setting decides it), who can call each route or tool and what it changes, and which
identity each write records. -->
{{access}}

### Dependencies

<!-- A table: | Dependency | Version or range | How it is pinned | How and when it is installed |. For example: from a requirements
file, by the start script from PyPI each time the App starts, or already in the Domino Environment. -->
{{dependencies}}

### Findings

#### Real findings

<!-- A table: | Name | Severity | Evidence | Fix |. The name is the one filed with write_governance_finding:
[Architecture and access] <what> in <where>. Severity: S0 to S3, on the scale of governance/README.md. Evidence: the file and line, and
the code that shows it. "None" when there are none. -->
{{real_findings}}

#### False hits

<!-- A table: | What | Why it is not a finding |. Each thing that looked like a problem and is not one, with the reason. "None" when
there is none. -->
{{false_hits}}

## Vulnerability scan

<!-- The middle part of the check "Vulnerability scan": known vulnerabilities in the code and the dependencies. -->

### Scan results

<!-- A table: | Tool | Version | Hits | What it did not check |, from the summary of governance/scan.py, and the scan Job's number.
For a tool that could not run, say why. What it did not check: each "- not audited: ..." and "- not scanned: ..." line of the
summary, or "nothing". -->
{{scan_results}}

### Findings

#### Real findings

<!-- A table: | Name | Severity | Evidence | Fix |. The name is the one filed with write_governance_finding:
[Vulnerability scan] <what> in <where>. Severity: S0 to S3, on the scale of governance/README.md. Evidence: the file and line, and the
scanner hit or the code that shows it. "None" when there are none. -->
{{real_findings}}

#### False hits

<!-- A table: | Hit | Why it is false |. One row for each scanner hit that is not a real finding, with the reason. "None" when every
hit is real. -->
{{false_hits}}
