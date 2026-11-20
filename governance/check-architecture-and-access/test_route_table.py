"""The unit test of the own tool route_table (tools/route_table.py). It calls the tool as a plain function: `@tool` gives back the
function as it is. It needs only the domino-agent package (or a domino-agent-service checkout on PYTHONPATH): no agent service and
no network. The file is next to definition.md, not in tools/, so `domino-agent deploy` does not upload it.

Run it in this folder:

  python -m unittest
"""
import json
import os
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from tools.route_table import route_table

PROJECT = Path(__file__).resolve().parents[2]   # the repo root, as the project folder of a task: the App's code is case_server/


def table(project, folder):
    """The tool's result for `folder`, called in the folder `project`. In a task, the tool's working folder is the project
    folder."""
    before = os.getcwd()
    os.chdir(project)
    try:
        return route_table(folder)
    finally:
        os.chdir(before)


def def_line(path, name):
    """The line of `def <name>(` in the file `path` (1 is the first), found in the text."""
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if line.lstrip().startswith((f"def {name}(", f"async def {name}(")):
            return n
    raise AssertionError(f"no def {name} in {path}")


class TheAppOfMain(unittest.TestCase):
    """The App's real code (case_server/ of this branch: on main, 5 MCP tools and 2 custom routes)."""

    def setUp(self):
        self.result = table(PROJECT, "case_server")

    def test_five_mcp_tools_and_two_custom_routes_each_with_its_handler_file_and_line(self):
        server = PROJECT / "case_server" / "server.py"
        want = [("MCP tool", "POST", f"/mcp (tool: {n})", n, "case_server/server.py", def_line(server, n))
                for n in ("get_alert", "get_customer_profile", "get_transactions", "close_alert", "escalate_to_sar")]
        want += [("route", "POST", "/reset", "reset", "case_server/server.py", def_line(server, "reset")),
                 ("route", "GET", "/", "case_board", "case_server/server.py", def_line(server, "case_board"))]
        got = [(r["kind"], r["method"], r["path"], r["handler"], r["file"], r["line"]) for r in self.result["rows"]]
        self.assertEqual(got, want)

    def test_close_alert_and_escalate_to_sar_read_the_identity_and_change_state(self):
        rows = {r["handler"]: r for r in self.result["rows"]}
        for name in ("close_alert", "escalate_to_sar"):
            self.assertEqual((rows[name]["reads_identity"], rows[name]["changes_state"]), (True, True), name)

    def test_post_reset_reads_no_identity_and_changes_state(self):
        rows = {r["handler"]: r for r in self.result["rows"]}
        self.assertEqual((rows["reset"]["reads_identity"], rows["reset"]["changes_state"]), (False, True))

    def test_get_slash_and_the_three_get_tools_change_nothing(self):
        rows = {r["handler"]: r for r in self.result["rows"]}
        for name in ("case_board", "get_alert", "get_customer_profile", "get_transactions"):
            self.assertEqual((rows[name]["reads_identity"], rows[name]["changes_state"]), (False, False), name)

    def test_each_yes_cites_its_evidence_and_each_no_has_none(self):
        """The file and line where the rule found the identity or the write: the header in acting_identity, the SQL in
        store.py."""
        server, store = (PROJECT / "case_server" / f for f in ("server.py", "store.py"))
        header = next(n for n, line in enumerate(server.read_text().splitlines(), 1) if '.get("domino-username")' in line)
        rows = {r["handler"]: r for r in self.result["rows"]}
        self.assertEqual(rows["close_alert"]["identity_at"], f"case_server/server.py:{header}")
        writes = {n for n, line in enumerate(store.read_text().splitlines(), 1)
                  if any(w in line for w in ('"UPDATE ', '"INSERT ', "'DROP TABLE"))}
        for name in ("close_alert", "escalate_to_sar", "reset"):
            file, _, line = rows[name]["changes_at"].partition(":")
            self.assertEqual(file, "case_server/store.py", name)
            self.assertIn(int(line), writes, name)
        self.assertEqual((rows["reset"]["identity_at"], rows["get_alert"]["changes_at"]), (None, None))

    def test_it_reads_each_file_of_the_folder_and_nothing_is_in_not_read(self):
        self.assertEqual((self.result["folder"], self.result["files"], self.result["not_read"]),
                         ("case_server", ["case_server/board.py", "case_server/server.py", "case_server/store.py"], []))

    def test_the_result_is_short(self):
        """Well under the 51,200 bytes of a result that opencode gives the model."""
        self.assertLess(len(json.dumps(self.result)), 8000)


class TheToolsDescription(unittest.TestCase):
    """The docstring is the tool's description: the model reads it in each call, and deploy refuses one of more than 2,000
    characters."""

    def test_it_fits_and_states_the_rules(self):
        doc = route_table.__doc__
        self.assertLessEqual(len(doc), 2000)
        for word in ("changes_state", "reads_identity", "domino-username", "not_read", "INSERT", "open", "global"):
            self.assertIn(word, doc)


