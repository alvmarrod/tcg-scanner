-- Reference data, rebuildable from the source. Never holds user data.
--
-- A printing is identified by (card_code, print_index): alternate arts share a
-- card code and the print label, so only the source's print ordinal tells them
-- apart. User data stores that key plus a snapshot, never a surrogate id, so a
-- catalog rebuild cannot repoint it.

CREATE TABLE IF NOT EXISTS sets (
    code         TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('booster', 'starter', 'promo')),
    release_date TEXT
);

CREATE TABLE IF NOT EXISTS cards (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    card_type   TEXT,
    color       TEXT,
    cost        INTEGER,
    power       INTEGER,
    counter     INTEGER,
    life        INTEGER,
    attribute   TEXT,
    traits      TEXT,
    effect_text TEXT,
    set_code    TEXT NOT NULL REFERENCES sets (code)
);

CREATE TABLE IF NOT EXISTS printings (
    card_code     TEXT NOT NULL REFERENCES cards (code),
    -- Print ordinal within the card, as assigned by the source (0 = first print).
    print_index   INTEGER NOT NULL,
    set_code      TEXT NOT NULL REFERENCES sets (code),
    rarity        TEXT NOT NULL DEFAULT 'unknown',
    -- 'base' unless the source marks an alternate art/rarity. Not unique: two
    -- prints of the same card can carry the same label.
    variant_label TEXT NOT NULL DEFAULT 'base',
    image_url     TEXT,
    tcgplayer_id  TEXT,
    cardmarket_id TEXT,
    PRIMARY KEY (card_code, print_index)
);

CREATE TABLE IF NOT EXISTS card_images (
    id          INTEGER PRIMARY KEY,
    card_code   TEXT NOT NULL,
    print_index INTEGER NOT NULL,
    path        TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    width       INTEGER,
    height      INTEGER,
    origin      TEXT NOT NULL DEFAULT 'reference',
    FOREIGN KEY (card_code, print_index)
        REFERENCES printings (card_code, print_index) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_card_images_printing ON card_images (card_code, print_index);

-- Append-only: one row per observation, never updated.
CREATE TABLE IF NOT EXISTS prices (
    card_code   TEXT NOT NULL,
    print_index INTEGER NOT NULL,
    source      TEXT NOT NULL,
    currency    TEXT NOT NULL,
    amount      REAL NOT NULL,
    fetched_at  TEXT NOT NULL,
    FOREIGN KEY (card_code, print_index)
        REFERENCES printings (card_code, print_index) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_prices_lookup
    ON prices (card_code, print_index, source, fetched_at);

-- Derived and rebuildable. `kind` is 'global' for the descriptor, 'patch' for
-- local tokens used on close calls.
CREATE TABLE IF NOT EXISTS embeddings (
    card_image_id INTEGER NOT NULL REFERENCES card_images (id) ON DELETE CASCADE,
    model         TEXT NOT NULL,
    dim           INTEGER NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'global' CHECK (kind IN ('global', 'patch')),
    vector        BLOB NOT NULL,
    PRIMARY KEY (card_image_id, model, kind)
);

CREATE VIEW IF NOT EXISTS latest_prices AS
SELECT card_code, print_index, source, currency, amount, fetched_at
FROM (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY card_code, print_index, source ORDER BY fetched_at DESC
    ) AS rn
    FROM prices
)
WHERE rn = 1;
