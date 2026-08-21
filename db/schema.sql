-- EvalMind SQLite schema
--
-- sessions: one row per evaluation run against a given AUT (Agent Under Test).
-- rounds:   one row per individual test round within a session, scoped to one
--           of the three evaluation categories (functionality/security/compliance).

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    aut_description TEXT NOT NULL,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS rounds (
    id               TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    category         TEXT NOT NULL CHECK (category IN ('functionality', 'security', 'compliance')),
    round_number     INTEGER NOT NULL,
    difficulty       TEXT,
    task             TEXT,
    output           TEXT,
    primary_scores   TEXT,     -- JSON-encoded object
    secondary_scores TEXT,     -- JSON-encoded object
    pass_fail        INTEGER,  -- 0 = fail, 1 = pass, NULL = not yet scored
    latency_ms       INTEGER,
    tokens_used      INTEGER,
    estimated_cost   REAL,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Rounds are always fetched per-session, ordered by category then round_number.
CREATE INDEX IF NOT EXISTS idx_rounds_session_category_round
    ON rounds (session_id, category, round_number);

-- final_reports: one row per session holding the Aggregator's (Block G)
-- fully-built FinalReport, serialized as JSON. session_id is the PRIMARY KEY
-- (not an autoincrement id / no separate index needed) since there is at
-- most one current final report per session -- rebuilding a report later
-- (db.store.insert_final_report) overwrites the existing row rather than
-- accumulating duplicates, keeping "fetch the report for this session" a
-- trivial primary-key lookup.
CREATE TABLE IF NOT EXISTS final_reports (
    session_id  TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    report_json TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
