"""Fill and compare the reference copy of the wizard agent "App validation" (this folder), for the live script of
domino-agent-service #529 and for tests/check_app_validation.py. Stdlib only, Python 3.8 or later.

The reference files hold placeholders for the values of a deployment, because the repo is public:

  __SERVICE_ACCOUNT__    the service account that the agent acts as (agent.json)
  __ANALYST__            the analyst who moves the bundle's stage: "People" (agent.json)
  __APPROVER__           the approver: "Editors" (agent.json)
  __PD_SKILL_ID__        the ID of the store skill purpose-and-data, from GET /api/skills (agent.json)
  __PD_SKILL_VERSION__   its version, from the same skill (agent.json)
  __AA_SKILL_ID__        the ID of the store skill architecture-and-access (agent.json)
  __AA_SKILL_VERSION__   its version (agent.json)
  __VS_SKILL_ID__        the ID of the store skill vulnerability-scan (agent.json)
  __VS_SKILL_VERSION__   its version (agent.json)
  __WIZARD_PROJECT_ID__  the ID of the second project, aml-validation-wizard (subscription.json)
  __INSTRUCTIONS__       the text of instructions.md, next to this file: filled with no --set

  python3 compare.py fill agent.json --set __SERVICE_ACCOUNT__=<name> --set ...    # the body of POST /api/agents
  python3 compare.py fill subscription.json --set __WIZARD_PROJECT_ID__=<ID>        # the body of POST /api/agents/{id}/triggers
  python3 compare.py fill schedule.json                                             # the same, for the schedule
  python3 compare.py diff agent.json <file> --set ...                # <file>: the answer of GET /api/agents/{id}
  python3 compare.py diff subscription.json <file> --set ...         # <file>: the answer of GET /api/agents/{id}/triggers
  python3 compare.py diff schedule.json <file>                       # the same answer: it compares the schedule

`fill` prints the filled file as JSON. It exits 2 when a placeholder of the file has no value. `diff` prints each setting that
differs, then one line, and exits 1 when a setting differs. The rule of the compare: each key of the reference is in the read-back,
with the same value. A key that only the read-back has is not compared: the IDs, the owner, the hardware tier, the times and the
counts are the deployment's. A list has as many items, and each item is the same. Text is the same when it is the same with no space
at its ends (a paste can add a new line). For a list of triggers, the one with the reference's type and name is compared.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLACEHOLDERS = ("__SERVICE_ACCOUNT__", "__ANALYST__", "__APPROVER__", "__PD_SKILL_ID__", "__PD_SKILL_VERSION__", "__AA_SKILL_ID__",
                "__AA_SKILL_VERSION__", "__VS_SKILL_ID__", "__VS_SKILL_VERSION__", "__WIZARD_PROJECT_ID__", "__INSTRUCTIONS__")
REFERENCES = ("agent.json", "subscription.json", "schedule.json")


def load(name):
    """The reference file `name` of this folder (one of REFERENCES), as JSON."""
    return json.loads((HERE / name).read_text())


def instructions():
    """The system prompt: instructions.md, with no space at its ends."""
    return (HERE / "instructions.md").read_text().strip()


def unfilled(value):
    """The placeholders that are still in `value` (a JSON value), in the order of PLACEHOLDERS."""
    words = json.dumps(value)
    return [p for p in PLACEHOLDERS if p in words]


def fill(value, values):
    """`value` (a JSON value) with each placeholder in its texts replaced: from `values` ({placeholder: text}), and __INSTRUCTIONS__
    with instructions.md when `values` doesn't give it. Raises KeyError with the placeholders that have no value."""
    values = dict(values)
    if "__INSTRUCTIONS__" in unfilled(value) and "__INSTRUCTIONS__" not in values:
        values["__INSTRUCTIONS__"] = instructions()
    missing = [p for p in unfilled(value) if p not in values]
    if missing:
        raise KeyError(missing)

    def walk(v):
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str):
            for p, text in values.items():
                v = v.replace(p, text)
        return v
    return walk(value)


