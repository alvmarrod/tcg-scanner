from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from tcg_scanner import config
from tcg_scanner.catalog import Fetcher, sync_all, sync_promos, sync_sets
from tcg_scanner.db import init_catalog, init_library, open_catalog

if TYPE_CHECKING:
    from tcg_scanner.eval.run import Report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tcg-scanner",
        description="Identify One Piece TCG cards and track an owned collection.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    db = commands.add_parser("db", help="manage the local databases")
    db_commands = db.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser("init", help="create the catalog and library databases")
    db_commands.add_parser("check", help="report catalog/library and image drift")

    catalog = commands.add_parser("catalog", help="sync card reference data")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    sync = catalog_commands.add_parser("sync", help="sync sets from the card database")
    choose = sync.add_mutually_exclusive_group(required=True)
    choose.add_argument(
        "--set", action="append", metavar="CODE", help="set code, e.g. OP08 (repeatable)"
    )
    choose.add_argument("--all", action="store_true", help="every booster and starter set")
    choose.add_argument("--promos", action="store_true", help="every promo product")
    sync.add_argument(
        "--lang",
        default="jp",
        choices=["jp", "en"],
        help="reference image language (default: jp)",
    )
    sync.add_argument("--no-images", action="store_true", help="skip downloading card images")
    sync.add_argument(
        "--skip-missing",
        action="store_true",
        help="do not retry assets previously recorded as missing",
    )

    prices = commands.add_parser("prices", help="refresh price history")
    price_commands = prices.add_subparsers(dest="prices_command", required=True)
    price_refresh = price_commands.add_parser(
        "refresh", help="append changed price points for synced sets"
    )
    price_refresh.add_argument(
        "--set",
        action="append",
        metavar="CODE",
        help="limit to a set code (repeatable); default is every synced set",
    )

    index = commands.add_parser("index", help="build the recognition index")
    index_commands = index.add_subparsers(dest="index_command", required=True)
    build = index_commands.add_parser("build", help="embed reference images with DINOv2")
    build.add_argument("--batch-size", type=int, default=8, metavar="N")
    build.add_argument("--limit", type=int, default=None, metavar="N")

    inspect = commands.add_parser("inspect", help="rectify an image and read its card code")
    inspect.add_argument("image", type=Path, metavar="IMAGE")

    identify = commands.add_parser("identify", help="match a photo against the reference index")
    identify.add_argument("image", type=Path, metavar="IMAGE")
    identify.add_argument("--top", type=int, default=5, metavar="N")
    identify.add_argument(
        "--text", action="store_true", help="human-readable output instead of JSON"
    )
    identify.add_argument(
        "--prefer", choices=["jp", "en"], default="jp", help="preferred reference language"
    )

    matches = commands.add_parser("matches", help="accept or reject recorded matches")
    matches_commands = matches.add_subparsers(dest="matches_command", required=True)
    accept = matches_commands.add_parser(
        "accept", help="accept a match and add it to the collection"
    )
    accept.add_argument("match_id", type=int)
    accept.add_argument("--quantity", type=int, default=1)
    accept.add_argument("--condition")
    accept.add_argument("--language")
    reject = matches_commands.add_parser("reject", help="reject a pending match")
    reject.add_argument("match_id", type=int)
    matches_list = matches_commands.add_parser("list", help="list recorded matches")
    matches_list.add_argument(
        "--status",
        default="pending",
        choices=["pending", "accepted", "rejected", "all"],
    )

    owned = commands.add_parser("owned", help="manage the owned collection")
    owned_commands = owned.add_subparsers(dest="owned_command", required=True)
    owned_add = owned_commands.add_parser("add", help="add a printing to the collection")
    owned_add.add_argument("card_code", metavar="CARD_CODE")
    owned_add.add_argument("print_index", type=int, metavar="PRINT_INDEX")
    owned_add.add_argument("--quantity", type=int, default=1)
    owned_add.add_argument("--condition")
    owned_add.add_argument("--language")
    owned_add.add_argument("--paid", type=float, dest="paid_price")
    owned_add.add_argument("--currency")
    owned_add.add_argument("--note")
    owned_update = owned_commands.add_parser("update", help="edit an owned row")
    owned_update.add_argument("owned_id", type=int)
    owned_update.add_argument("--quantity", type=int, default=None)
    owned_update.add_argument("--condition")
    owned_update.add_argument("--language")
    owned_update.add_argument("--paid", type=float, dest="paid_price")
    owned_update.add_argument("--currency")
    owned_update.add_argument("--note")
    owned_remove = owned_commands.add_parser("remove", help="delete an owned row")
    owned_remove.add_argument("owned_id", type=int)
    owned_list = owned_commands.add_parser("list", help="list the collection with latest prices")
    owned_list.add_argument("--source", default="auto", choices=["auto", "eur", "usd"])

    samples = commands.add_parser("samples", help="manage confirmed user photo samples")
    sample_commands = samples.add_subparsers(dest="samples_command", required=True)
    sample_add = sample_commands.add_parser("add", help="store a confirmed photo as a sample")
    sample_add.add_argument("image", type=Path, metavar="IMAGE")
    sample_add.add_argument("card_code", metavar="CARD_CODE")
    sample_add.add_argument("print_index", type=int, metavar="PRINT_INDEX")
    sample_add.add_argument("--language", choices=["jp", "en"], default="jp")
    sample_list = sample_commands.add_parser("list", help="list confirmed samples")
    sample_list.add_argument("--card-code", default=None)
    sample_remove = sample_commands.add_parser("remove", help="delete a sample")
    sample_remove.add_argument("sample_id", type=int)

    batch = commands.add_parser("batch", help="identify every photo in a folder")
    batch.add_argument("--input", type=Path, default=None, metavar="DIR")
    batch.add_argument("--top", type=int, default=5, metavar="N")
    batch.add_argument("--prefer", choices=["jp", "en"], default="jp")

    review = commands.add_parser("review", help="inspect result feedback")
    review_commands = review.add_subparsers(dest="review_command", required=True)
    review_list = review_commands.add_parser("list", help="list recorded reviews")
    review_list.add_argument("--run", default=None)
    review_stats = review_commands.add_parser("stats", help="right/wrong statistics")
    review_stats.add_argument("--run", default=None)

    serve = commands.add_parser("serve", help="serve the results website")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=9876)

    evaluation = commands.add_parser("eval", help="score recognition against labeled photos")
    evaluation.add_argument(
        "labels", type=Path, nargs="?", default=None, metavar="CSV", help="labels CSV"
    )
    evaluation.add_argument("--top", type=int, default=5, metavar="N")
    evaluation.add_argument("--json", action="store_true", help="print the report as JSON")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    handlers = {
        ("db", "init"): _db_init,
        ("db", "check"): _db_check,
        ("catalog", "sync"): _catalog_sync,
        ("prices", "refresh"): _prices_refresh,
        ("index", "build"): _index_build,
        ("inspect", None): _inspect,
        ("identify", None): _identify,
        ("matches", "accept"): _matches_accept,
        ("matches", "reject"): _matches_reject,
        ("matches", "list"): _matches_list,
        ("owned", "add"): _owned_add,
        ("owned", "update"): _owned_update,
        ("owned", "remove"): _owned_remove,
        ("owned", "list"): _owned_list,
        ("samples", "add"): _samples_add,
        ("samples", "list"): _samples_list,
        ("samples", "remove"): _samples_remove,
        ("batch", None): _batch,
        ("serve", None): _serve,
        ("review", "list"): _review_list,
        ("review", "stats"): _review_stats,
        ("eval", None): _evaluate,
    }
    handler = handlers.get((args.command, getattr(args, f"{args.command}_command", None)))
    if handler is None:
        return 0
    return handler(args)