class Samples(unittest.TestCase):
    """Small sample files, in a project folder of their own, with the App's code in app/."""

    def run_on(self, files):
        """The tool's result for app/, with `files` ({path in app/: text}) in a new project folder."""
        project = Path(tempfile.mkdtemp(prefix="route-table-"))
        self.addCleanup(shutil.rmtree, project)
        for rel, body in files.items():
            (project / "app" / rel).parent.mkdir(parents=True, exist_ok=True)
            (project / "app" / rel).write_text(textwrap.dedent(body))
        return table(project, "app")

    def rows(self, files):
        return {r["handler"]: r for r in self.run_on(files)["rows"]}

    def test_the_demo_branchs_post_upload_reads_no_identity_and_changes_nothing(self):
        # The route as the demo branch demo/app-validation has it in case_server/server.py (the planted yaml.full_load)
        row = self.rows({"server.py": UPLOAD})["upload"]
        self.assertEqual((row["kind"], row["method"], row["path"], row["file"], row["line"]),
                         ("route", "POST", "/upload", "app/server.py", line_of(UPLOAD, "async def upload(")))
        self.assertEqual((row["reads_identity"], row["changes_state"]), (False, False))

    def test_a_handler_reads_the_identity_through_a_function_of_the_same_file(self):
        rows = self.rows({"server.py": THROUGH_HELPERS, "people.py": OTHER_FILE})
        self.assertEqual((rows["whoami"]["reads_identity"], rows["whoami"]["identity_at"]),
                         (True, f"app/server.py:{line_of(THROUGH_HELPERS, 'return request.headers.get(')}"))
        self.assertEqual(rows["ping"]["reads_identity"], False, "a function of another file does not count")

    def test_a_decorator_that_the_tool_does_not_know_is_in_not_read(self):
        result = self.run_on({"server.py": UNKNOWN_DECORATORS})
        self.assertEqual([r["handler"] for r in result["rows"]], ["admin_reset"], "the handler still has its row")
        got = [(n["file"], n["line"], n["what"].split(":")[0]) for n in result["not_read"]]
        self.assertEqual(got, [("app/server.py", line_of(UNKNOWN_DECORATORS, "@login_required"),
                                "a decorator that the tool does not know, on the handler admin_reset"),
                               ("app/server.py", line_of(UNKNOWN_DECORATORS, '@app.get("/admin")'),
                                "a decorator with a path that the tool does not know, on the function admin_page")])
        self.assertIn("@login_required", result["not_read"][0]["what"])

    def test_a_file_that_is_not_valid_python_is_in_not_read_and_the_other_files_are_still_read(self):
        result = self.run_on({"broken.py": "def half(:\n    pass\n", "server.py": THROUGH_HELPERS, "people.py": OTHER_FILE})
        self.assertEqual(sorted(r["handler"] for r in result["rows"]), ["ping", "whoami"])
        self.assertEqual([(n["file"], n["line"]) for n in result["not_read"]], [("app/broken.py", 1)])
        self.assertTrue(result["not_read"][0]["what"].startswith("not valid Python"), result["not_read"])
        self.assertEqual(result["files"], ["app/broken.py", "app/people.py", "app/server.py"])

    def test_the_other_forms_of_the_two_decorators(self):
        result = self.run_on({"server.py": OTHER_FORMS})
        got = [(r["kind"], r["method"], r["path"], r["handler"]) for r in result["rows"]]
        self.assertEqual(got, [("MCP tool", "POST", "/mcp (tool: lookup)", "find_customer"),
                               ("MCP tool", "POST", "/mcp (tool: plain)", "plain"),
                               ("route", "GET, POST", "/both", "both")])
        self.assertEqual([(n["line"], n["what"].split(":")[0]) for n in result["not_read"]],
                         [(line_of(OTHER_FORMS, "@mcp.custom_route(PATH"), "a route whose path or methods are not plain values, "
                                                                           "on the handler hidden")])

    def test_the_writes_of_the_rule_change_state_and_a_text_about_a_write_does_not(self):
        rows = self.rows({"server.py": WRITES, "files.py": FILE_WRITES})
        want = {"save_note": ("app/files.py", "with open(path, \"a\")"), "drop_cache": ("app/files.py", "path.unlink()"),
                "count_up": ("app/server.py", "global COUNT"), "add_row": ("app/server.py", "db.execute(\"insert into")}
        for name, (file, start) in want.items():
            body = FILE_WRITES if file == "app/files.py" else WRITES
            self.assertEqual((rows[name]["changes_state"], rows[name]["changes_at"]), (True, f"{file}:{line_of(body, start)}"),
                             name)
        for name in ("read_note", "explain"):
            self.assertEqual((rows[name]["changes_state"], rows[name]["changes_at"]), (False, None), name)

    def test_a_hidden_folder_is_not_read(self):
        result = self.run_on({"server.py": UPLOAD, ".venv/lib/server.py": OTHER_FORMS})
        self.assertEqual((result["files"], [r["handler"] for r in result["rows"]]), (["app/server.py"], ["upload"]))

    def test_a_folder_that_is_not_in_the_project_folder_is_an_error(self):
        project = Path(tempfile.mkdtemp(prefix="route-table-"))
        self.addCleanup(shutil.rmtree, project)
        (project / "app").mkdir()
        for folder, why in (("..", "not in the project folder"), ("/etc", "not in the project folder"),
                            ("no-such-folder", "no folder")):
            with self.assertRaises(ValueError) as e:
                table(project, folder)
            self.assertIn(why, str(e.exception), folder)

    def test_a_clean_app_has_nothing_in_not_read(self):
        self.assertEqual(self.run_on({"server.py": UPLOAD})["not_read"], [])


