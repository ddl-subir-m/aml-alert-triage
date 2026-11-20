"""The own tool route_table of check 2, "Architecture and access". The agent sees it as own_route_table. It reads the App's
Python code with the standard library `ast`, and never imports or runs it. Its unit test is test_route_table.py, next to
definition.md."""
import ast
import os
import re
from pathlib import Path

from domino_agent import tool

MCP_ENDPOINT = "/mcp"   # FastMCP's streamable HTTP endpoint: each MCP tool call is a POST to it
IDENTITY_HEADER = "domino-username"   # the header in which the Apps proxy gives the caller's identity
# A SQL text that writes starts with one of these, in upper or in lower case (_is_sql_write)
SQL_WRITE = re.compile(r"\s*(INSERT\s+(OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE\s+\S+\s+SET|DELETE\s+FROM"
                       r"|(CREATE|DROP|ALTER)\s+(TABLE|INDEX|VIEW|TRIGGER))\b", re.I)
# A call of one of these names writes a file or a folder (pathlib, os, shutil)
WRITE_CALLS = ("write_text", "write_bytes", "mkdir", "makedirs", "touch", "rename", "remove", "unlink", "rmdir", "rmtree")
FILE_MODE = re.compile(r"^[rwaxbt+]+$")   # the mode of open()
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
UNREAD = "unread"   # a way into the App that the tool can't read: it gets no row
OTHER = "other"     # a .tool or .custom_route decorator of a name that the file does not bind to FastMCP(...): it gets no row
GIVE = "Give the folder of the App's Python code, relative to the project folder, for example case_server"