def _show(v):
    return json.dumps(v, ensure_ascii=False)


def _same(want, got):
    """Two values that are not a dict or a list: text with no space at its ends, a number as a number, and true or false only as
    itself (1 is not true)."""
    if isinstance(want, str) and isinstance(got, str):
        return want.strip() == got.strip()
    if isinstance(want, bool) or isinstance(got, bool):
        return type(want) is type(got) and want == got
    return want == got


def differences(want, got, path=""):
    """Each place where `got` (a read-back) differs from `want` (a filled reference), as lines `<path>: <what differs>`. [] when
    `got` has each key of `want` with the same value."""
    if isinstance(want, dict):
        if not isinstance(got, dict):
            return [f"{path or 'the read-back'}: wants an object, has {_show(got)}"]
        out = []
        for k, v in want.items():
            at = f"{path}.{k}" if path else k
            out += differences(v, got[k], at) if k in got else [f"{at}: missing"]
        return out
    if isinstance(want, list):
        if not isinstance(got, list):
            return [f"{path}: wants a list, has {_show(got)}"]
        if len(want) != len(got):
            if all(not isinstance(x, (dict, list)) for x in want + got):
                return [f"{path}: wants {_show(want)}, has {_show(got)}"]
            return [f"{path}: wants {len(want)} item{'' if len(want) == 1 else 's'}, has {len(got)}"]
        out = []
        for i, (w, x) in enumerate(zip(want, got)):
            out += differences(w, x, f"{path}[{i}]")
        return out
    return [] if _same(want, got) else [f"{path}: wants {_show(want)}, has {_show(got)}"]


def pick(want, got):
    """A read-back that is a list of triggers (GET /api/agents/{id}/triggers): its item with the type and the name of `want`, or
    None. Any other read-back as it is."""
    if isinstance(want, dict) and isinstance(got, list):
        return next((t for t in got if isinstance(t, dict) and t.get("type") == want.get("type")
                     and t.get("name") == want.get("name")), None)
    return got


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fill or compare a reference file of the wizard agent App validation.")
    ap.add_argument("action", choices=("fill", "diff"))
    ap.add_argument("reference", choices=REFERENCES)
    ap.add_argument("readback", nargs="?", help="diff: the file with the App's answer")
    ap.add_argument("--set", action="append", default=[], metavar="PLACEHOLDER=VALUE")
    a = ap.parse_args(argv)
    values = {}
    for s in a.set:
        k, eq, v = s.partition("=")
        if not eq or k not in PLACEHOLDERS:
            ap.error(f"--set takes PLACEHOLDER=VALUE, and the placeholders are: {', '.join(PLACEHOLDERS)}")
        values[k] = v
    try:
        want = fill(load(a.reference), values)
    except KeyError as e:
        print("No value for " + ", ".join(e.args[0]) + ". Add " + " ".join(f"--set {p}=<value>" for p in e.args[0]) + ".",
              file=sys.stderr)
        return 2
    if a.action == "fill":
        print(json.dumps(want, indent=2, ensure_ascii=False))
        return 0
    if not a.readback:
        ap.error("diff needs the file with the App's answer")
    try:
        got = json.loads(Path(a.readback).read_text())
    except (OSError, ValueError) as e:
        print(f"Can't read {a.readback} as JSON: {e}", file=sys.stderr)
        return 2
    item = pick(want, got)
    if item is None:
        print(f"No {want.get('type')} trigger named {want.get('name')!r} in {a.readback}.")
        return 1
    found = differences(want, item)
    for line in found:
        print(line)
    print(f"{len(found)} setting{'' if len(found) == 1 else 's'} differ{'s' if len(found) == 1 else ''} from {a.reference}." if found
          else f"Same as {a.reference}.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
