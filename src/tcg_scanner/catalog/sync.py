from __future__ import annotations

import re
import sqlite3
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from tcg_scanner.catalog.fetch import Fetcher
from tcg_scanner.catalog.parse import (
    base_image_url,
    parse_cards,
    parse_index,
    variant_image_url,
)
from tcg_scanner.db import catalog
from tcg_scanner.images import store_image

Progress = Callable[[int, int], None]


@dataclass(frozen=True)
class SyncResult:
    set_code: str
    cards: int
    printings: int
    prices: int
    images: int


def sync_set(
    conn: sqlite3.Connection,
    set_code: str,
    fetcher: Fetcher,
    data_root: Path,
    *,
    with_images: bool = True,
    now: str | None = None,
    workers: int = 4,
    on_progress: Progress | None = None,
) -> SyncResult:
    set_code = set_code.upper()
    known = {entry.code: entry for entry in parse_index(fetcher.text("/cards"))}
    target = known.get(set_code)
    if target is None:
        raise ValueError(f"unknown set code: {set_code}")

    for entry in known.values():
        catalog.upsert_set(
            conn,
            code=entry.code,
            name=entry.name,
            kind=entry.kind,
            release_date=entry.release_date,
        )

    by_name = {entry.name: entry.code for entry in known.values()}
    cards = parse_cards(fetcher.text(f"/cards/{target.slug}?display=full"))
    fetched_at = now or datetime.now(UTC).isoformat(timespec="seconds")
    printings = prices = images = 0
    image_jobs: list[tuple[tuple[str, int], str]] = []

    for card in cards:
        card_set = card.code.split("-")[0]
        if card_set not in known:
            card_set = set_code
        catalog.upsert_card(conn, card, card_set)

        base_image = base_image_url(card.image_url)
        for printing in card.printings:
            printing_set = _set_for_name(conn, printing.set_name, by_name)
            image_url = (
                card.image_url
                if printing.current
                else variant_image_url(base_image, printing.print_index)
            )
            printing_key = catalog.upsert_printing(
                conn,
                card_code=card.code,
                set_code=printing_set,
                variant_label=printing.variant_label,
                print_index=printing.print_index,
                image_url=image_url,
                tcgplayer_id=printing.tcgplayer_id,
                cardmarket_id=printing.cardmarket_id,
            )
            printings += 1

            for source, currency, amount in (
                ("tcgplayer", "USD", printing.usd),
                ("cardmarket", "EUR", printing.eur),
            ):
                if amount is not None and catalog.add_price(
                    conn,
                    card_code=printing_key[0],
                    print_index=printing_key[1],
                    source=source,
                    currency=currency,
                    amount=amount,
                    fetched_at=fetched_at,
                ):
                    prices += 1

            if with_images and not catalog.has_reference_image(conn, *printing_key):
                image_jobs.append((printing_key, image_url))

    conn.commit()
    images = _download_images(
        conn,
        fetcher,
        data_root,
        image_jobs,
        workers=workers,
        on_progress=on_progress,
    )
    conn.commit()
    return SyncResult(
        set_code=set_code,
        cards=len(cards),
        printings=printings,
        prices=prices,
        images=images,
    )


def _set_for_name(conn: sqlite3.Connection, name: str, by_name: dict[str, str]) -> str:
    code = by_name.get(name)
    if code:
        return code

    # Reprinted in a product outside the sets index (promo/collection sets).
    # A synthetic code keeps the foreign key and the printing key honest.
    code = "X-" + re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:60]
    catalog.upsert_set(conn, code=code, name=name, kind="promo", release_date=None)
    return code


def _download_images(
    conn: sqlite3.Connection,
    fetcher: Fetcher,
    data_root: Path,
    jobs: list[tuple[tuple[str, int], str]],
    *,
    workers: int,
    on_progress: Progress | None,
) -> int:
    if not jobs:
        return 0

    downloaded = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetcher.content, url): (key, url) for key, url in jobs}
        for future in as_completed(futures):
            printing_key, url = futures[future]
            try:
                data = future.result()
            except httpx.HTTPStatusError as error:
                print(f"warning: {url}: HTTP {error.response.status_code}", file=sys.stderr)
                continue
            except httpx.HTTPError as error:
                print(f"warning: {url}: {type(error).__name__}", file=sys.stderr)
                continue

            path, digest = store_image(data, data_root, Path(urlsplit(url).path).suffix or ".webp")
            catalog.add_card_image(
                conn,
                card_code=printing_key[0],
                print_index=printing_key[1],
                path=path.relative_to(data_root).as_posix(),
                sha256=digest,
            )
            downloaded += 1
            if on_progress is not None:
                on_progress(downloaded, len(jobs))
    return downloaded
