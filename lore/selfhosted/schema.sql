-- Lore SQLite schema
-- Apply with: init_db() in db.py (enables WAL mode and foreign keys before execution)

CREATE TABLE IF NOT EXISTS concepts (
    concept_id           TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    type                 TEXT NOT NULL CHECK(type IN ('project','pattern','tool','testing','architecture')),
    content              TEXT NOT NULL,
    language             TEXT,
    when_to_use          TEXT NOT NULL,
    dont_use_when        TEXT,
    tags                 TEXT,               -- JSON array stored as text, e.g. '["python","cli"]'
    source_url           TEXT,
    author               TEXT,
    avg_rating           REAL DEFAULT 0,
    usage_count          INTEGER DEFAULT 0,
    time_saved_avg_hours REAL,
    created_at           TEXT,
    embedding            BLOB                -- raw float32 BLOB (when_to_use + name); vector queries go through Qdrant
);

CREATE TABLE IF NOT EXISTS links (
    link_id   TEXT PRIMARY KEY,
    from_id   TEXT NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    to_id     TEXT NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    rel       TEXT NOT NULL CHECK(rel IN ('uses','tested_by','extends','alternative_to','requires')),
    label     TEXT
);

CREATE TABLE IF NOT EXISTS ratings (
    rating_id    TEXT PRIMARY KEY,
    concept_id   TEXT NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    session_id   TEXT,
    outcome      INTEGER NOT NULL CHECK(outcome BETWEEN 1 AND 5),
    hours_saved  REAL,
    notes        TEXT,
    rated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_usage (
    session_id   TEXT NOT NULL,
    concept_id   TEXT NOT NULL,
    used_at      TEXT NOT NULL
);

-- Indexes for common access patterns
CREATE INDEX IF NOT EXISTS idx_links_from_id ON links(from_id);
CREATE INDEX IF NOT EXISTS idx_links_to_id   ON links(to_id);
CREATE INDEX IF NOT EXISTS idx_ratings_concept_id ON ratings(concept_id);
CREATE INDEX IF NOT EXISTS idx_session_usage_session_id ON session_usage(session_id);
CREATE INDEX IF NOT EXISTS idx_session_usage_concept_id ON session_usage(concept_id);