def _db_init(args: argparse.Namespace) -> int:
    for path, init in (
        (config.catalog_db(), init_catalog),
        (config.library_db(), init_library),
    ):
        init(path)
        print(f"initialized {path}")
    return 0


def _db_check(args: argparse.Namespace) -> int:
    from tcg_scanner.db.check import check
    from tcg_scanner.recognition.embed import MODEL_NAME

    conn = _open_library_with_catalog()
    try:
        result = check(conn, config.data_dir(), MODEL_NAME)
    finally:
        conn.close()

    print(f"owned: {result.owned_total} rows, {len(result.unresolved_owned)} unresolved")
    print(f"matches: {result.matches_total} open, {len(result.unresolved_matches)} unresolved")
    print(
        f"images: {result.images_total} referenced, {len(result.missing_files)} missing, "
        f"{len(result.unreferenced_files)} unreferenced"
    )
    print(f"index: {result.unindexed_images} images missing vectors ({MODEL_NAME})")
    print(f"samples: {result.user_samples} confirmed user images")
    print(
        f"coverage: {result.jp_missing} printings without JP art, "
        f"{result.image_misses} recorded misses"
    )

    for label, ids in (
        ("unresolved owned", result.unresolved_owned),
        ("unresolved matches", result.unresolved_matches),
    ):
        if ids:
            print(f"{label}: {', '.join(str(value) for value in ids)}")
    for label, paths in (
        ("missing files", result.missing_files),
        ("unreferenced files", result.unreferenced_files),
    ):
        for path in paths:
            print(f"{label}: {path}")

    return 0 if result.ok else 1


