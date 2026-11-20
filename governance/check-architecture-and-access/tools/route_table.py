"""The own tool route_table of check 2, "Architecture and access". The agent sees it as own_route_table. It reads the App's Python
code with the standard library `ast`, and never imports or runs it. Its unit test is test_route_table.py, next to definition.md."""
import ast
import re
from pathlib import Path

from domino_agent import tool

MCP_ENDPOINT = "/mcp"   # FastMCP's streamable HTTP endpoint: each MCP tool call is a POST to it
IDENTITY_HEADER = "domino-username"   # the header in which the Apps proxy gives the caller's identity
# A SQL text that writes: it starts with one of these (case aside)
SQL_WRITE = re.compile(r"\s*(INSERT\s+(OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE\s+\S+\s+SET|DELETE\s+FROM"
                       r"|(CREATE|DROP|ALTER)\s+(TABLE|INDEX|VIEW|TRIGGER))\b", re.I)
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


@tool
def route_table(folder: str) -> dict:
    """The table of the ways into a Python App."""
    project = Path.cwd()
    modules = {}   # {file: its tree}
    for path in sorted((project / folder).rglob("*.py")):
        rel = path.relative_to(project).as_posix()
        modules[rel] = ast.parse(path.read_text(), filename=rel)
    functions = {rel: [fn for fn in ast.walk(tree) if isinstance(fn, FUNCTIONS)] for rel, tree in modules.items()}
    everywhere = _by_name((rel, fn) for rel, fns in functions.items() for fn in fns)
    rows = []
    for rel, fns in functions.items():
        same_file = _by_name((rel, fn) for fn in fns)
        for fn in fns:
            for dec in fn.decorator_list:
                row = _row(dec, fn, rel)
                if row:
                    identity_at = _find(rel, fn, _reads_identity, same_file, set())
                    changes_at = _find(rel, fn, _writes, everywhere, set())
                    rows.append({**row, "reads_identity": bool(identity_at), "identity_at": identity_at,
                                 "changes_state": bool(changes_at), "changes_at": changes_at})
    rows.sort(key=lambda r: (r["file"], r["line"]))
    return {"folder": folder, "rows": rows}


def _row(dec, fn, rel):
    """The row of the decorator `dec` on the function `fn`, or None when it is not a way into the App."""
    call = dec if isinstance(dec, ast.Call) else None
    func = call.func if call else dec
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr == "tool":
        return {"kind": "MCP tool", "method": "POST", "path": f"{MCP_ENDPOINT} (tool: {fn.name})", "handler": fn.name,
                "file": rel, "line": fn.lineno}
    if func.attr == "custom_route" and call:
        path = ast.literal_eval(call.args[0])
        methods = ast.literal_eval(next(k.value for k in call.keywords if k.arg == "methods"))
        return {"kind": "route", "method": ", ".join(methods), "path": path, "handler": fn.name, "file": rel,
                "line": fn.lineno}
    return None


def _by_name(pairs):
    """{function name: [(file, function), ...]}"""
    out = {}
    for rel, fn in pairs:
        out.setdefault(fn.name, []).append((rel, fn))
    return out


def _find(rel, fn, hit, index, seen):
    """"<file>:<line>" of the first place where `hit` finds something in the function `fn` (of the file `rel`), or in a function of
    `index` that it calls, found by the called name, at any depth. None when there is none."""
    if id(fn) in seen:
        return None
    seen.add(id(fn))
    line = hit(fn)
    if line:
        return f"{rel}:{line}"
    for name in _called(fn):
        for other_rel, other in index.get(name, ()):
            at = _find(other_rel, other, hit, index, seen)
            if at:
                return at
    return None


def _body(fn):
    """Each node of the body of the function `fn`, with no docstring and no other string statement (a text that runs nothing)."""
    said = {id(s.value) for s in ast.walk(fn) if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)}
    return [n for stmt in fn.body for n in ast.walk(stmt) if id(n) not in said]


def _texts(fn):
    """(line, text) of each string in the code of the function `fn`. A part of an f-string is a string too."""
    return [(n.lineno, n.value) for n in _body(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _called(fn):
    """The names that the function `fn` calls (`f(...)` and `x.f(...)`), in the order of the code."""
    calls = sorted((n for n in _body(fn) if isinstance(n, ast.Call)), key=lambda n: (n.lineno, n.col_offset))
    return [c.func.id if isinstance(c.func, ast.Name) else c.func.attr for c in calls
            if isinstance(c.func, (ast.Name, ast.Attribute))]


def _reads_identity(fn):
    """The first line of `fn` with the text domino-username, or None."""
    return min((line for line, s in _texts(fn) if s.strip().lower() == IDENTITY_HEADER), default=None)


def _writes(fn):
    """The first line of `fn` with a write, or None."""
    return min((line for line, s in _texts(fn) if SQL_WRITE.match(s)), default=None)