UPLOAD = '''\
    from mcp.server.fastmcp import FastMCP
    from starlette.requests import Request
    from starlette.responses import JSONResponse


    def build_server(store, host, port):
        mcp = FastMCP("aml-case-management", host=host, port=port)

        # Not one of the server's tools either. It changes nothing: it reads an uploaded YAML file of alerts, for a test of a new seed.
        @mcp.custom_route("/upload", methods=["POST"])
        async def upload(request: Request) -> JSONResponse:
            """Read an uploaded YAML file ({"alerts": [...]}) and answer with how many alerts it holds."""
            import yaml   # pyyaml (case_server/requirements.txt). Only this route needs it.

            data = yaml.full_load(await request.body())
            alerts = data.get("alerts") if isinstance(data, dict) else None
            count = len(alerts) if isinstance(alerts, list) else 0
            log.info("upload: read %d alert(s)", count)
            return JSONResponse({"result": "read the upload", "alerts": count})

        return mcp
    '''
THROUGH_HELPERS = '''\
    from mcp.server.fastmcp import FastMCP
    from people import caller

    mcp = FastMCP("sample")


    def header_of(request):
        """The domino-username header (this docstring does not count)."""
        return request.headers.get("Domino-Username")


    def who(request):
        return header_of(request) or "nobody"


    @mcp.custom_route("/whoami", methods=["GET"])
    async def whoami(request):
        return who(request)


    @mcp.custom_route("/ping", methods=["GET"])
    async def ping(request):
        return caller(request)
    '''
OTHER_FILE = '''\
    def caller(request):
        return request.headers.get("domino-username")
    '''
UNKNOWN_DECORATORS = '''\
    from fastapi import FastAPI
    from mcp.server.fastmcp import FastMCP

    from auth import login_required

    mcp = FastMCP("sample")
    app = FastAPI()


    @mcp.custom_route("/admin/reset", methods=["POST"])
    @login_required
    async def admin_reset(request):
        return "done"


    @app.get("/admin")
    def admin_page():
        return "the admin page"
    '''


OTHER_FORMS = '''\
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("sample")
    PATH = "/hidden"


    @mcp.tool(name="lookup")
    def find_customer(customer_id: str) -> dict:
        return {}


    @mcp.tool
    def plain() -> str:
        return "a bare @mcp.tool"


    @mcp.custom_route("/both", ["GET", "post"])
    async def both(request):
        return "methods as the second argument"


    @mcp.custom_route(PATH, methods=["GET"])
    async def hidden(request):
        return "a path that is a name"
    '''


WRITES = '''\
    from mcp.server.fastmcp import FastMCP

    from files import append_note, clear_cache, note_text

    mcp = FastMCP("sample")
    COUNT = 0


    @mcp.tool()
    def save_note(text: str) -> str:
        return append_note(text)


    @mcp.tool()
    def read_note() -> str:
        return note_text()


    @mcp.custom_route("/cache", methods=["DELETE"])
    async def drop_cache(request):
        return clear_cache()


    @mcp.custom_route("/count", methods=["POST"])
    async def count_up(request):
        global COUNT
        COUNT += 1
        return COUNT


    @mcp.tool()
    def add_row(db, name: str) -> str:
        db.execute("insert into notes (name) values (?)", (name,))
        return "added"


    @mcp.tool()
    def explain() -> str:
        """UPDATE notes SET text = 'x' would change a note: this docstring changes nothing."""
        return "Delete from the cache with DELETE /cache."
    '''
FILE_WRITES = '''\
    from pathlib import Path

    NOTES = Path("notes.txt")


    def append_note(text):
        with open(path, "a") as f:
            f.write(text)
        return "saved"


    def note_text():
        with open(NOTES, "r") as f:
            return f.read()


    def clear_cache(path=Path("cache.json")):
        path.unlink()
        return "cleared"
    '''


def line_of(text, start):
    """The line of the sample `text` that starts with `start` (after its indent), as the sample file has it."""
    return next(n for n, line in enumerate(textwrap.dedent(text).splitlines(), 1) if line.lstrip().startswith(start))


if __name__ == "__main__":
    unittest.main()