def _catalog_sync(args: argparse.Namespace) -> int:
    init_catalog(config.catalog_db())
    conn = open_catalog(config.catalog_db())
    try:
        with Fetcher() as fetcher:
            common = {
                "language": args.lang,
                "skip_missing": args.skip_missing,
                "with_images": not args.no_images,
                "on_progress": _progress(f"{args.lang} images"),
            }
            if args.all:
                results = sync_all(conn, fetcher, config.data_dir(), **common)
            elif args.promos:
                results = sync_promos(conn, fetcher, config.data_dir(), **common)
            else:
                results = sync_sets(conn, args.set, fetcher, config.data_dir(), **common)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        conn.close()

    for result in results:
        fallbacks = f", {result.fallbacks} art fallbacks" if result.fallbacks else ""
        print(
            f"{result.set_code}: {result.cards} cards, {result.printings} printings, "
            f"{result.prices} price points, {result.images} images{fallbacks}"
        )
    if len(results) > 1:
        fallbacks = sum(result.fallbacks for result in results)
        suffix = f", {fallbacks} art fallbacks" if fallbacks else ""
        print(
            f"total: {sum(result.cards for result in results)} cards, "
            f"{sum(result.printings for result in results)} printings, "
            f"{sum(result.prices for result in results)} price points, "
            f"{sum(result.images for result in results)} images{suffix}"
        )
    return 0


def _require_recognition(*modules: str) -> None:
    import importlib.util

    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    if missing:
        raise SystemExit(
            f"missing optional dependencies: {', '.join(missing)}. Install them with "
            '`uv sync --extra recognition` or `uv tool install ".[recognition]"`.'
        )


def _progress(label: str):
    def report(done: int, total: int) -> None:
        if total and (done % 100 == 0 or done == total):
            print(f"{label}: {done}/{total}", file=sys.stderr)

    return report


def _prices_refresh(args: argparse.Namespace) -> int:
    from tcg_scanner.catalog.sync import refresh_prices

    init_catalog(config.catalog_db())
    conn = open_catalog(config.catalog_db())
    try:
        with Fetcher() as fetcher:
            result = refresh_prices(conn, fetcher, args.set)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"{result.sets} sets, {result.prices} new price points")
    if result.unknown:
        print(
            f"{result.unknown} printings are missing from the catalog; "
            "run `catalog sync` for their sets",
            file=sys.stderr,
        )
    return 0


def _index_build(args: argparse.Namespace) -> int:
    _require_recognition("timm")

    from tcg_scanner.recognition.embed import Embedder
    from tcg_scanner.recognition.index import build_index

    init_catalog(config.catalog_db())
    conn = open_catalog(config.catalog_db())
    try:
        embedder = Embedder()
        result = build_index(
            conn,
            config.data_dir(),
            embedder,
            embedder.model_name,
            batch_size=args.batch_size,
            limit=args.limit,
            on_progress=_progress("embedded"),
        )
    finally:
        conn.close()

    print(f"{result.embedded} images embedded, {result.missing} missing")
    return 0


