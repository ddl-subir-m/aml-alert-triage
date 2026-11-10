"""Creates the AML alert triage agent on the platform App from agent/definition.json, or updates it when the App has an agent of that
name: the API way to do what the App's wizard does (README, Create the agent). Run it in a Domino Workspace: it acts as you. It uses
the stdlib only, so it runs on the Domino Standard Environment.

  python agent/register.py --app URL --reviewer NAME [--reviewer NAME ...] [--model ALIAS] [--environment ID] [--view-as]
  python agent/register.py --print --reviewer NAME [--reviewer NAME ...] [--model ALIAS] [--environment ID]

It puts you in the agent's users list (you are the analyst, and the agent's owner when it creates it) and the reviewers in its editors
list (the approvers of an escalation are the owner and the editors, minus the analyst who asked: any one of them decides). Give
--reviewer once for each reviewer. Each run sets the whole editors list, so name every reviewer each time. --print shows the agent body
and calls nothing.

How it calls the App: with the Workspace's token. The platform App has extended identity, so the Apps proxy gives it a token of yours
that Domino accepts. --view-as is for an App without extended identity (smoke.py deploy --no-extended-identity): the Apps proxy then
changes the token, so the script also sends your own Domino user name in the header X-Prototype-View-As, and the App's view-as switch
must be on (SMOKE_ALLOW_VIEW_AS=1 on agent-framework-smoke). It checks GET api/me first, finds the agent by name (GET api/agents), then
sends POST api/agents or PUT api/agents/<id> with the whole body. It prints the agent's ID and page URL.

Exit code: 0 when the agent is created or updated (or printed), 1 when the App or the Workspace stopped it, 2 when an argument is wrong.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFINITION = Path(__file__).resolve().parent / "definition.json"
SWITCH_OFF = ("Turn on the App's view-as switch: in the project that holds the App (agent-framework-smoke), set the project variable "
              "SMOKE_ALLOW_VIEW_AS=1, then restart the App (publish a new version). The App's first log line then shows "
              "AGENT_ALLOW_VIEW_AS=1.")
NO_EXTENDED_IDENTITY = ("It does that when the App runs without extended identity: publish it with extended identity (smoke.py deploy), "
                        "or turn its view-as switch on and run this again with --view-as.")
HINTS = [   # (a part of the App's reason, what to do)
    ("isn't in the tool server list", "Add the case-management App as the tool server aml on the App's Tool servers page first "
                                      "(README, Create the agent), then run this again."),
    ("isn't certified for langgraph", "Run this again with --environment and one of the Environment IDs that the App lists."),
]


class Stop(Exception):
    """Why the script stops, for the person who runs it."""


def agent_body(reviewers, me, model=None, environment=None):
    """The definition file, with you (the analyst) in its users list, the reviewers in its editors list, and the overrides."""
    b = json.loads(DEFINITION.read_text())
    b["access"] = {**b["access"], "users": [me], "editors": list(reviewers)}
    if model:
        b["model"] = {**b["model"], "models": [model]}
    if environment:
        b["execution"] = {**b["execution"], "environment": {"id": environment}}
    return b


# ------------------------------------------------------------------------------------------------------------------------- HTTP
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # a redirect is the Apps proxy's sign-in or consent page, never the App's answer
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def request(method, url, headers, body=None):
    """-> (status, the JSON answer or its text, the Location header)"""
    data = None if body is None else json.dumps(body).encode()
    h = {"Accept": "application/json", **({"Content-Type": "application/json"} if data else {}), **headers}
    try:
        with _OPENER.open(urllib.request.Request(url, data=data, method=method, headers=h), timeout=60) as r:
            status, raw, location = r.status, r.read(), r.headers.get("Location")
    except urllib.error.HTTPError as e:
        status, raw, location = e.code, e.read(), e.headers.get("Location")
    except OSError as e:
        raise Stop(f"{method} {url} didn't answer: {e}")
    text = raw.decode("utf-8", "replace")
    try:
        return status, json.loads(text), location
    except ValueError:
        return status, text, location


def token():
    """The Workspace's own token, fresh for each request (it lives for minutes)."""
    url = os.environ.get("DOMINO_API_PROXY", "http://localhost:8899").rstrip("/") + "/access-token"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            t = r.read().decode().strip()
    except OSError as e:
        raise Stop(f"The Workspace's token isn't at {url} ({e}): run this in a Domino Workspace.")
    t = t[len("Bearer "):] if t.startswith("Bearer ") else t
    if not t:
        raise Stop(f"{url} gave an empty token: run this in a Domino Workspace.")
    return t


