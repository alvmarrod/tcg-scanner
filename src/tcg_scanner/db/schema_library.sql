-- User data. Never rebuilt, backed up as-is.
--
-- `printing_id` points into catalog.db, which SQLite cannot enforce across
-- files; catalog and library are always opened together by callers that
-- resolve a printing.

CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL,
    sha256      TEXT NOT NULL UNIQUE,
    width       INTEGER,
    height      INTEGER,
    captured_at TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY,
    photo_id    INTEGER NOT NULL REFERENCES photos (id),
    -- NULL when nothing matched; the attempt is still recorded.
    printing_id INTEGER,
    confidence  REAL,
    method      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'accepted', 'rejected')),
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_matches_photo ON matches (photo_id);

CREATE TABLE IF NOT EXISTS owned (
    id          INTEGER PRIMARY KEY,
    printing_id INTEGER NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    condition   TEXT,
    language    TEXT,
    acquired_at TEXT,
    paid_price  REAL,
    currency    TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
