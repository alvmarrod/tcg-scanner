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
- Per card: card code (e.g. `OP01-001`), name, type, color, cost, power, and links
  to TCGplayer and Cardmarket prices.
- The source does not expose rarity; print labels (`aa`, …) are what distinguish
  variants.

Art variants (alternate arts, alternate rarities) can share a card code, so the unit
that is recognized, stored and priced is the *printing*, not the card.

Card images and text are Eiichiro Oda / Shueisha, Toei Animation and Bandai copyright.
Anything downloaded is for local matching only, not redistribution. Requests are
throttled; sync one set at a time and do not hammer the source.

## Storage

SQLite, one file per store, images on disk content-addressed. Two databases, because
they have different lifetimes:

- `catalog.db` — reference data scraped from the source. Disposable and rebuildable.
- `library.db` — user photos, matches and owned cards. Never rebuilt; backed up.

A printing is identified by `(card_code, print_index)` — alternate arts share a card
code, so the print ordinal is what tells them apart. User rows also keep a snapshot of
the printing; catalog data is only trusted while the snapshot still matches, so a
rebuild that renumbers prints cannot silently repoint a card.

Schema versions live in `PRAGMA user_version`. The SQL files are the frozen version-1
baseline; later changes are ordered migrations in `db/conn.py` and run on open.

## Usage

```sh
uv run tcg-scanner db init
uv run tcg-scanner catalog sync --set OP08
uv run tcg-scanner catalog sync --set OP08 --no-images
uv run tcg-scanner prices refresh
uv run tcg-scanner index build
uv run tcg-scanner inspect path/to/photo.jpg
uv run tcg-scanner identify path/to/photo.jpg
uv run tcg-scanner matches accept 12
uv run tcg-scanner owned list
uv run tcg-scanner owned add OP08-001 1
uv run tcg-scanner owned update 3 --quantity 2
uv run tcg-scanner owned remove 3
uv run tcg-scanner eval data/eval/labels.csv
```

`catalog sync` needs network access. It stores the set's cards, printings, prices and
reference images under `data/`, and is incremental: re-running adds only new price
points and missing images. Image downloads use a small worker pool while request
starts stay throttled.

`prices refresh` appends only price points that changed, for one `--set` or every
synced set. It never creates printings, so run `catalog sync` first. There is no
built-in scheduler: run it from cron or a systemd timer if you want a cadence.

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
`owned add <card_code> <print_index>` adds a card by hand. Re-adding the same
printing, condition and language increments the quantity instead of creating a new
row; `owned update <id>` edits a row and `owned remove <id>` deletes it. `owned list`
prints the collection total for the chosen price source, ignoring rows whose printing
no longer resolves.

`eval` scores recognition against a labels CSV with `image,card_code,print_index`
(paths relative to the CSV; `print_index` is optional). It reports card and printing
accuracy, OCR rates, the top-1 score distribution for correct vs. wrong matches, and
the misses. `--json` emits the same report as JSON.

## Development

Requires [uv](https://docs.astral.sh/uv/). The virtualenv and Python version are
managed per-repo.

```sh
uv sync --extra recognition  # .venv + dependencies (including torch)
uv run pre-commit install    # git hooks
```

`uv sync` alone installs everything except the model stack; `index`, `inspect`,
`identify` and `eval` then exit with a message telling you to add the extra.

```sh
uv run pre-commit run --all-files
uv run ruff check .
uv run pytest
```

## Install as a tool

```sh
uv tool install ".[recognition]"
tcg-scanner --help
```

Data defaults to the checkout's `data/` directory when running from a checkout, and to
`./data` when installed as a tool. Set `TCG_SCANNER_DATA` to use another directory.

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

Phases 1–7 are in place: storage, catalog sync, the DINOv2 index, rectification, OCR,
matching, match confirmation, and the evaluation harness. The harness still needs a
labeled set of real photos before model and threshold decisions. Python 3.14.
