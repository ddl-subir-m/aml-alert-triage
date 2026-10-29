"""The case-management system's state: one SQLite file at AML_DB_PATH, loaded from the seed on the first start."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

SEED = Path(__file__).with_name("seed.json")

SCHEMA = (
    """CREATE TABLE customers (
        customer_id TEXT PRIMARY KEY, name TEXT NOT NULL, segment TEXT NOT NULL, kyc_risk_rating TEXT NOT NULL,
        occupation TEXT NOT NULL, expected_monthly_activity REAL NOT NULL, country TEXT NOT NULL, pep INTEGER NOT NULL)""",
    """CREATE TABLE transactions (
        transaction_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers, date TEXT NOT NULL,
        amount REAL NOT NULL, currency TEXT NOT NULL, type TEXT NOT NULL, counterparty TEXT NOT NULL, country TEXT NOT NULL,
        memo TEXT NOT NULL)""",
    """CREATE TABLE alerts (
        alert_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers, rule TEXT NOT NULL, score REAL NOT NULL,
        status TEXT NOT NULL, flagged_transaction_ids TEXT NOT NULL)""",
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
        today = date.today()
        for c in seed["customers"]:
            db.execute("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (c["customer_id"], c["name"], c["segment"], c["kyc_risk_rating"], c["occupation"],
                        c["expected_monthly_activity"], c["country"], int(c["pep"])))
        for t in seed["transactions"]:
            day = (today - timedelta(days=t["days_ago"])).isoformat()
            db.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (t["transaction_id"], t["customer_id"], day, t["amount"], t["currency"], t["type"],
                        t["counterparty"], t["country"], t["memo"]))
        for a in seed["alerts"]:
            db.execute("INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?)",
                       (a["alert_id"], a["customer_id"], a["rule"], a["score"], a["status"],
                        json.dumps(a["flagged_transaction_ids"])))

    def get_alert(self, alert_id: str) -> dict[str, Any]:
        with self._tx() as db:
            row = db.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
        if row is None:
            raise Refused(f"No alert {alert_id}. Check the alert ID.")
        return {"alert_id": row["alert_id"], "customer_id": row["customer_id"], "rule": row["rule"], "score": row["score"],
                "status": row["status"], "flagged_transaction_ids": json.loads(row["flagged_transaction_ids"])}
