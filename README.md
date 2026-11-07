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
  promos index whose products are reprints with their own print entries.
- Per card: card code (e.g. `OP01-001`), name, type, color, cost, power, and links
  to TCGplayer and Cardmarket prices.
- The source does not expose rarity; print labels (`aa`, …) are what distinguish
  variants.

Art variants (alternate arts, alternate rarities) can share a card code, so the unit
that is recognized, stored and priced is the *printing*, not the card.

Some prints exist only in Japanese; their Japanese image is stored and the catalog
URL is updated to match.

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
uv run tcg-scanner db check
uv run tcg-scanner catalog sync --set OP01 --set OP02
uv run tcg-scanner catalog sync --all
uv run tcg-scanner catalog sync --promos
uv run tcg-scanner catalog sync --set OP08 --no-images
uv run tcg-scanner prices refresh
uv run tcg-scanner index build
uv run tcg-scanner inspect path/to/photo.jpg
uv run tcg-scanner identify path/to/photo.jpg          # JSON
uv run tcg-scanner identify --text path/to/photo.jpg   # human table
uv run tcg-scanner batch
uv run tcg-scanner serve
uv run tcg-scanner samples list
uv run tcg-scanner samples add photo.jpg OP15-001 0
uv run tcg-scanner matches list
uv run tcg-scanner matches accept 12
uv run tcg-scanner owned list
uv run tcg-scanner owned add OP08-001 1
uv run tcg-scanner owned update 3 --quantity 2
uv run tcg-scanner owned remove 3
uv run tcg-scanner eval data/eval/labels.csv
```

`catalog sync` needs network access. `--set` is repeatable, `--all` walks every
booster and starter product, and `--promos` walks the separate promo-product index. It stores the
set's cards, printings, prices and reference images under `data/`, and is incremental:
re-running adds only new price points and missing images. Image downloads use a small
worker pool while request starts stay throttled.

Reference images default to Japanese (`--lang jp`); pass `--lang en` for English.
Each stored image is tagged with its real language; when the requested language is
missing, the other language's asset is stored separately and reported as a fallback.
Misses are remembered and retried on every sync unless `--skip-missing` is passed.
Card names, text and prices always come from the English product data.

`db check` reports owned rows and open matches whose printing no longer resolves
against the catalog, missing or unreferenced image files, reference images without
vectors, and Japanese coverage/misses. It exits 1 when anything is off, so it works in
cron or CI.

`prices refresh` appends only price points that changed, for one `--set` or every
synced set. It never creates printings, so run `catalog sync` first. There is no
built-in scheduler: run it from cron or a systemd timer if you want a cadence.

`index build` embeds every reference image that has no vector yet. The first run
downloads the DINOv2 weights (~85 MB); it uses CUDA when available.

`inspect` rectifies a photo to the canonical card size, writes it to `data/output/`
and reads the card code. The first run downloads the EasyOCR models (~100 MB).

`identify` rectifies, reads the code and ranks printings against the reference index.
It is pure recognition: it never writes to `library.db`. It prints JSON by default
(schema 2): card corners, OCR code with confidence and box, the matched printing,
global and patch scores, which reference language was used, prices attached from the
catalog, and a `warnings` array. `--text` prints the simpler table. References are
preferred in Japanese (`--prefer en` to change); a fallback to English is reported,
never silent.

`batch` identifies every card in `data/input/` (or `--input DIR`). First-level folders
are one card each (`card-001/front.jpg`, `card-001/back.jpg`); loose images become
single-photo cards. Each group is fused (best score per printing, OCR majority,
outlier photos excluded with a warning) and written as one JSON report to
`data/output/<input-folder>/<group>.json`, alongside a `run.json` manifest. Nothing is
written to `library.db`. A broken file does not stop the run; the command exits 1 if
any file failed.

Confirmed photos can be kept as recognition samples: `samples add <image> <card_code>
<print_index>` stores the rectified image under `data/samples/<code>/<index>/`, tagged
`origin=user`; `samples list` and `samples remove` manage them. `index build` embeds
them, but matching and eval only use catalog references by default, so a wrong
confirmation cannot distort recognition.

`matches` and `owned` are the collection module. They operate on rows you create
manually (`owned add`) or record later through a future ingestion step; recognition no
longer produces matches. `matches list [--status …]` marks rows whose snapshot no
longer resolves as stale.
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

## Results website

`tcg-scanner serve` starts a local, read-only results browser (default
`http://127.0.0.1:9876`; `--host` and `--port` are configurable). Each folder under
`data/output/` is a run. The run page shows an album of input photos with their matched
reference image; clicking a tile opens a side-by-side comparison with OCR, candidates,
prices and warnings, plus previous/next navigation. Dark theme by default, light theme
available. It serves the FastAPI API and the built Svelte UI, and never writes to the
databases.

The UI source lives in `src/tcg_scanner/web/ui`; the built assets in `ui_build` are
committed so the tool works without Node. Rebuild after UI changes:

```sh
cd src/tcg_scanner/web/ui
npm install
npm run build
```

Uploading or triggering a scan from the browser is not implemented yet.

## Development

Requires [uv](https://docs.astral.sh/uv/). The virtualenv and Python version are
managed per-repo.

```sh
uv sync --extra recognition --extra web
uv run pre-commit install    # git hooks
```

`uv sync` alone installs everything except the model stack and the web server;
`index`, `inspect`, `identify`, `eval` and `serve` then tell you which extra to add.

```sh
uv run pre-commit run --all-files
uv run ruff check .
uv run pytest
```

## Install as a tool

```sh
uv tool install ".[recognition,web]"
tcg-scanner --help
```

Data defaults to the checkout's `data/` directory when running from a checkout, and to
`./data` when installed as a tool. Set `TCG_SCANNER_DATA` to use another directory.

Layout:

```
src/tcg_scanner/   package
  web/             FastAPI API + built Svelte UI
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
