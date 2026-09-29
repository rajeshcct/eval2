-- EvalMind SQLite schema
--
-- projects: an organizational layer ABOVE sessions. A project groups related
--           evaluation sessions (e.g. all runs against one product). A session
--           still has its own unique id -- the project is purely additive.
-- sessions: one row per evaluation run against a given AUT (Agent Under Test).
-- rounds:   one row per individual test round within a session, scoped to one
--           of the three evaluation categories (functionality/security/compliance).
--
-- Hierarchy:  Project -> Sessions -> Rounds
--
-- NOTE: columns added to `sessions` after the first release (agent_brief,
-- project_id, session_meta) are also applied to already-existing databases by
-- db.store._migrate_add_session_columns(), since CREATE TABLE IF NOT EXISTS
-- never alters a table that already exists.

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    aut_description TEXT NOT NULL,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    agent_brief     TEXT,      -- optional free-text brief the user gave about the agent
    project_id      TEXT REFERENCES projects(id) ON DELETE SET NULL,
    session_meta    TEXT       -- JSON: connection + run configuration snapshot (never secrets)
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
    reasoning        TEXT,     -- Judge's short (2-4 sentence) explanation for the verdict
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

-- users: simple username / bcrypt-hashed password store for the login system.
-- No roles or permissions yet — every authenticated user can see and run
-- everything. The first user is created via POST /api/auth/register (open the
-- first time, then locked behind FIRST_USER_REGISTERED flag in the DB).
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    username     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT,
    password_hash TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

