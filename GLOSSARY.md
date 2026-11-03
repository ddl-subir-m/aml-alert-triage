# AML alert triage

A reference workflow for the Domino Agent Service: a LangGraph agent triages transaction monitoring alerts with a fake
case-management system, and an escalation needs a second person.

## Language

**Alert**:
One hit of the transaction monitoring system on one customer, which an analyst must triage.
_Avoid_: case, flag, hit

**Triage**:
The decision on one alert: close it, escalate it, or ask a person.

**Analyst**:
The person who starts a triage. On the platform, the requester.
_Avoid_: maker, user

**Reviewer**:
The second person who approves or denies an escalation. On the platform, the approver. An agent can have several reviewers: any
one of them decides.
_Avoid_: checker

**Escalation**:
Sending an alert to a SAR investigation. It always needs a reviewer.

**SAR case**:
The investigation record that an escalation opens. An alert has at most one.
_Avoid_: SAR (alone), investigation

**Maker-checker**:
The rule that an escalation needs two different people: an analyst and a reviewer.
_Avoid_: four-eyes, dual control

**Reason code**:
Why an alert was closed: `false_positive`, `explained_activity` or `duplicate`.

**Case-management system**:
The system that holds alerts and SAR cases. Here it is a fake one, served as a tool server.
_Avoid_: CMS
