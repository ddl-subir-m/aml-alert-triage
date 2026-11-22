## Agent skills

### Issue tracker

Issues and specs live in the repo's GitHub Issues, through the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`. The platform's own terms (agent,
task, requester, approval, tool server, client-side tool, ...) are in the Domino Agent Service's `GLOSSARY.md`
(etanlightstone/domino-agent-service).

## No plumbing

No file of this repo works around a gap of the platform: the checks of `governance/` show the author's work. For each gap below,
use what the platform gives (domino-agent-service spec #499). The code review checks each row:

| The gap: no file has it | Use |
|---|---|
| An ID search: the IDs of an evidence item, a field or an option | `write_policy_result` by the item's name and the field labels |
| The handling of a cut answer: text that the gateway cut | the list tools' `offset` and `nextOffset` (`contract.call_json()` reads each page) |
| A regex on prose: a tool's answer in words, the task brief, the instruction | the tools' JSON (`call_json()`) and the task's facts (`contract.task()`) |
| A snapshot wait loop | `write_bundle_doc`: the file, its snapshot and the attachment, in one call |

A check reads its own files in its own way: for example the summary that `governance/scan.py` prints. When a check needs something
that the platform does not give, the fix goes in domino-agent-service or domino-agui, not in the check.
