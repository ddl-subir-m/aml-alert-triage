"""The case-management system's state: one SQLite file at AML_DB_PATH, loaded from the seed on the first start."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SEED = Path(__file__).with_name("seed.json")
MAX_DAYS = 3650  # the widest window get_transactions takes: 10 years
STATUSES = ("open", "closed", "escalated")  # open moves to closed or to escalated; both are final
REASON_CODES = ("false_positive", "explained_activity", "duplicate")  # why an alert was closed


def today() -> date:
    """Today in UTC. Each date in the state is a UTC date, so the server's time zone doesn't move the 90-day window."""
    return datetime.now(timezone.utc).date()


def timestamp(days_ago: int = 0) -> str:
    """Now, or days_ago days before now, in UTC to the second (2026-10-17T15:04:05Z).
    Each "when" in the state has this form."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _one_of(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


SCHEMA = (
    """CREATE TABLE customers (
        customer_id TEXT PRIMARY KEY, name TEXT NOT NULL, segment TEXT NOT NULL, kyc_risk_rating TEXT NOT NULL,
        occupation TEXT NOT NULL, expected_monthly_activity_usd REAL NOT NULL, country TEXT NOT NULL, pep INTEGER NOT NULL)""",
    """CREATE TABLE transactions (
        transaction_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers, date TEXT NOT NULL,
        amount REAL NOT NULL, currency TEXT NOT NULL, type TEXT NOT NULL, counterparty TEXT NOT NULL, country TEXT NOT NULL,
        memo TEXT NOT NULL)""",
    # acted_by and acted_at: who closed or escalated the alert (the acting identity), and when. Empty while it is open.
    # reason_code and rationale: why it was closed. Empty unless it is closed.
    f"""CREATE TABLE alerts (
        alert_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers, rule TEXT NOT NULL, score REAL NOT NULL,
        status TEXT NOT NULL CHECK (status IN ({_one_of(STATUSES)})), flagged_transaction_ids TEXT NOT NULL,
        acted_by TEXT, acted_at TEXT, reason_code TEXT CHECK (reason_code IN ({_one_of(REASON_CODES)})), rationale TEXT)""",
    # The investigation record that an escalation opens. An alert has at most one (UNIQUE alert_id).
    # opened_by and opened_at: who escalated the alert (the acting identity), and when.
    """CREATE TABLE sar_cases (
        sar_case_id TEXT PRIMARY KEY, alert_id TEXT NOT NULL UNIQUE REFERENCES alerts, narrative TEXT NOT NULL,
        transaction_ids TEXT NOT NULL, opened_by TEXT NOT NULL, opened_at TEXT NOT NULL)""",
)
FIRST_SAR_CASE = 5001  # SAR case IDs are SAR-5001, SAR-5002, ... in the order the escalations come


class Refused(Exception):
    """A request that the case-management system refuses. The message says why; the client sees it as a tool error."""