def _inspect(args: argparse.Namespace) -> int:
    _require_recognition("easyocr")

    from tcg_scanner.imaging.rectify import rectify_file, write_image
    from tcg_scanner.recognition.ocr import CodeReader

    rectified = rectify_file(args.image)
    output = config.output_dir() / f"{args.image.stem}-rectified.jpg"
    write_image(output, rectified.image)
    reading = CodeReader().read(rectified.image)

    print(f"card edge: {'found' if rectified.found else 'not found'}")
    print(f"rectified: {output}")
    print(f"code: {reading.code or 'unreadable'}")
    return 0


def _identify(args: argparse.Namespace) -> int:
    _require_recognition("easyocr", "timm")

    import json

    from tcg_scanner.recognition.api import Recognizer, fuse
    from tcg_scanner.recognition.report import build_report

    init_catalog(config.catalog_db())
    conn = open_catalog(config.catalog_db())
    try:
        recognizer = Recognizer(conn, prefer=args.prefer, top_k=args.top)
        recognition = recognizer.recognize(args.image)
        fused = fuse([recognition], top_k=args.top)
        prices = _latest_prices(conn, fused.candidates[0]) if fused.candidates else _no_prices()
        index_size = len(recognizer.index)
    finally:
        conn.close()

    report = build_report(
        group=args.image.name,
        fused=fused,
        prices=prices,
        preferred_language=args.prefer,
    )

    if not args.text:
        print(json.dumps(report, indent=2))
        return 0

    print(f"card edge: {'found' if fused.representative.rectified.found else 'not found'}")
    print(f"code: {fused.ocr_code or 'unreadable'}")
    for position, candidate in enumerate(fused.candidates, start=1):
        patch = f"  patch {candidate.patch_score:.3f}" if candidate.patch_score is not None else ""
        print(
            f"{position:>2}. {candidate.score:.3f}{patch}  {candidate.card_code}  "
            f"{candidate.card_name}  ({candidate.set_code}, {candidate.variant_label})  "
            f"[{candidate.reference_language}]"
        )
    if not fused.candidates:
        print("no match")
        if index_size == 0:
            print("index is empty: run `tcg-scanner index build`")
    elif len(fused.candidates) > 1:
        print(f"margin: {fused.candidates[0].score - fused.candidates[1].score:.3f}")
    if report["warnings"]:
        print("warnings:")
        for warning in report["warnings"]:
            print(f"  {warning['code']}: {warning['message']}")
    return 0


def _samples_add(args: argparse.Namespace) -> int:
    from tcg_scanner.samples import add_sample

    init_catalog(config.catalog_db())
    conn = open_catalog(config.catalog_db())
    try:
        sample = add_sample(
            conn,
            config.data_dir(),
            image=args.image,
            card_code=args.card_code,
            print_index=args.print_index,
            language=args.language,
        )
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        conn.close()

    if not sample.rectified:
        print("warning: card edge not found; stored the image unrectified", file=sys.stderr)
    print(f"sample {sample.id}: {sample.path}")
    print("run `tcg-scanner index build` to include it")
    return 0


def _samples_list(args: argparse.Namespace) -> int:
    from tcg_scanner.samples import list_samples

    init_catalog(config.catalog_db())
    conn = open_catalog(config.catalog_db())
    try:
        rows = list_samples(conn, card_code=args.card_code)
    finally:
        conn.close()

    if not rows:
        print("no samples")
        return 0
    for row in rows:
        print(
            f"{row['id']:>4}  {row['card_code']} #{row['print_index']}  "
            f"{row['language']}  {row['path']}"
        )
    return 0


def _samples_remove(args: argparse.Namespace) -> int:
    from tcg_scanner.samples import remove_sample

    init_catalog(config.catalog_db())
    conn = open_catalog(config.catalog_db())
    try:
        path = remove_sample(conn, config.data_dir(), args.sample_id)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"removed sample {args.sample_id}: {path}")
    return 0