def reason(status, data):
    """The App's reason (its {"detail": ...}), else the start of what answered."""
    if isinstance(data, dict) and "detail" in data:
        d = data["detail"]
        return f"{status} {d if isinstance(d, str) else json.dumps(d)}"
    return f"{status} {str(data)[:300]}"


def starting_username():
    """The Workspace's DOMINO_STARTING_USERNAME: the person who started it ("" when it isn't set)."""
    return os.environ.get("DOMINO_STARTING_USERNAME", "").strip()


def my_name():
    """Your own Domino user name: the Workspace's DOMINO_STARTING_USERNAME, else Domino's answer for the Workspace's token."""
    name = starting_username()
    if name:
        return name
    host = os.environ.get("DOMINO_API_HOST", "").rstrip("/")
    if not host:
        raise Stop("Neither DOMINO_STARTING_USERNAME nor DOMINO_API_HOST is set: run this in a Domino Workspace.")
    status, data, _ = request("GET", f"{host}/api/users/v1/self", {"Authorization": f"Bearer {token()}"})
    name = ((data.get("user") or {}).get("userName") if isinstance(data, dict) else None) or ""
    if status != 200 or not name:
        raise Stop(f"Domino didn't say who you are (GET /api/users/v1/self: {reason(status, data)}).")
    return name


# ------------------------------------------------------------------------------------------------------------------------- the App
def call(base, view_as, method, path, body=None):
    """The platform App, as you: the Workspace's token and, for an App without extended identity, your name (`view_as`) in the view-as
    header. `view_as` is None for an App with extended identity: it takes your token."""
    headers = {"Authorization": f"Bearer {token()}", **({"X-Prototype-View-As": view_as} if view_as else {})}
    status, data, location = request(method, f"{base}/{path}", headers, body)
    if 300 <= status < 400:
        raise Stop(f"{base} sent a redirect to {(location or '')[:150]}: that is the Apps proxy's sign-in or consent page. Open the "
                   "App once in your browser, then run this again.")
    return status, data


def page(base, agent_id):
    return f"{base}/#/agents/{agent_id}"


def check_me(base, me):
    """The App (with extended identity) knows you by your token. -> how it knows you (its `source`)"""
    status, data = call(base, None, "GET", "api/me")
    if status == 401:
        raise Stop(f"Domino didn't accept the token that the Apps proxy gave the App for you (GET api/me: {reason(status, data)}). "
                   f"{NO_EXTENDED_IDENTITY}")
    if status != 200 or not isinstance(data, dict):
        raise Stop(f"GET api/me didn't answer as the App does ({reason(status, data)}): check the App's URL, and that the App runs.")
    if data.get("userName") != me:
        raise Stop(f"The App sees you as {data.get('userName')!r} through {data.get('source')!r}, not as {me!r}: run this in a "
                   "Workspace that you started.")
    return data.get("source")


def check_view_as(base, me):
    """With --view-as: the App has its view-as switch on and knows you by your name. -> how it knows you (its `source`)"""
    status, data = call(base, me, "GET", "api/me")
    if status == 401:
        raise Stop(f"The App checked your token instead of the view-as header (GET api/me: {reason(status, data)}). It does that "
                   f"when its view-as switch is off. {SWITCH_OFF}")
    if status != 200 or not isinstance(data, dict):
        raise Stop(f"GET api/me didn't answer as the App does ({reason(status, data)}): check the App's URL, and that the App runs.")
    if not data.get("viewAsEnabled"):
        raise Stop(f"The App's view-as switch is off (GET api/me: viewAsEnabled is false). {SWITCH_OFF}")
    if data.get("userName") != me:
        raise Stop(f"The App didn't take the view-as header: it sees you as {data.get('userName')!r} through "
                   f"{data.get('source')!r}, not as {me!r}. Something between you and the App drops the header X-Prototype-View-As.")
    return data.get("source")


