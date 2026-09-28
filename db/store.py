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
        _migrate_add_session_columns(conn)
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


def _migrate_add_session_columns(conn: sqlite3.Connection) -> None:
    """One-off migration for DBs created before `sessions` had agent_brief,
    project_id and session_meta. Same idea as _migrate_add_reasoning_column:
    PRAGMA table_info first, ALTER only what is missing, so it is a no-op on
    an up-to-date DB. The project_id index is created here (not in
    schema.sql) because on an old DB the column does not exist yet when
    schema.sql runs.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "agent_brief" not in existing:
        conn.execute("ALTER TABLE sessions ADD COLUMN agent_brief TEXT")
    if "project_id" not in existing:
        conn.execute(
            "ALTER TABLE sessions ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL"
        )
    if "session_meta" not in existing:
        conn.execute("ALTER TABLE sessions ADD COLUMN session_meta TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions (project_id)")
    conn.commit()


def insert_session(
    id: str,
    aut_description: str,
    db_path: Path = DEFAULT_DB_PATH,
    agent_brief: Optional[str] = None,
    project_id: Optional[str] = None,
    session_meta: Optional[dict[str, Any]] = None,
) -> None:
    """Insert a new evaluation session. started_at is set by the DB default.

    The extra fields are keyword-friendly and come AFTER db_path on purpose, so
    every pre-existing positional caller keeps working unchanged.
    - agent_brief: the optional free-text brief the user typed about the agent.
    - project_id: the project this session is grouped under (must exist).
    - session_meta: JSON-serializable snapshot of the connection/run settings
      (never credentials) -- stored as JSON text.
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sessions (id, aut_description, agent_brief, project_id, session_meta) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                id,
                aut_description,
                agent_brief,
                project_id,
                json.dumps(session_meta) if session_meta else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_session_description(
    session_id: str,
    aut_description: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Overwrite an existing session's aut_description.

    run_full_session() now creates the session row BEFORE the Describer runs
    (so a run that dies during discovery still leaves a trace in the DB), with
    a placeholder description; this swaps in the real, auto-discovered one
    once it is known. A no-op if the session id doesn't exist.
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE sessions SET aut_description = ? WHERE id = ?",
            (aut_description, session_id),
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


def list_sessions(limit: int = 50, db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Fetch the most-recent sessions (up to `limit`), newest first.
    Returns lightweight rows: id, aut_description, started_at.
    A final_report row existing means the session completed.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT s.id, s.aut_description, s.started_at, s.project_id, s.session_meta,
                   p.name AS project_name,
                   CASE WHEN fr.session_id IS NOT NULL THEN 1 ELSE 0 END AS has_report
            FROM sessions s
            LEFT JOIN final_reports fr ON fr.session_id = s.id
            LEFT JOIN projects p ON p.id = s.project_id
            ORDER BY s.started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    results: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        # session_meta is a JSON blob; only the agent's display name is surfaced
        # on the lightweight history rows.
        meta_raw = d.pop("session_meta", None)
        agent_name = None
        if meta_raw:
            try:
                agent_name = (json.loads(meta_raw) or {}).get("agent_name")
            except (TypeError, ValueError):
                agent_name = None
        d["agent_name"] = agent_name
        results.append(d)
    return results


def delete_session(session_id: str, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Delete a session and all its rounds + final_report (CASCADE).
    Returns True if a row was deleted, False if the id didn't exist.
    """
    conn = _connect(db_path)
    try:
        cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ==========================================================================
# Projects -- an organizational layer above sessions. A session keeps its own
# unique id; project_id is just an optional grouping pointer on the session row.
# ==========================================================================
def create_project(
    id: str,
    name: str,
    description: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Insert a project and return it (with session_count = 0)."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO projects (id, name, description) VALUES (?, ?, ?)",
            (id, name, description),
        )
        conn.commit()
    finally:
        conn.close()
    created = get_project(id, db_path=db_path)
    assert created is not None  # just inserted
    return created


def list_projects(db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """All projects (alphabetical) with how many sessions each one holds."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.description, p.created_at,
                   COUNT(s.id) AS session_count
            FROM projects p
            LEFT JOIN sessions s ON s.project_id = p.id
            GROUP BY p.id
            ORDER BY p.name COLLATE NOCASE
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_project(project_id: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[dict[str, Any]]:
    """One project (with session_count), or None if it doesn't exist."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT p.id, p.name, p.description, p.created_at,
                   COUNT(s.id) AS session_count
            FROM projects p
            LEFT JOIN sessions s ON s.project_id = p.id
            WHERE p.id = ?
            GROUP BY p.id
            """,
            (project_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def find_project_by_name(name: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[dict[str, Any]]:
    """Case-insensitive exact-name lookup, used to stop duplicate project names."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, name, description, created_at FROM projects WHERE name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def set_session_project(
    session_id: str,
    project_id: Optional[str],
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """Move a session into a project (or out of one with project_id=None).
    Returns False if the session id doesn't exist. The caller is expected to
    have checked that project_id exists (foreign keys are enforced).
    """
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "UPDATE sessions SET project_id = ? WHERE id = ?",
            (project_id, session_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_round_scores(
    round_id: str,
    primary_scores: dict[str, Any],
    secondary_scores: dict[str, Any],
    reasoning: str,
    pass_fail: bool,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Overwrite the judge scores on an existing round row (used by the
    re-judge endpoint). Does not change task/output/latency/tokens/cost —
    only the scoring columns.
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            UPDATE rounds
            SET primary_scores = ?, secondary_scores = ?, reasoning = ?, pass_fail = ?
            WHERE id = ?
            """,
            (
                json.dumps(primary_scores),
                json.dumps(secondary_scores),
                reasoning,
                int(pass_fail),
                round_id,
            ),
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