def _batch(args: argparse.Namespace) -> int:
    _require_recognition("easyocr", "timm")

    import json
    from datetime import UTC, datetime

    from tcg_scanner.batch import discover_groups, result_path
    from tcg_scanner.recognition.api import Recognizer, fuse
    from tcg_scanner.recognition.report import build_report

    input_dir = args.input or config.input_dir()
    groups = discover_groups(input_dir)
    if not groups:
        print(f"no images in {input_dir}")
        return 0

    output_dir = config.output_dir() / input_dir.resolve().name
    output_dir.mkdir(parents=True, exist_ok=True)
    init_catalog(config.catalog_db())

    matched = no_match = failed = 0
    created_at = datetime.now(UTC).isoformat(timespec="seconds")
    conn = open_catalog(config.catalog_db())
    try:
        recognizer = Recognizer(conn, prefer=args.prefer, top_k=args.top)
        for position, group in enumerate(groups, start=1):
            recognitions = []
            for image in group.images:
                try:
                    recognitions.append(recognizer.recognize(image))
                except (OSError, ValueError) as error:
                    failed += 1
                    print(f"  {image.name}: failed: {error}", file=sys.stderr)
            if not recognitions:
                continue

            fused = fuse(recognitions, top_k=args.top)
            top = fused.candidates[0] if fused.candidates else None
            prices = _latest_prices(conn, top) if top is not None else _no_prices()
            report = build_report(
                group=group.name,
                fused=fused,
                prices=prices,
                preferred_language=args.prefer,
            )
            path = result_path(output_dir, group.name)
            path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

            if top is None:
                no_match += 1
                summary = "no match"
            else:
                matched += 1
                summary = f"{top.card_code} #{top.print_index} {top.score:.3f} {top.card_name}"
            state = "excluded" if len(recognitions) == len(fused.excluded) else "used"
            print(
                f"[{position}/{len(groups)}] {group.name} "
                f"({len(recognitions)} photos, {state})  {summary}  -> {path.name}"
            )
            for warning in report["warnings"]:
                print(f"  warning: {warning['code']}: {warning['message']}", file=sys.stderr)
    finally:
        conn.close()

    (output_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": output_dir.name,
                "input": str(input_dir),
                "created_at": created_at,
                "photos": sum(len(group.images) for group in groups),
                "groups": len(groups),
                "model": recognizer.embedder.model_name,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"{matched} matched, {no_match} no match, {failed} failed photos; "
        f"run {output_dir.name} in {output_dir}"
    )
    return 0 if failed == 0 else 1


def _no_prices() -> dict[str, object]:
    return {"eur": None, "usd": None, "currency": None}


def _latest_prices(conn, candidate) -> dict[str, object]:
    rows = conn.execute(
        "SELECT source, currency, amount FROM latest_prices "
        "WHERE card_code = ? AND print_index = ?",
        (candidate.card_code, candidate.print_index),
    ).fetchall()
    by_source = {row["source"]: (row["amount"], row["currency"]) for row in rows}
    eur = by_source.get("cardmarket")
    usd = by_source.get("tcgplayer")
    currency = eur[1] if eur is not None else (usd[1] if usd is not None else None)
    return {
        "eur": eur[0] if eur is not None else None,
        "usd": usd[0] if usd is not None else None,
        "currency": currency,
    }


def _open_library_with_catalog():
    from tcg_scanner.db import attach_catalog, open_library

    init_catalog(config.catalog_db())
    init_library(config.library_db())
    conn = open_library(config.library_db())
    attach_catalog(conn, config.catalog_db())
    return conn


def _describe_printing(row) -> str:
    if row is None:
        return "unknown printing"
    return f"{row['card_code']} {row['card_name']} ({row['set_code']}, {row['variant_label']})"


def _matches_accept(args: argparse.Namespace) -> int:
    from tcg_scanner.db.library import accept_match, get_printing

    conn = _open_library_with_catalog()
    try:
        key = accept_match(
            conn,
            args.match_id,
            quantity=args.quantity,
            condition=args.condition,
            language=args.language,
        )
        printing = get_printing(conn, *key)
        conn.commit()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"accepted match {args.match_id}: {_describe_printing(printing)}")
    print(f"added {args.quantity} to the collection")
    return 0


