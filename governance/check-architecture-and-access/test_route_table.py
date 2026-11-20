"""The unit test of the own tool route_table (tools/route_table.py). It calls the tool as a plain function: `@tool` gives back the
function as it is. It needs only the domino-agent package (or a domino-agent-service checkout on PYTHONPATH): no agent service and
no network. The file is next to definition.md, not in tools/, so `domino-agent deploy` does not upload it.

Run it in this folder:

  python -m unittest
"""
import os
import unittest
from pathlib import Path

from tools.route_table import route_table

PROJECT = Path(__file__).resolve().parents[2]   # the repo root, as the project folder of a task: the App's code is case_server/


def table(project, folder):
    """The tool's result for `folder`, called in the folder `project` (in a task, the tool's working folder is the project folder)."""
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
        """The file and line where the rule found the identity or the write: the header in acting_identity, the SQL in store.py."""
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


if __name__ == "__main__":
    unittest.main()
