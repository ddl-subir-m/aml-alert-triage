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
)


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
        return alert

    def get_alert(self, alert_id: str) -> dict[str, Any]:
        with self._tx() as db:
            row = db.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
        if row is None:
            raise Refused(f"No alert {alert_id}. Check the alert ID.")
        return self._alert(row)

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
