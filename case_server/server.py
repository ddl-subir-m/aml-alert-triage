"""The case-management system: a fake one, served as an MCP server over streamable HTTP at /mcp.

On Domino it runs as the App aml-case-management: app.sh starts it on port 8888. Locally:
  mkdir -p /tmp/aml && AML_DB_PATH=/tmp/aml/cases.db PORT=8890 python case_server/server.py
Then the MCP URL is http://localhost:8890/mcp.

Settings (environment variables):
  AML_DB_PATH    the SQLite state file (required). Its folder must exist; the server never makes it.
  HOST, PORT     where to listen (default 0.0.0.0 and 8888, as a Domino App must).
  AML_SEED_PATH  the seed to load into an empty state file (default: seed.json next to this file).
"""
import logging
import os
import sys
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from store import SEED, CaseStore, Refused

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("aml")


@contextmanager
def refusals_as_tool_errors():
    """A refusal reaches the MCP client as a tool error (isError true) with the reason."""
    try:
        yield
    except Refused as e:
        raise ToolError(str(e)) from e


def log_call(ctx: Context, tool: str, **args: Any) -> None:
    """Log a tool call with the names of its request headers, so the log shows what the Apps proxy sends.
    Never the values: one of them is a token."""
    request = ctx.request_context.request  # None when the call didn't come over HTTP
    headers = sorted(request.headers.keys()) if request is not None else []
    log.info("tool call: %s(%s) headers: %s", tool, ", ".join(f"{k}={v!r}" for k, v in args.items()), " ".join(headers))


def build_server(store: CaseStore, host: str, port: int) -> FastMCP:
    mcp = FastMCP(
        "aml-case-management",
        instructions="A fake case-management system for AML alert triage. All its data is fake.",
        host=host,
        port=port,
        stateless_http=True,  # no MCP session to lose when the App restarts
        json_response=True,
        # The same in a local run (127.0.0.1) as on Domino (0.0.0.0): the Apps proxy sends its own Host header.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    def get_alert(alert_id: str, ctx: Context) -> dict[str, Any]:
        """Read one alert by its ID (for example A-1001): the customer, the monitoring rule that flagged it, the score,
        the status (open, closed or escalated) and the IDs of the flagged transactions. A closed or escalated alert also
        has who acted (acted_by) and when (acted_at, UTC); a closed one has its reason_code and rationale."""
        log_call(ctx, "get_alert", alert_id=alert_id)
        with refusals_as_tool_errors():
            return store.get_alert(alert_id)

    @mcp.tool()
    def get_customer_profile(customer_id: str, ctx: Context) -> dict[str, Any]:
        """Read one customer's KYC profile by its ID (for example C-2001; an alert names its customer): the name, the
        segment, the KYC risk rating (low, medium or high), the occupation, the expected monthly activity in USD, the
        country and the PEP flag (true when the customer is a politically exposed person)."""
        log_call(ctx, "get_customer_profile", customer_id=customer_id)
        with refusals_as_tool_errors():
            return store.get_customer_profile(customer_id)

    @mcp.tool()
    def get_transactions(customer_id: str, ctx: Context, days: int = 90) -> dict[str, Any]:
        """Read one customer's transactions of the last `days` days (default 90, from 1 to 3650), oldest first. Each has
        its ID, date, amount, currency, type, counterparty, country (where the money came from or went to) and memo."""
        log_call(ctx, "get_transactions", customer_id=customer_id, days=days)
        with refusals_as_tool_errors():
            return store.get_transactions(customer_id, days)

    return mcp


def state_file() -> Path:
    """The SQLite file at AML_DB_PATH. Stops the server when its folder is missing, so it never runs on state that a
    restart would lose (on Domino, the folder is the AML project's dataset aml-cases)."""
    if not os.environ.get("AML_DB_PATH"):
        sys.exit("Set AML_DB_PATH to the state file, for example /tmp/aml/cases.db. On Domino, app.sh sets it.")
    path = Path(os.environ["AML_DB_PATH"])
    if not path.parent.is_dir():
        sys.exit(f"The state folder {path.parent} doesn't exist. Create the dataset aml-cases in the AML project, "
                 f"then restart the App. (Locally, make the folder or set AML_DB_PATH to a file in a folder that exists.)")
    return path


if __name__ == "__main__":
    path = state_file()
    store = CaseStore(path, os.environ.get("AML_SEED_PATH") or SEED)
    host, port = os.environ.get("HOST", "0.0.0.0"), int(os.environ.get("PORT", "8888"))
    log.info("case-management system: mcp %s, state %s (%s), MCP at http://%s:%s/mcp", version("mcp"), path,
             f"loaded the seed {store.seed_path}" if store.loaded_seed else "kept the state", host, port)
    build_server(store, host, port).run(transport="streamable-http")