@tool
def route_table(folder: str) -> dict:
    """The table of the ways into a Python App: each MCP tool (`@<server>.tool`) and each custom route (`@<server>.custom_route`)
    of its code. `<server>` is a name that the same file binds to `FastMCP(...)`. Give the folder of the App's Python code,
    relative to the project folder, such as `case_server`. The tool parses the code with `ast`, and never imports or runs it.

    The result has `folder`, `files` (the files that it read), `rows` and `not_read`. Each row has `kind` (`MCP tool` or
    `route`), `method`, `path` (for an MCP tool: the MCP endpoint and the tool's name, such as `/mcp (tool: get_alert)`),
    `handler`, `file` and `line` (of the handler's `def`), `reads_identity`, `identity_at`, `changes_state` and `changes_at`
    (`identity_at` and `changes_at`: the file and line of the evidence, or null).

    reads_identity: the handler, or a function of the same file that it calls (at any depth), has the text `domino-username`
    (the header with the caller's identity) in its code.

    changes_state: the handler, or a function of the App's code that it calls, has a write. The tool finds a called function by
    its name, at any depth, in each file. A write is one of these:
    - a SQL text that starts with INSERT INTO, REPLACE INTO, UPDATE ... SET, DELETE FROM, or CREATE, DROP or ALTER of a table,
      index, view or trigger;
    - `open` with a mode with w, a, x or +;
    - a call of write_text, write_bytes, mkdir, makedirs, touch, rename, remove, unlink, rmdir or rmtree;
    - a `global` or `nonlocal` statement.
    A docstring is not code. The tool does not follow a function of a package. So false means only that the rule found no write.

    not_read: each file that is not valid Python, each decorator that the tool does not know on a handler, each decorator with
    a path (it can be a route of another framework), and each route whose path or methods are not plain values. A tool or a
    route that the code adds with no decorator has no row."""
    project = Path.cwd().resolve()
    modules, not_read = {}, []   # {file: its tree}, [what the tool could not read]
    for path in _python_files(project, folder):
        rel = path.relative_to(project).as_posix()
        try:
            modules[rel] = ast.parse(path.read_bytes(), filename=rel)
        except (SyntaxError, ValueError) as e:   # ValueError: a null byte (before Python 3.12)
            not_read.append({"file": rel, "line": getattr(e, "lineno", None), "what": f"not valid Python: {e}"})
        except OSError as e:
            not_read.append({"file": rel, "line": None, "what": f"the file can't be read: {e.strerror}"})
    functions = {rel: [fn for fn in ast.walk(tree) if isinstance(fn, FUNCTIONS)] for rel, tree in modules.items()}
    everywhere = _by_name((rel, fn) for rel, fns in functions.items() for fn in fns)
    rows = []
    for rel, fns in functions.items():
        same_file = _by_name((rel, fn) for fn in fns)
        servers = _servers(modules[rel])
        for fn in fns:
            ways = [_way(dec, fn, servers) for dec in fn.decorator_list]
            for dec, way in zip(fn.decorator_list, ways):
                if way == UNREAD:
                    not_read.append({"file": rel, "line": dec.lineno, "what": "a route whose path or methods are not plain "
                                     f"values, on the handler {fn.name}: @{_shown(dec)}. It has no row"})
                elif way == OTHER:
                    not_read.append({"file": rel, "line": dec.lineno, "what": "a decorator that the tool does not know, on the "
                                     f"handler {fn.name}: @{_shown(dec)}. This file does not bind its name to FastMCP(...). It "
                                     "has no row"})
                elif way:
                    identity_at = _find(rel, fn, _reads_identity, same_file, set())
                    changes_at = _find(rel, fn, _writes, everywhere, set())
                    rows.append({**way, "handler": fn.name, "file": rel, "line": fn.lineno,
                                 "reads_identity": bool(identity_at), "identity_at": identity_at,
                                 "changes_state": bool(changes_at), "changes_at": changes_at})
                elif any(ways):
                    not_read.append({"file": rel, "line": dec.lineno, "what": "a decorator that the tool does not know, on the "
                                     f"handler {fn.name}: @{_shown(dec)}. It can change who can call the handler, or what it "
                                     "does"})
                elif _has_path(dec):
                    not_read.append({"file": rel, "line": dec.lineno, "what": "a decorator with a path that the tool does not "
                                     f"know, on the function {fn.name}: @{_shown(dec)}. It can be a route of another framework"})
    rows.sort(key=lambda r: (r["file"], r["line"]))
    not_read.sort(key=lambda n: (n["file"], n["line"] or 0))
    return {"folder": folder, "files": sorted(set(modules) | {n["file"] for n in not_read}), "rows": rows, "not_read": not_read}


def _python_files(project, folder):
    """The .py files of `folder` (relative to `project`), in the order of their paths. A hidden folder (such as .venv) and
    __pycache__ are not read. ValueError for a folder that is not in the project folder, or that does not exist."""
    base = (project / folder).resolve()
    if base != project and project not in base.parents:
        raise ValueError(f"the folder {folder!r} is not in the project folder. {GIVE}")
    if not base.is_dir():
        raise ValueError(f"no folder {folder!r} in the project folder. {GIVE}")
    found = []
    for dirpath, dirnames, filenames in os.walk(base):   # a link to a folder is not walked into
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        found += [Path(dirpath) / f for f in filenames if f.endswith(".py") and not f.startswith(".")]
    return sorted(found)


def _servers(tree):
    """The names that the module `tree` binds to `FastMCP(...)` (`mcp = FastMCP(...)`, also in a function): the App's servers."""
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, ast.Call) and _name(n.value) == "FastMCP":
            names |= {t.id for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)}
    return names


