"""SQLite store: one file holds the watcher cursor, tickets, sends and the event log.

Every state change is a single SQL statement or a short transaction, so two
processes (a watcher and a dispatcher) can share the file safely.
"""
import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS cursor (
    source TEXT PRIMARY KEY,
    last_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE,
    source_msg_id TEXT UNIQUE NOT NULL,   -- one ticket per inbound message, ever
    thread TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready', -- ready | claimed | done | needs_human
    claimed_by TEXT,
    lease_expires REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    summary TEXT,
    evidence TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sends (
    idem_key TEXT PRIMARY KEY,            -- a message is sent at most once per key
    thread TEXT NOT NULL,
    text TEXT NOT NULL,
    sent_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    ticket_id INTEGER,
    kind TEXT NOT NULL,
    data TEXT
);
"""


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    # cursor ---------------------------------------------------------------
    def get_cursor(self, source: str) -> Optional[str]:
        row = self.db.execute("SELECT last_id FROM cursor WHERE source=?", (source,)).fetchone()
        return row["last_id"] if row else None

    def set_cursor(self, source: str, last_id: str) -> None:
        self.db.execute(
            "INSERT INTO cursor(source,last_id) VALUES(?,?) "
            "ON CONFLICT(source) DO UPDATE SET last_id=excluded.last_id",
            (source, last_id),
        )

    # events ---------------------------------------------------------------
    def event(self, kind: str, ticket_id: Optional[int] = None, **data: Any) -> None:
        self.db.execute(
            "INSERT INTO events(at,ticket_id,kind,data) VALUES(?,?,?,?)",
            (time.time(), ticket_id, kind, json.dumps(data, sort_keys=True)),
        )

    def events(self, ticket_id: Optional[int] = None) -> List[Dict[str, Any]]:
        q, args = "SELECT * FROM events", ()
        if ticket_id is not None:
            q, args = q + " WHERE ticket_id=?", (ticket_id,)
        return [dict(r) for r in self.db.execute(q + " ORDER BY id", args)]

    # tickets --------------------------------------------------------------
    def open_ticket(self, source_msg_id: str, thread: str, body: str, prefix: str = "E") -> Optional[int]:
        """Create a ticket for an inbound message. Returns None if one already exists."""
        now = time.time()
        cur = self.db.execute(
            "INSERT OR IGNORE INTO tickets(source_msg_id,thread,body,created_at,updated_at) "
            "VALUES(?,?,?,?,?)",
            (source_msg_id, thread, body, now, now),
        )
        if cur.rowcount == 0:
            return None
        tid = cur.lastrowid
        self.db.execute("UPDATE tickets SET code=? WHERE id=?", (f"{prefix}{tid}", tid))
        self.event("opened", tid, source_msg_id=source_msg_id)
        return tid

    def claim(self, worker: str, lease_s: float = 900) -> Optional[sqlite3.Row]:
        """Atomically claim one ready ticket, or one whose lease expired (crashed worker)."""
        now = time.time()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT id FROM tickets WHERE status='ready' "
                "OR (status='claimed' AND lease_expires < ?) ORDER BY id LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                self.db.execute("COMMIT")
                return None
            self.db.execute(
                "UPDATE tickets SET status='claimed', claimed_by=?, lease_expires=?, "
                "attempts=attempts+1, updated_at=? WHERE id=?",
                (worker, now + lease_s, now, row["id"]),
            )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.event("claimed", row["id"], worker=worker)
        return self.ticket(row["id"])

    def finish(self, tid: int, status: str, summary: str, evidence: Dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE tickets SET status=?, summary=?, evidence=?, lease_expires=NULL, updated_at=? WHERE id=?",
            (status, summary, json.dumps(evidence, sort_keys=True), time.time(), tid),
        )
        self.event(status, tid, summary=summary)

    def ticket(self, tid: int) -> sqlite3.Row:
        return self.db.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()

    def tickets(self) -> List[sqlite3.Row]:
        return list(self.db.execute("SELECT * FROM tickets ORDER BY id"))

    # sends ----------------------------------------------------------------
    def record_send(self, idem_key: str, thread: str, text: str) -> bool:
        """Reserve a send. False means this exact send already happened."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO sends(idem_key,thread,text,sent_at) VALUES(?,?,?,?)",
            (idem_key, thread, text, time.time()),
        )
        return cur.rowcount == 1
