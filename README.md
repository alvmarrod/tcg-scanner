# tcg-scanner

Identify One Piece TCG cards from photos, and keep track of the ones you own with
their current price.

## Focus for now: recognition

Given a set of photos of a card, find the matching card in a card database.

Everything downstream of that — how recognitions are grouped into batches, where and
how they are stored, and how they are exposed (input folder, API, UI) — is undecided
and will be designed later. The recognition path is the only part being shaped now.

See [docs/recognition.md](docs/recognition.md) for the recognition design.

## Planned flow

1. **Ingest** — one or more photos of a single card.
2. **Identify** — match the photos against a local card database that holds card
   metadata and reference images.
3. **Record** — store the identified card, its printing/variant, and its price in a
   local database, after the user confirms the match.

User data and reference data follow different rules:

- **User data** exists only on user input and is persisted after user confirmation.
- **Reference data** is pulled from the online source on demand; a fetch stores what
  it retrieved even when it yields no match, and later fetches update it
  incrementally (new sets, refreshed prices).

## Card data

Source: <https://onepiece.limitlesstcg.com/cards>

- Products: booster sets (`OP*`, `EB*`, `PRB*`), starter decks (`ST*`), and a separate
  promos page.
- Per card: card code (e.g. `OP01-001`), name, rarity, color, cost, power, and links
  to TCGplayer and Cardmarket prices.

Art variants (alternate arts, alternate rarities) can share a card code, so the unit
that is recognized, stored and priced is the *printing*, not the card.

Card images and text are Eiichiro Oda / Shueisha, Toei Animation and Bandai copyright.
Anything downloaded is for local matching only, not redistribution.

## Storage

SQLite, one file per store, images on disk content-addressed. Two databases, because
they have different lifetimes:

- `catalog.db` — reference data scraped from the source. Disposable and rebuildable.
- `library.db` — user photos, matches and owned cards. Never rebuilt; backed up.

## Usage

```sh
uv run tcg-scanner db init
uv run tcg-scanner catalog sync --set OP08
uv run tcg-scanner catalog sync --set OP08 --no-images
uv run tcg-scanner index build
uv run tcg-scanner inspect path/to/photo.jpg
uv run tcg-scanner identify path/to/photo.jpg
uv run tcg-scanner matches accept 12
uv run tcg-scanner owned list
```

`catalog sync` needs network access. It stores the set's cards, printings, prices and
reference images under `data/`, and is incremental: re-running adds only new price
points and missing images.

`index build` embeds every reference image that has no vector yet. The first run
downloads the DINOv2 weights (~85 MB); it uses CUDA when available.

`inspect` rectifies a photo to the canonical card size, writes it to `data/output/`
and reads the card code. The first run downloads the EasyOCR models (~100 MB).

`identify` rectifies, reads the code, ranks printings against the reference index and
records the attempt in `library.db` as a pending match. The code is used as a filter
when it can be read.

`matches accept <id>` marks a pending match accepted and adds its printing to the
collection; `matches reject <id>` closes it without touching the collection.
`owned list` shows the collection with the latest catalog prices, and
`owned add <printing_id>` adds a card by hand.

## Development

Requires [uv](https://docs.astral.sh/uv/). The virtualenv and Python version are
managed per-repo.

```sh
uv sync                      # .venv + dependencies
uv run pre-commit install    # git hooks
```

```sh
uv run pre-commit run --all-files
uv run ruff check .
uv run pytest
```

Layout:

```
src/tcg_scanner/   package
docs/              design notes
data/              local only, git-ignored
  input/           photos to process
  output/          recognition results
  db/              catalog.db, library.db
  images/          content-addressed image store
```

## Status

Catalog storage, sync (single set, `OP08`) and the DINOv2 reference index are in place.
Rectification, OCR and matching are next. Python 3.14.