def _matches_reject(args: argparse.Namespace) -> int:
    from tcg_scanner.db.library import reject_match

    conn = _open_library_with_catalog()
    try:
        reject_match(conn, args.match_id)
        conn.commit()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"rejected match {args.match_id}")
    return 0


def _owned_add(args: argparse.Namespace) -> int:
    from tcg_scanner.db.library import add_owned, get_printing

    conn = _open_library_with_catalog()
    try:
        owned_id = add_owned(
            conn,
            card_code=args.card_code,
            print_index=args.print_index,
            quantity=args.quantity,
            condition=args.condition,
            language=args.language,
            paid_price=args.paid_price,
            currency=args.currency,
            note=args.note,
        )
        printing = get_printing(conn, args.card_code, args.print_index)
        conn.commit()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"owned {owned_id}: {_describe_printing(printing)} x{args.quantity}")
    return 0


def _matches_list(args: argparse.Namespace) -> int:
    from tcg_scanner.db.library import list_matches

    conn = _open_library_with_catalog()
    try:
        rows = list_matches(conn, status=args.status)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        conn.close()

    if not rows:
        print(f"no {args.status} matches")
        return 0

    for row in rows:
        if row["card_code"] is None:
            card = "no match"
            stale = ""
        else:
            card = (
                f"{row['card_code']} #{row['print_index']} {row['card_name']} "
                f"({row['set_code']}, {row['variant_label']})"
            )
            stale = "" if row["resolved"] else "  [stale snapshot]"
        confidence = "-" if row["confidence"] is None else f"{row['confidence']:.3f}"
        print(
            f"{row['id']:>4}  {row['status']:<8}  {confidence:>5}  {card}{stale}  "
            f"{row['created_at']}"
        )
    return 0


def _owned_update(args: argparse.Namespace) -> int:
    from tcg_scanner.db.library import update_owned

    conn = _open_library_with_catalog()
    try:
        update_owned(
            conn,
            args.owned_id,
            quantity=args.quantity,
            condition=args.condition,
            language=args.language,
            paid_price=args.paid_price,
            currency=args.currency,
            note=args.note,
        )
        conn.commit()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"updated owned {args.owned_id}")
    return 0


def _owned_remove(args: argparse.Namespace) -> int:
    from tcg_scanner.db.library import remove_owned

    conn = _open_library_with_catalog()
    try:
        remove_owned(conn, args.owned_id)
        conn.commit()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"removed owned {args.owned_id}")
    return 0


def _owned_list(args: argparse.Namespace) -> int:
    from tcg_scanner.db.library import collection_total, list_owned

    conn = _open_library_with_catalog()
    try:
        rows = list_owned(conn, source=args.source)
    finally:
        conn.close()

    if not rows:
        print("collection is empty")
        return 0

    for position, row in enumerate(rows, start=1):
        price = "-" if row["price"] is None else f"{row['price']:.2f} {row['currency']}"
        print(
            f"{position:>2}. {row['card_code']} #{row['print_index']}  "
            f"{row['card_name'] or '?'}  "
            f"({row['set_code'] or '?'}, {row['variant_label'] or '?'})  "
            f"x{row['quantity']}  {price}"
        )

    total, unpriced = collection_total(rows)
    currency = next((row["currency"] for row in rows if row["currency"]), "")
    suffix = f" ({unpriced} rows without price)" if unpriced else ""
    print(f"total: {total:.2f} {currency}{suffix}".rstrip())
    return 0


def _review_connection():
    from tcg_scanner.db import open_library

    init_library(config.library_db())
    return open_library(config.library_db())


