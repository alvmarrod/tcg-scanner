from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from tcg_scanner import config
from tcg_scanner.catalog import Fetcher, sync_set
from tcg_scanner.db import init_catalog, init_library, open_catalog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tcg-scanner",
        description="Identify One Piece TCG cards and track an owned collection.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    db = commands.add_parser("db", help="manage the local databases")
    db_commands = db.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser("init", help="create the catalog and library databases")

    catalog = commands.add_parser("catalog", help="sync card reference data")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    sync = catalog_commands.add_parser("sync", help="sync one set from the card database")
    sync.add_argument("--set", required=True, metavar="CODE", help="set code, e.g. OP08")
    sync.add_argument("--no-images", action="store_true", help="skip downloading card images")

    index = commands.add_parser("index", help="build the recognition index")
    index_commands = index.add_subparsers(dest="index_command", required=True)
    build = index_commands.add_parser("build", help="embed reference images with DINOv2")
    build.add_argument("--batch-size", type=int, default=8, metavar="N")
    build.add_argument("--limit", type=int, default=None, metavar="N")

    inspect = commands.add_parser("inspect", help="rectify an image and read its card code")
    inspect.add_argument("image", type=Path, metavar="IMAGE")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "db" and args.db_command == "init":
        for path, init in (
            (config.catalog_db(), init_catalog),
            (config.library_db(), init_library),
        ):
            init(path)
            print(f"initialized {path}")
        return 0

    if args.command == "catalog" and args.catalog_command == "sync":
        init_catalog(config.catalog_db())
        conn = open_catalog(config.catalog_db())
        try:
            with Fetcher() as fetcher:
                result = sync_set(
                    conn,
                    args.set,
                    fetcher,
                    config.data_dir(),
                    with_images=not args.no_images,
                )
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        finally:
            conn.close()

        print(
            f"{result.set_code}: {result.cards} cards, {result.printings} printings, "
            f"{result.prices} price points, {result.images} images"
        )
        return 0

    if args.command == "index" and args.index_command == "build":
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
            )
        finally:
            conn.close()

        print(f"{result.embedded} images embedded, {result.missing} missing")
        return 0

    if args.command == "inspect":
        from tcg_scanner.imaging.rectify import rectify_file, write_image
        from tcg_scanner.recognition.ocr import CodeReader

        rectified = rectify_file(args.image)
        output = config.output_dir() / f"{args.image.stem}-rectified.jpg"
        write_image(output, rectified.image)
        code = CodeReader().read(rectified.image)

        print(f"card edge: {'found' if rectified.found else 'not found'}")
        print(f"rectified: {output}")
        print(f"code: {code or 'unreadable'}")
        return 0

    return 0