def _way(dec, fn, servers):
    """The start of a row ({"kind", "method", "path"}) for the decorator `dec` on the function `fn`: `@<server>.tool`, with or
    without its arguments (the tool's name is its `name`, else the function's name), or `@<server>.custom_route(path, methods)`.
    `<server>` is a name of `servers`. OTHER for `.tool` or `.custom_route` of another name. UNREAD for a custom route whose path
    or methods are not plain values. None for another decorator."""
    call = dec if isinstance(dec, ast.Call) else None
    func = call.func if call else dec
    if not isinstance(func, ast.Attribute) or func.attr not in ("tool", "custom_route"):
        return None
    if not isinstance(func.value, ast.Name) or func.value.id not in servers:
        return OTHER
    if func.attr == "tool":
        name = _value(_argument(call, 0, "name")) if call else None
        name = name if isinstance(name, str) else fn.name
        return {"kind": "MCP tool", "method": "POST", "path": f"{MCP_ENDPOINT} (tool: {name})"}
    path, methods = (_value(_argument(call, i, key)) for i, key in ((0, "path"), (1, "methods"))) if call else (None, None)
    if not isinstance(path, str) or not isinstance(methods, (list, tuple)) or not all(isinstance(m, str) for m in methods):
        return UNREAD
    return {"kind": "route", "method": ", ".join(m.upper() for m in methods), "path": path}


def _argument(call, position, keyword):
    """The argument of `call` at `position`, or the one named `keyword`, or None."""
    if len(call.args) > position:
        return call.args[position]
    return next((k.value for k in call.keywords if k.arg == keyword), None)


def _value(node):
    """The value of `node` when it is a plain value (a string, a list of strings, ...), else None."""
    try:
        return ast.literal_eval(node) if node is not None else None
    except (ValueError, TypeError, SyntaxError):
        return None


def _has_path(dec):
    """Is the decorator `dec` a call whose first argument is a path (a string that starts with /), as for a route of a
    framework?"""
    return (isinstance(dec, ast.Call) and bool(dec.args) and isinstance(dec.args[0], ast.Constant)
            and isinstance(dec.args[0].value, str) and dec.args[0].value.startswith("/"))


def _shown(node, limit=80):
    """The code of `node`, cut to `limit` characters."""
    text = ast.unparse(node)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _by_name(pairs):
    """{function name: [(file, function), ...]}"""
    out = {}
    for rel, fn in pairs:
        out.setdefault(fn.name, []).append((rel, fn))
    return out


def _find(rel, fn, hit, index, seen):
    """"<file>:<line>" of the first place where `hit` finds something in the function `fn` (of the file `rel`), or in a function
    of `index` that it calls, found by the called name, at any depth. None when there is none."""
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
    return [name for name in map(_name, calls) if name]


def _name(call):
    """The name that `call` calls: f of `f(...)` and of `x.f(...)`, or None for another form."""
    return call.func.id if isinstance(call.func, ast.Name) else call.func.attr if isinstance(call.func, ast.Attribute) else None


def _reads_identity(fn):
    """The first line of `fn` with the text domino-username, or None."""
    return min((line for line, s in _texts(fn) if s.strip().lower() == IDENTITY_HEADER), default=None)


def _writes(fn):
    """The first line of `fn` with a write of the rule (route_table's docstring), or None."""
    lines = [line for line, s in _texts(fn) if _is_sql_write(s)]
    for n in _body(fn):
        if isinstance(n, (ast.Global, ast.Nonlocal)):
            lines.append(n.lineno)
        elif isinstance(n, ast.Call) and (_name(n) in WRITE_CALLS or (_name(n) == "open" and _writes_a_file(n))):
            lines.append(n.lineno)
    return min(lines, default=None)


def _is_sql_write(text):
    """Is `text` a SQL text that writes? Its first word is in upper case or in lower case, as SQL is: "Delete from the cache" is
    a text for a person."""
    return bool(SQL_WRITE.match(text)) and (text.split()[0].isupper() or text.split()[0].islower())


def _writes_a_file(call):
    """Does the call `open(path, mode)` (or `path.open(mode)`) open the file to write: a mode with w, a, x or +?"""
    mode = _value(_argument(call, 1 if isinstance(call.func, ast.Name) else 0, "mode"))
    return isinstance(mode, str) and bool(FILE_MODE.match(mode)) and any(c in mode for c in "wax+")
