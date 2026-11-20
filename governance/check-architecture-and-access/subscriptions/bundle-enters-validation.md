---
# The event subscription of check 2 (domino-agent-service ADR 0049): `domino-agent deploy` (0.4.0 or later) makes it from this
# file, and changes or removes it at each deploy. The file name is its name. The repo is public, so the filter names the demo
# project by its name, not by its Domino ID: a project with this name in another person's account matches too.
event: governance.bundle.stage_changed
filter:
  - field: toStage
    equals: Validation
  - field: project.name
    equals: aml-validation-demo
title: "Architecture and access: bundle {{bundle.id}}"
---
Check the architecture and access of the App of governance bundle {{bundle.id}} ({{bundle.name}}) in project {{project.name}}. The bundle moved from {{fromStage}} to {{toStage}}. Follow the checklist of the skill architecture-and-access, and fill only the evidence item "Validation: Architecture and access" of bundle {{bundle.id}}.
