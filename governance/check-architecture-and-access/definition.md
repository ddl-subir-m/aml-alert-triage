---
# Check 2 of the App validation demo, "Architecture and access" (domino-agent-service spec #388, Implementation Decision 9): a
# registered agent (opencode). When a governance bundle moves to the Validation stage, it checks the bundle's
# App with the checklist of its own skill, skills/architecture-and-access: all access, the tech stack, the design and the
# dependencies. `domino-agent deploy governance/check-architecture-and-access` registers it. The data is fake.
# It is the folder validator of spec #260 (the tag app-validation-two-ways keeps it), narrowed to its part: no scan, no Job.
# The fields are on domino-agent-service's reference page, docs/definition-file.md. Its event subscription is the file
# subscriptions/bundle-enters-validation.md. What the owner adds before it can run (the service account and its token, the sharing)
# is in README.md, next to this file.
name: architecture-and-access
title: Architecture and access   # exact: the check's name in governance/checks.json (Validation status finds the task by it)
description: >-
  Checks the architecture and access of the App of a governance bundle that moved to the Validation stage: who can call each route
  and what it changes, which identity each write records, the tech stack, the design, and how each dependency is pinned and
  installed. It commits its doc to its task branch, attaches the doc to the bundle, files its real findings, and fills the evidence
  item "Validation: Architecture and access". Fake data only.
model: google/gemini-3.8-flash   # the same model for the three checks; not sonnet: Anthropic's cyber safeguards refuse this work (domino-agent-service#270)
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
  jobs: false                 # no scan: known vulnerabilities are the part of the check "Vulnerability scan"
  push: true                  # the doc leaves the Job only through domino_git_push, to the task branch agent/<task key>
access:
  project: write              # the doc goes in the project's files (the push needs it); the bundle of the task's project too
  datasets: none
  attached: write             # the event's bundle is a resource attached to the task: the attachment, the findings, the evidence
  other: none
on-error: fail                # an event task has nobody to unblock it: a denied call ends the task with a report
---