def register(base, view_as, body):
    """Creates the agent, or updates the one with its name. -> (verb, the App's answer)"""
    status, data = call(base, view_as, "GET", "api/agents")
    if status != 200 or not isinstance(data, list):
        raise Stop(f"The App didn't list its agents (GET api/agents: {reason(status, data)}).")
    same = [a for a in data if isinstance(a, dict) and a.get("name") == body["name"]]
    if len(same) > 1:
        raise Stop(f"The App has {len(same)} agents named {body['name']!r}: " + ", ".join(page(base, a.get("id")) for a in same)
                   + ". Delete all but one on the App, then run this again.")
    if same and not same[0].get("canEdit"):
        owner = (same[0].get("owner") or {}).get("userName") or "its owner"
        raise Stop(f"The agent {body['name']!r} exists ({page(base, same[0].get('id'))}), and you can't change it: ask {owner} to "
                   "add you as an editor, or to delete it.")
    if same:
        verb, (status, data) = "Updated", call(base, view_as, "PUT", f"api/agents/{same[0]['id']}", body)
    else:
        verb, (status, data) = "Created", call(base, view_as, "POST", "api/agents", body)
    if status != 200 or not isinstance(data, dict) or not data.get("id"):
        why = reason(status, data)
        raise Stop(f"The App refused to {'update' if same else 'create'} the agent: {why}"
                   + "".join(f"\n{todo}" for part, todo in HINTS if part in why))
    return verb, data


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--app", help="the platform App's URL, as Domino gives it (https://<apps host>/apps-internal/<App ID>)")
    ap.add_argument("--reviewer", required=True, action="append",
                    help="a reviewer's Domino user name: an editor of the agent, who approves escalations. Give it once for each reviewer")
    ap.add_argument("--model", help="an LLM Gateway alias, instead of the file's")
    ap.add_argument("--environment", help="a certified LangGraph Environment's ID, instead of the file's")
    ap.add_argument("--view-as", action="store_true",
                    help="the App runs without extended identity: send your name in its view-as header (its view-as switch must be on)")
    ap.add_argument("--print", action="store_true", dest="print_only", help="show the agent body, and call nothing")
    a = ap.parse_args()
    if not a.print_only and not a.app:
        ap.error("--app is required (the platform App's URL), or --print to only show the agent body")
    for flag in ("model", "environment"):
        if getattr(a, flag) is not None and not getattr(a, flag).strip():
            ap.error(f"--{flag} is empty")
    if any(not r.strip() for r in a.reviewer):
        ap.error("a --reviewer is empty")
    reviewers = list(dict.fromkeys(r.strip() for r in a.reviewer))   # in the order given, each name once
    try:
        me = (starting_username() or "<your Domino user name>") if a.print_only else my_name()
        if me in reviewers:
            ap.error(f"a reviewer can't be you ({me}): an escalation needs a second person to approve it. Remove --reviewer {me}, and "
                     "name other Domino users.")
        body = agent_body(reviewers, me, (a.model or "").strip(), (a.environment or "").strip())
        if a.print_only:
            print(json.dumps(body, indent=2))
            return 0
        base = a.app.split("#")[0].rstrip("/")
        source = check_view_as(base, me) if a.view_as else check_me(base, me)
        print(f"The App knows you as {me} (through the {source}).", flush=True)
        verb, agent = register(base, me if a.view_as else None, body)
    except Stop as e:
        print(e, file=sys.stderr)
        return 1
    print(f"{verb} the agent {agent.get('name')!r} as {me}, with {', '.join(reviewers)} as its "
          f"{'editor' if len(reviewers) == 1 else 'editors'}.")
    print(f"Agent ID: {agent['id']}")
    print(f"Agent page: {page(base, agent['id'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
