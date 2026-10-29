"""The case-management system: a fake one, served as an MCP server over streamable HTTP at /mcp.

On Domino it runs as the App aml-case-management: app.sh starts it on port 8888. Locally:
  mkdir -p /tmp/aml && AML_DB_PATH=/tmp/aml/cases.db PORT=8890 python case_server/server.py
Then the MCP URL is http://localhost:8890/mcp. POST /reset (not one of the server's tools) loads the seed again.

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
from typing import Any, Mapping

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from store import SEED, CaseStore, Refused

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("aml")


def request_headers(ctx: Context) -> Mapping[str, str]:
    """The headers of the tool call's HTTP request (none when the call didn't come over HTTP)."""
    request = ctx.request_context.request
    return request.headers if request is not None else {}


@contextmanager
def tool_call(ctx: Context, tool: str, *, who: str | None = None, **args: Any):
    """One tool call. It logs the call with the names of its request headers, so the log shows what the Apps proxy sends.
    Never the values: one of them is a token. A write also logs who acts (see acting_identity). A refusal reaches the MCP
    client as a tool error (isError true) with the reason."""
    log.info("tool call: %s(%s)%s headers: %s", tool, ", ".join(f"{k}={v!r}" for k, v in args.items()),
             f" as {who}" if who else "", " ".join(sorted(request_headers(ctx).keys())))
    try:
        yield
    except Refused as e:
        raise ToolError(str(e)) from e


def acting_identity(ctx: Context) -> str:
    """Who acts: the domino-username header, which the Apps proxy sets to the acting identity. A missing or empty header,
    or Anonymous, is no identity (as domino-agent-service reads it), and the answer says so and why. It has spaces, so it
    can never be a Domino user name. Nobody has measured yet whether the proxy sets the header for an API caller of an App
    with extended identity off: the live check sees it in the record and in the log."""
    name = request_headers(ctx).get("domino-username")
    if name is None:
        return "no identity (the request had no domino-username header)"
    if not name.strip():
        return "no identity (the domino-username header was empty)"
    if name.strip().lower() == "anonymous":
        return f"no identity (the domino-username header was {name.strip()})"
    return name.strip()


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
        has who acted (acted_by) and when (acted_at, UTC). A closed one has its reason_code and rationale; an escalated
        one has its sar_case_id."""
        with tool_call(ctx, "get_alert", alert_id=alert_id):
            return store.get_alert(alert_id)

    @mcp.tool()
    def get_customer_profile(customer_id: str, ctx: Context) -> dict[str, Any]:
        """Read one customer's KYC profile by its ID (for example C-2001; an alert names its customer): the name, the
        segment, the KYC risk rating (low, medium or high), the occupation, the expected monthly activity in USD, the
        country and the PEP flag (true when the customer is a politically exposed person)."""
        with tool_call(ctx, "get_customer_profile", customer_id=customer_id):
            return store.get_customer_profile(customer_id)

    @mcp.tool()
    def get_transactions(customer_id: str, ctx: Context, days: int = 90) -> dict[str, Any]:
        """Read one customer's transactions of the last `days` days (default 90, from 1 to 3650), oldest first. Each has
        its ID, date, amount, currency, type, counterparty, country (where the money came from or went to) and memo."""
        with tool_call(ctx, "get_transactions", customer_id=customer_id, days=days):
            return store.get_transactions(customer_id, days)

    @mcp.tool()
    def close_alert(alert_id: str, reason_code: str, rationale: str, ctx: Context) -> dict[str, Any]:
        """Close an open alert. reason_code is false_positive, explained_activity or duplicate; the rationale says why,
        citing the evidence. Answers with the closed alert, which names who acted and when. A close is final. Refused (a
        tool error with the reason): another reason code, an empty rationale, and an alert that is closed or escalated."""
        who = acting_identity(ctx)
        with tool_call(ctx, "close_alert", who=who, alert_id=alert_id, reason_code=reason_code, rationale=rationale):
            return store.close_alert(alert_id, reason_code, rationale, who)

    @mcp.tool()
    def escalate_to_sar(alert_id: str, narrative: str, transaction_ids: list[str], ctx: Context) -> dict[str, Any]:
        """Escalate an open alert: open a SAR case with a narrative (what is suspicious) and the IDs of the transactions
        that support it, which must be transactions of the alert's customer. Answers with the SAR case: its ID
        (sar_case_id), who opened it and when, and result "escalated". An escalation is final. An alert has at most one
        SAR case: for an alert that is escalated already, it opens no other and answers with the first one and result
        "already escalated" (not an error). Refused (a tool error with the reason): a closed alert, an empty narrative,
        no transaction IDs, and a transaction ID that is unknown or another customer's."""
        who = acting_identity(ctx)
        with tool_call(ctx, "escalate_to_sar", who=who, alert_id=alert_id, narrative=narrative,
                       transaction_ids=transaction_ids):
            return store.escalate_to_sar(alert_id, narrative, transaction_ids, who)

    # Not one of the server's tools, so the tools route never offers it to an agent. Anyone who can open the App can call it.
    @mcp.custom_route("/reset", methods=["POST"])
    async def reset(request: Request) -> JSONResponse:
        """Load the seed again, for a repeat test: every alert open except alert 4, and no SAR cases."""
        alerts = store.reset()
        log.info("reset: made the tables again and loaded the seed %s", store.seed_path)
        return JSONResponse({"result": "loaded the seed", "alerts": alerts})

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
