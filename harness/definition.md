---
# The AML alert triage agent on the harness lane (opencode), as an agent folder (domino-agent-service spec #220, ADR 0037).
# The framework agent in agent/ does the same triage. `domino-agent deploy harness` registers this one. The data is fake.
# The fields are in domino-agent-service's docs/definition-file.md. This file sets the values of agent/definition.json where both
# lanes have them: a field left out has that value as its default.
name: aml-alert-triage
title: AML alert triage (harness)
description: >-
  Triages one transaction monitoring alert: reads the alert, the customer's profile and transactions in the fake case-management
  system, then closes the alert, escalates it to a SAR case (a reviewer approves first), or asks the analyst. Fake data only.
project: aml-alert-triage     # the agent always runs in this Domino project, and only its collaborators can use it. An eval run
                             # needs it: an eval task has a project only when this file names one
model: sonnet
identity: requester          # the agent acts as the analyst who starts the task
tool-servers: [aml]          # the case-management system, with every tool. It must be on the tool server list
inputs:
  - type: project            # each task names a project, so it runs as a Domino Job in that project
    required: true
limits:
  turns: 20
  wait-minutes: 0            # a question ends the Job at once, and the answer starts a new Job
tools:
  shell: false               # the triage needs only the case-management tools
  subagents: false
access:
  project: read
  datasets: none
on-error: fail
memory:                      # what the agent keeps outside the conversation of a task (domino-agent 0.10.0)
  personal: true             # about one analyst: only the tasks that this analyst starts directly read it
  agent: true                # for every analyst: a run proposes a note, and an owner or an editor of the agent accepts it
  task: true                 # the working notes of one task: a later round (a new Job) and a task that names it read them
starter-prompts:
  - Triage alert A-1001.
  - Triage alert A-1002.
  - Triage alert A-1003.
  - Triage alert A-1004.
---