class CaseStore:
    def __init__(self, db_path: str | Path, seed_path: str | Path = SEED):
        self.seed_path = Path(seed_path)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        # A Domino dataset is an NFS mount: no WAL, full syncs, and only this process opens the file
        # (the settings domino-agent-service uses on the same kind of mount).
        self._db.execute("PRAGMA journal_mode=DELETE")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA locking_mode=EXCLUSIVE")
        with self._tx() as db:
            self.loaded_seed = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'alerts'").fetchone() is None
            if self.loaded_seed:
                self._make_tables(db)

    def reset(self) -> dict[str, str]:
        """Make the tables again and load the seed: every change since the seed is gone, and so is every SAR case.
        It drops every table, so a state file from an older build, whose tables may not fit, works again.
        -> each alert's status."""
        with self._tx() as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()
            for (name,) in tables:
                db.execute(f'DROP TABLE "{name}"')
            self._make_tables(db)
            return dict(db.execute("SELECT alert_id, status FROM alerts ORDER BY alert_id").fetchall())

    def _make_tables(self, db: sqlite3.Connection) -> None:
        for statement in SCHEMA:
            db.execute(statement)
        self._load_seed(db)

    @contextmanager
    def _tx(self):
        """One transaction: all of it is written, or none of it."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def _load_seed(self, db: sqlite3.Connection) -> None:
        seed = json.loads(self.seed_path.read_text())
        load_day = today()
        for c in seed["customers"]:
            db.execute("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (c["customer_id"], c["name"], c["segment"], c["kyc_risk_rating"], c["occupation"],
                        c["expected_monthly_activity_usd"], c["country"], int(c["pep"])))
        for t in seed["transactions"]:
            day = (load_day - timedelta(days=t["days_ago"])).isoformat()
            db.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (t["transaction_id"], t["customer_id"], day, t["amount"], t["currency"], t["type"],
                        t["counterparty"], t["country"], t["memo"]))
        for a in seed["alerts"]:  # an alert that is closed in the seed says who acted, and how many days ago
            acted_at = timestamp(a["acted_days_ago"]) if "acted_days_ago" in a else None
            db.execute("INSERT INTO alerts (alert_id, customer_id, rule, score, status, flagged_transaction_ids, acted_by, "
                       "acted_at, reason_code, rationale) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (a["alert_id"], a["customer_id"], a["rule"], a["score"], a["status"],
                        json.dumps(a["flagged_transaction_ids"]), a.get("acted_by"), acted_at, a.get("reason_code"),
                        a.get("rationale")))

    @staticmethod
    def _alert(row: sqlite3.Row) -> dict[str, Any]:
        """An alert as the tools answer it. A closed or escalated alert adds who acted and when; a closed one adds why."""
        alert = {"alert_id": row["alert_id"], "customer_id": row["customer_id"], "rule": row["rule"], "score": row["score"],
                 "status": row["status"], "flagged_transaction_ids": json.loads(row["flagged_transaction_ids"])}
        if row["status"] != "open":
            alert.update(acted_by=row["acted_by"], acted_at=row["acted_at"])
        if row["status"] == "closed":
            alert.update(reason_code=row["reason_code"], rationale=row["rationale"])
        if row["status"] == "escalated":
            alert.update(sar_case_id=row["sar_case_id"])
        return alert

    @staticmethod
    def _sar_case(row: sqlite3.Row) -> dict[str, Any]:
        return {"sar_case_id": row["sar_case_id"], "alert_id": row["alert_id"], "narrative": row["narrative"],
                "transaction_ids": json.loads(row["transaction_ids"]), "opened_by": row["opened_by"],
                "opened_at": row["opened_at"]}

    @staticmethod
    def _row(db: sqlite3.Connection, alert_id: str) -> sqlite3.Row:
        row = db.execute("SELECT alerts.*, sar_cases.sar_case_id FROM alerts LEFT JOIN sar_cases USING (alert_id) "
                         "WHERE alert_id = ?", (alert_id,)).fetchone()
        if row is None:
            raise Refused(f"No alert {alert_id}. Check the alert ID.")
        return row

    @staticmethod
    def _final(row: sqlite3.Row, change: str) -> Refused:
        """The refusal of a change to an alert that is closed or escalated: its decision is final."""
        if row["status"] == "closed":
            decision = f"closed: {row['acted_by']} closed it at {row['acted_at']} with the reason code {row['reason_code']}"
        else:
            decision = f"escalated to SAR case {row['sar_case_id']}: {row['acted_by']} escalated it at {row['acted_at']}"
        return Refused(f"Alert {row['alert_id']} is {decision}. That decision is final, so the alert can't be {change}.")

    def get_alert(self, alert_id: str) -> dict[str, Any]:
        with self._tx() as db:
            return self._alert(self._row(db, alert_id))

    def close_alert(self, alert_id: str, reason_code: str, rationale: str, acted_by: str) -> dict[str, Any]:
        """Close an open alert, as acted_by, now -> the closed alert."""
        with self._tx() as db:
            row = self._row(db, alert_id)
            if row["status"] != "open":
                raise self._final(row, "closed" if row["status"] == "escalated" else "closed again")
            if reason_code not in REASON_CODES:
                raise Refused(f"The reason code must be {', '.join(REASON_CODES[:-1])} or {REASON_CODES[-1]}, "
                              f"not {reason_code!r}.")
            if not rationale.strip():
                raise Refused("The rationale is empty. Say why the alert can be closed, and cite the evidence.")
            db.execute("UPDATE alerts SET status = 'closed', acted_by = ?, acted_at = ?, reason_code = ?, rationale = ? "
                       "WHERE alert_id = ?", (acted_by, timestamp(), reason_code, rationale, alert_id))
            return self._alert(self._row(db, alert_id))

    def escalate_to_sar(self, alert_id: str, narrative: str, transaction_ids: list[str], acted_by: str) -> dict[str, Any]:
        """Open a SAR case for an open alert, as acted_by, now -> the SAR case, with result "escalated".
        For an escalated alert -> its first SAR case, with result "already escalated", so a replayed call opens no other."""
        with self._tx() as db:
            row = self._row(db, alert_id)
            if row["status"] == "escalated":
                case = db.execute("SELECT * FROM sar_cases WHERE alert_id = ?", (alert_id,)).fetchone()
                return {"result": "already escalated", **self._sar_case(case)}
            if row["status"] == "closed":
                raise self._final(row, "escalated")
            if not narrative.strip():
                raise Refused("The narrative is empty. Say what is suspicious, and cite the transactions.")
            if not transaction_ids:
                raise Refused("The list of transaction IDs is empty. Name the transactions that support the escalation.")
            self._check_customer_transactions(db, row["customer_id"], transaction_ids)
            count = db.execute("SELECT COUNT(*) FROM sar_cases").fetchone()[0]
            sar_case_id, now = f"SAR-{FIRST_SAR_CASE + count}", timestamp()
            db.execute("INSERT INTO sar_cases VALUES (?, ?, ?, ?, ?, ?)",
                       (sar_case_id, alert_id, narrative, json.dumps(transaction_ids), acted_by, now))
            db.execute("UPDATE alerts SET status = 'escalated', acted_by = ?, acted_at = ? WHERE alert_id = ?",
                       (acted_by, now, alert_id))
            case = db.execute("SELECT * FROM sar_cases WHERE alert_id = ?", (alert_id,)).fetchone()
            return {"result": "escalated", **self._sar_case(case)}

    @staticmethod
    def _check_customer_transactions(db: sqlite3.Connection, customer_id: str, transaction_ids: list[str]) -> None:
        """Refuse transaction IDs that aren't the customer's: unknown ones, and those of another customer."""
        marks = ", ".join("?" * len(transaction_ids))
        owners = dict(db.execute(f"SELECT transaction_id, customer_id FROM transactions WHERE transaction_id IN ({marks})",
                                 transaction_ids).fetchall())
        unknown = [t for t in transaction_ids if t not in owners]
        others = [t for t in transaction_ids if t in owners and owners[t] != customer_id]
        if unknown or others:
            why = ([f"Unknown: {', '.join(unknown)}."] if unknown else []) + (
                [f"Another customer's: {', '.join(others)}."] if others else [])
            raise Refused(f"Name only transactions of the alert's customer {customer_id} (get_transactions lists them). "
                          f"{' '.join(why)}")

    def get_customer_profile(self, customer_id: str) -> dict[str, Any]:
        with self._tx() as db:
            row = db.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
        if row is None:
            raise Refused(f"No customer {customer_id}. Check the customer ID (an alert names its customer).")
        return {**dict(row), "pep": bool(row["pep"])}

    def get_transactions(self, customer_id: str, days: int) -> dict[str, Any]:
        if not 1 <= days <= MAX_DAYS:
            raise Refused(f"days must be from 1 to {MAX_DAYS}, not {days}.")
        since = (today() - timedelta(days=days)).isoformat()
        with self._tx() as db:
            if db.execute("SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)).fetchone() is None:
                raise Refused(f"No customer {customer_id}. Check the customer ID (an alert names its customer).")
            rows = db.execute("SELECT transaction_id, date, amount, currency, type, counterparty, country, memo "
                              "FROM transactions WHERE customer_id = ? AND date >= ? ORDER BY date, transaction_id",
                              (customer_id, since)).fetchall()
        return {"customer_id": customer_id, "days": days, "since": since, "transactions": [dict(r) for r in rows]}
