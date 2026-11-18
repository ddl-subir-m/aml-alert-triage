---
# The agent folder validator of the App validation demo (domino-agent-service spec #260, Implementation Decision 8): a harness agent
# (opencode). When a governance bundle moves to the Validation stage, it validates the bundle's App with the checklist of its own
# skill, skills/app-validation. `domino-agent deploy governance/validator-folder` registers it. The data is fake.
# The fields are on domino-agent-service's reference page, docs/definition-file.md. What the owner adds before it can run (the
# service account and its token, the sharing, the event subscription) is in README.md, next to this file.
name: app-validator-folder
title: App validator (agent folder)   # exact: the scripted check (governance/validation_status.py) finds the agent by this name
description: >-
  Validates the App of a governance bundle that moved to the Validation stage: reads the App's code, scans it in a Domino Job,
  sorts the real findings from the false hits, commits a validation doc to its task branch, attaches the doc to the bundle, files
  the real findings, and fills the evidence item "Validation (agent folder)". Fake data only.
model: sonnet
identity: service-account     # the owner adds the service account and its token (README.md): the file holds no user names
inputs:
  - type: project             # a task runs as a Domino Job in the bundle's project: the event names it
    required: true
limits:
  minutes: 45
  turns: 120
  wait-minutes: 0             # nobody answers an event task, so a question ends the Job at once
tools:
  subagents: false
  jobs: true                  # the scan runs in a Domino Job (governance/scan.py), which reaches PyPI
  push: true                  # the doc leaves the Job only through domino_git_push, to the task branch agent/<task key>
access:
  project: write              # the doc goes in the project's files (the push needs it); the bundle of the task's project too
  datasets: none
  attached: write             # the event's bundle is a resource attached to the task: the attachment, the findings, the evidence
  other: none
on-error: fail                # an event task has nobody to unblock it: a denied call ends the task with a report
---
