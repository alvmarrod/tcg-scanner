-- User data. Never rebuilt, backed up as-is.
--
-- Rows identify catalog printings by (card_code, print_index) and keep their own
-- snapshot of the printing. catalog.db is disposable: a rebuild can renumber
-- print indexes, so looked-up data is only trusted when the snapshot still
-- matches; otherwise the snapshot is shown and prices are skipped.

CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL,
    sha256      TEXT NOT NULL UNIQUE,
    width       INTEGER,
    height      INTEGER,
    captured_at TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    id            INTEGER PRIMARY KEY,
    photo_id      INTEGER NOT NULL REFERENCES photos (id),
    -- NULL when nothing matched; the attempt is still recorded.
    card_code     TEXT,
    print_index   INTEGER,
    card_name     TEXT,
    set_code      TEXT,
    variant_label TEXT,
    image_url     TEXT,
    confidence    REAL,
    method        TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'accepted', 'rejected')),
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_matches_photo ON matches (photo_id);

CREATE TABLE IF NOT EXISTS owned (
    id            INTEGER PRIMARY KEY,
    card_code     TEXT NOT NULL,
    print_index   INTEGER NOT NULL,
    -- Snapshot of the printing as it was when the user confirmed it.
    card_name     TEXT,
    set_code      TEXT,
    variant_label TEXT,
    image_url     TEXT,
    quantity      INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    condition     TEXT,
    language      TEXT,
    acquired_at   TEXT,
    paid_price    REAL,
    currency      TEXT,
    note          TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