def _review_list(args: argparse.Namespace) -> int:
    from tcg_scanner.db.library import list_reviews

    conn = _review_connection()
    try:
        rows = list_reviews(conn, run=args.run)
    finally:
        conn.close()

    if not rows:
        print("no reviews")
        return 0
    for row in rows:
        expansion = f" → {row['expansion']}" if row["expansion"] else ""
        note = f"  {row['note']}" if row["note"] else ""
        print(
            f"{row['run']}/{row['result_group']}  {row['status']}{expansion}  "
            f"{row['updated_at']}{note}"
        )
    return 0


def _review_stats(args: argparse.Namespace) -> int:
    from tcg_scanner.db.library import review_stats

    conn = _review_connection()
    try:
        stats = review_stats(conn, run=args.run)
    finally:
        conn.close()

    reviewed = stats["reviewed"]
    accuracy = "n/a" if stats["accuracy"] is None else f"{stats['accuracy']:.1%}"
    print(
        f"reviewed {reviewed}: right {stats['right']}, wrong {stats['wrong']}, accuracy {accuracy}"
    )
    if stats["by_expansion"]:
        print("by predicted expansion:")
        for expansion, counts in stats["by_expansion"].items():
            total = counts["right"] + counts["wrong"]
            print(f"  {expansion}: {counts['right']}/{total}")
    if stats["claimed_expansion"]:
        print("claimed expansions (wrong):")
        for expansion, count in stats["claimed_expansion"].items():
            print(f"  {expansion}: {count}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn

        from tcg_scanner.web.app import create_app
    except ImportError:
        print("the web extra is missing: run `uv sync --extra web`", file=sys.stderr)
        return 1

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    _require_recognition("easyocr", "timm")

    import json

    from tcg_scanner.eval.run import evaluate, load_labels, score_summary
    from tcg_scanner.recognition.api import Recognizer

    labels_path = args.labels or (config.data_dir() / "eval" / "labels.csv")
    try:
        labels = load_labels(labels_path)
    except (OSError, ValueError) as error:
        print(f"{labels_path}: {error}", file=sys.stderr)
        return 1

    init_catalog(config.catalog_db())
    conn = open_catalog(config.catalog_db())
    try:
        recognizer = Recognizer(conn, prefer="jp", top_k=args.top)

        def predict(image):
            recognition = recognizer.recognize(image)
            return recognition.reading.code, recognition.candidates

        report = evaluate(labels, predict, top_k=args.top)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(_report_dict(report), indent=2))
        return 0

    print(f"labeled: {report.total} scored, {report.missing} missing")
    print(f"card top-1:    {report.card_accuracy:.1%}  ({report.card_top1}/{report.total})")
    print(f"print top-1:   {report.print_accuracy:.1%}  ({report.print_top1}/{report.print_total})")
    print(
        f"print top-{args.top}:   {report.print_recall:.1%}  "
        f"({report.print_top5}/{report.print_total})"
    )
    print(f"OCR readable:  {report.ocr_readable_rate:.1%}  ({report.ocr_readable}/{report.total})")
    print(
        f"OCR correct:   {report.ocr_accuracy:.1%}  "
        f"({report.ocr_correct}/{report.ocr_readable} readable)"
    )
    print(
        f"score top-1:   correct {score_summary(report.correct_scores)} | "
        f"wrong {score_summary(report.wrong_scores)}"
    )
    if report.misses:
        print("misses:")
        for miss in report.misses:
            print(f"  {miss.image}  expected {miss.expected}  got {miss.predicted}")
    else:
        print("misses: none")
    return 0


def _report_dict(report: Report) -> dict:
    return {
        "total": report.total,
        "missing": report.missing,
        "card_top1": {"count": report.card_top1, "rate": report.card_accuracy},
        "print_top1": {"count": report.print_top1, "rate": report.print_accuracy},
        "print_top5": {"count": report.print_top5, "rate": report.print_recall},
        "ocr_readable": {"count": report.ocr_readable, "rate": report.ocr_readable_rate},
        "ocr_correct": {"count": report.ocr_correct, "rate": report.ocr_accuracy},
        "scores": {
            "correct": list(report.correct_scores),
            "wrong": list(report.wrong_scores),
        },
        "misses": [
            {"image": miss.image, "expected": miss.expected, "predicted": miss.predicted}
            for miss in report.misses
        ],
    }
