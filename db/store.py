"""
db/store.py

SQLite access layer for EvalMind. Wraps db/schema.sql with plain Python
functions — no ORM. Every function accepts an optional db_path override
(handy for tests / smoke checks); it defaults to db/evalmind.db.
"""
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

DEFAULT_DB_PATH = Path(__file__).parent / "evalmind.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

VALID_CATEGORIES = ("functionality", "security", "compliance")


def _connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Create the sessions/rounds tables (and index) if they don't already exist."""
    conn = _connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
        _migrate_add_reasoning_column(conn)
    finally:
        conn.close()


def _migrate_add_reasoning_column(conn: sqlite3.Connection) -> None:
    """One-off migration for DBs created before the `reasoning` column existed
    on `rounds` (schema.sql's CREATE TABLE IF NOT EXISTS only applies to a
    table that doesn't exist yet -- it never alters an already-existing one).
    Safe to call every init_db(): checks PRAGMA table_info first and is a
    no-op if the column is already there.
    """
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(rounds)").fetchall()}
    if "reasoning" not in existing_columns:
        conn.execute("ALTER TABLE rounds ADD COLUMN reasoning TEXT")
        conn.commit()


def insert_session(
    id: str,
    aut_description: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Insert a new evaluation session. started_at is set by the DB default."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sessions (id, aut_description) VALUES (?, ?)",
            (id, aut_description),
        )
        conn.commit()
    finally:
        conn.close()


def get_session(session_id: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[dict[str, Any]]:
    """Fetch one session row (id, aut_description, started_at), or None if it
    doesn't exist. Added for Block G's Aggregator, which needs a session's
    aut_description to build a self-contained FinalReport from session_id
    alone -- no existing store.py function returned the session row itself,
    only get_rounds_for_session() for its rounds.
    """
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def insert_round(
    id: str,
    session_id: str,
    category: str,
    round_number: int,
    difficulty: Optional[str] = None,
    task: Optional[str] = None,
    output: Optional[str] = None,
    primary_scores: Optional[dict[str, Any]] = None,
    secondary_scores: Optional[dict[str, Any]] = None,
    reasoning: Optional[str] = None,
    pass_fail: Optional[bool] = None,
    latency_ms: Optional[int] = None,
    tokens_used: Optional[int] = None,
    estimated_cost: Optional[float] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Insert one test round. primary_scores/secondary_scores are dicts, stored as JSON.
    reasoning is the Judge's short free-text explanation (agents.schemas.JudgeScore.reasoning),
    stored as plain text.
    """
    if category not in VALID_CATEGORIES:
        raise ValueError(f"category must be one of {VALID_CATEGORIES}, got {category!r}")

    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO rounds (
                id, session_id, category, round_number, difficulty, task, output,
                primary_scores, secondary_scores, reasoning, pass_fail,
                latency_ms, tokens_used, estimated_cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                id,
                session_id,
                category,
                round_number,
                difficulty,
                task,
                output,
                json.dumps(primary_scores) if primary_scores is not None else None,
                json.dumps(secondary_scores) if secondary_scores is not None else None,
                reasoning,
                None if pass_fail is None else int(pass_fail),
                latency_ms,
                tokens_used,
                estimated_cost,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_rounds_for_session(session_id: str, db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Fetch all rounds for a session, ordered by category then round_number.
    JSON columns are decoded back into dicts; pass_fail is decoded back into a bool.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM rounds
            WHERE session_id = ?
            ORDER BY category, round_number
            """,
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    results = []
    for row in rows:
        d = dict(row)
        d["primary_scores"] = json.loads(d["primary_scores"]) if d["primary_scores"] else None
        d["secondary_scores"] = json.loads(d["secondary_scores"]) if d["secondary_scores"] else None
        d["pass_fail"] = None if d["pass_fail"] is None else bool(d["pass_fail"])
        results.append(d)
    return results


def insert_final_report(
    session_id: str,
    report_json: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Persist (or refresh) the Aggregator's (Block G) FinalReport for a
    session. report_json is the already-serialized JSON string (see
    aggregator.FinalReport.model_dump_json()) -- this function does not know
    or care about the report's shape, same as how primary_scores/
    secondary_scores are opaque JSON blobs to insert_round() above.

    One row per session_id: INSERT ... ON CONFLICT DO UPDATE, so calling
    aggregator.build_final_report() again later (e.g. a standalone "reload
    the report" call, or simply re-running the aggregation step) refreshes
    the stored copy and its created_at timestamp in place rather than
    accumulating duplicate rows for the same session.
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO final_reports (session_id, report_json, created_at)
            VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(session_id) DO UPDATE SET
                report_json = excluded.report_json,
                created_at = excluded.created_at
            """,
            (session_id, report_json),
        )
        conn.commit()
    finally:
        conn.close()


def get_final_report(session_id: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[dict[str, Any]]:
    """Fetch the stored final_reports row (session_id, report_json,
    created_at) for a session, or None if none has been generated yet.
    report_json is returned as the raw JSON string, undecoded -- deserialize
    it with aggregator.FinalReport.model_validate_json() to get a typed
    object back. Note that aggregator.build_final_report() always rebuilds
    the report fresh from the sessions/rounds tables rather than reading it
    back through this function (see that module's docstring) -- this getter
    exists so the persisted report is independently queryable by session_id
    (per the Block G spec) without forcing a caller to re-run the
    aggregation (and its LLM call) just to look at what was last stored.
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM final_reports WHERE session_id = ?", (session_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None
