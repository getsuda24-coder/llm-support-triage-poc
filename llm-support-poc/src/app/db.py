from __future__ import annotations

import os
import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional, Any


def _utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def get_db_path() -> str:
    return os.getenv("DB_PATH", "/app/data/app.db")


def connect() -> sqlite3.Connection:
    path = get_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [r["name"] for r in cur.fetchall()]
    return column in cols


def init_db() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        subject TEXT NOT NULL,
        requester_email TEXT NOT NULL,
        body TEXT NOT NULL,
        priority TEXT NOT NULL,
        status TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        llm_provider TEXT NOT NULL,
        llm_model TEXT NOT NULL,
        draft_reply TEXT NOT NULL,
        risk_score REAL NOT NULL,
        routing TEXT NOT NULL,
        rag_sources TEXT,
        rag_context TEXT,
        agent_trace TEXT,
        FOREIGN KEY(ticket_id) REFERENCES tickets(id)
    );

    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        action TEXT NOT NULL,
        final_reply TEXT,
        reviewer TEXT NOT NULL,
        FOREIGN KEY(ticket_id) REFERENCES tickets(id)
    );

    CREATE TABLE IF NOT EXISTS kb_docs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        source TEXT NOT NULL,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        metadata_json TEXT NOT NULL
    );
    """
    with db() as conn:
        conn.executescript(schema)

        # migrate older DBs
        if not _has_column(conn, "drafts", "rag_sources"):
            conn.execute("ALTER TABLE drafts ADD COLUMN rag_sources TEXT")
        if not _has_column(conn, "drafts", "rag_context"):
            conn.execute("ALTER TABLE drafts ADD COLUMN rag_context TEXT")
        if not _has_column(conn, "drafts", "agent_trace"):
            conn.execute("ALTER TABLE drafts ADD COLUMN agent_trace TEXT")

        # FTS5 KB index
        conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS kb_docs_fts
                USING fts5(title, text, content='kb_docs', content_rowid='id');"""
        )

        # Triggers to keep FTS in sync
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS kb_docs_ai AFTER INSERT ON kb_docs BEGIN
              INSERT INTO kb_docs_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
            END;

            CREATE TRIGGER IF NOT EXISTS kb_docs_ad AFTER DELETE ON kb_docs BEGIN
              INSERT INTO kb_docs_fts(kb_docs_fts, rowid, title, text) VALUES('delete', old.id, old.title, old.text);
            END;

            CREATE TRIGGER IF NOT EXISTS kb_docs_au AFTER UPDATE ON kb_docs BEGIN
              INSERT INTO kb_docs_fts(kb_docs_fts, rowid, title, text) VALUES('delete', old.id, old.title, old.text);
              INSERT INTO kb_docs_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
            END;
            """
        )


# Tickets
def insert_ticket(subject: str, requester_email: str, body: str, priority: str) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO tickets (created_at, subject, requester_email, body, priority, status) VALUES (?, ?, ?, ?, ?, ?)",
            (_utcnow_iso(), subject, requester_email, body, priority, "open"),
        )
        return int(cur.lastrowid)


def list_tickets(limit: int = 200) -> list[sqlite3.Row]:
    with db() as conn:
        cur = conn.execute("SELECT * FROM tickets ORDER BY id DESC LIMIT ?", (limit,))
        return list(cur.fetchall())


def get_ticket(ticket_id: int) -> Optional[sqlite3.Row]:
    with db() as conn:
        cur = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        return cur.fetchone()


def set_ticket_status(ticket_id: int, status: str) -> None:
    with db() as conn:
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))


# Drafts
def insert_draft(
    ticket_id: int,
    llm_provider: str,
    llm_model: str,
    draft_reply: str,
    risk_score: float,
    routing: str,
    rag_sources: list[str],
    rag_context: Optional[str],
    agent_trace: list[dict[str, Any]],
) -> int:
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO drafts (ticket_id, created_at, llm_provider, llm_model, draft_reply, risk_score, routing, rag_sources, rag_context, agent_trace)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ticket_id,
                _utcnow_iso(),
                llm_provider,
                llm_model,
                draft_reply,
                float(risk_score),
                routing,
                json.dumps(rag_sources, ensure_ascii=False),
                rag_context,
                json.dumps(agent_trace, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)


def get_latest_draft(ticket_id: int) -> Optional[sqlite3.Row]:
    with db() as conn:
        cur = conn.execute("SELECT * FROM drafts WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (ticket_id,))
        return cur.fetchone()


# Decisions
def insert_decision(ticket_id: int, action: str, final_reply: Optional[str], reviewer: str) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO decisions (ticket_id, created_at, action, final_reply, reviewer) VALUES (?, ?, ?, ?, ?)",
            (ticket_id, _utcnow_iso(), action, final_reply, reviewer),
        )
        return int(cur.lastrowid)


def get_latest_decision(ticket_id: int) -> Optional[sqlite3.Row]:
    with db() as conn:
        cur = conn.execute("SELECT * FROM decisions WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (ticket_id,))
        return cur.fetchone()


# Knowledge base (RAG)
import re

_FTS_TOKEN_RE = re.compile(r'"[^"]*"|\(|\)|\S+')

def _normalize_fts_query(q: str) -> str:
    """Make a SQLite FTS5 query safer by quoting tokens with special chars
    (e.g. INV-2099, emails). Keeps operators AND/OR/NOT and parentheses.
    """
    parts = []
    for m in _FTS_TOKEN_RE.finditer(q.strip()):
        tok = m.group(0)
        if tok in ("(", ")"):
            parts.append(tok)
            continue
        if tok.startswith('"') and tok.endswith('"'):
            parts.append(tok)
            continue
        up = tok.upper()
        if up in ("AND", "OR", "NOT", "NEAR"):
            parts.append(up)
            continue
        if re.fullmatch(r"[A-Za-z0-9_]+", tok):
            parts.append(tok)
            continue
        safe = tok.replace('"', '""')
        parts.append(f'"{safe}"')
    return " ".join(parts).strip()

def kb_add_doc(source: str, title: str, text: str, metadata: dict[str, Any]) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO kb_docs (created_at, source, title, text, metadata_json) VALUES (?, ?, ?, ?, ?)",
            (_utcnow_iso(), source, title, text, json.dumps(metadata, ensure_ascii=False)),
        )
        return int(cur.lastrowid)


def kb_get_doc(doc_id: int) -> Optional[sqlite3.Row]:
    with db() as conn:
        cur = conn.execute("SELECT * FROM kb_docs WHERE id = ?", (doc_id,))
        return cur.fetchone()


def kb_search(query: str, limit: int = 5) -> list[sqlite3.Row]:
    sql = """SELECT d.id, d.source, d.title, d.text, d.metadata_json, bm25(kb_docs_fts) AS rank
               FROM kb_docs_fts
               JOIN kb_docs d ON d.id = kb_docs_fts.rowid
               WHERE kb_docs_fts MATCH ?
               ORDER BY rank
               LIMIT ?"""
    with db() as conn:
        try:
            cur = conn.execute(sql, (query, limit))
        except sqlite3.OperationalError:
            q2 = _normalize_fts_query(query)
            cur = conn.execute(sql, (q2, limit))
        return list(cur.fetchall())
