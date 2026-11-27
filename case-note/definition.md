---
# The AML case note agent on the harness lane (opencode), as an agent folder. It shows an upstream task (domino-agent 0.10.0, task
# memory): a task of this agent names a task of the triage agent (harness/), and reads that task's notes. `domino-agent deploy
# case-note` registers it. The fields are in domino-agent-service's docs/definition-file.md. The data is fake.
name: aml-case-note
title: AML case note
description: >-
  Writes the case note for the audit file of one triaged alert, from the notes of the triage task. It has no access to the
  case-management system: it knows only what the upstream task wrote. Fake data only.
model: sonnet
identity: requester          # the agent acts as the person who starts the task
tools:
  shell: false               # the case note needs only the notes of the upstream task
  subagents: false
memory:
  task: true                 # an agent needs task memory to read an upstream task
on-error: fail
starter-prompts:
  - Write the case note for this alert.
---
