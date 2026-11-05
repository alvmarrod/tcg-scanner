from __future__ import annotations

import argparse
from collections.abc import Sequence

from tcg_scanner import config
from tcg_scanner.db import init_catalog, init_library


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tcg-scanner",
        description="Identify One Piece TCG cards and track an owned collection.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    db = commands.add_parser("db", help="manage the local databases")
    db_commands = db.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser("init", help="create the catalog and library databases")

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
