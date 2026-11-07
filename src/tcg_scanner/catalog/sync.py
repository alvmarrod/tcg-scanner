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
    ParsedSet,
    base_image_url,
    parse_cards,
    parse_index,
    variant_image_url,
)
from tcg_scanner.db import catalog
from tcg_scanner.images import store_image

Progress = Callable[[int, int], None]
PrintingKey = tuple[str, int]


@dataclass(frozen=True)
class SyncResult:
    set_code: str
    cards: int
    printings: int
    prices: int
    images: int


@dataclass(frozen=True)
class PriceRefresh:
    sets: int
    prices: int
    unknown: int


@dataclass
class _Counts:
    cards: int = 0
    printings: int = 0
    prices: int = 0
    images: int = 0


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
    return sync_sets(
        conn,
        [set_code],
        fetcher,
        data_root,
        with_images=with_images,
        now=now,
        workers=workers,
        on_progress=on_progress,
    )[0]


def sync_sets(
    conn: sqlite3.Connection,
    set_codes: list[str],
    fetcher: Fetcher,
    data_root: Path,
    *,
    with_images: bool = True,
    now: str | None = None,
    workers: int = 4,
    on_progress: Progress | None = None,
) -> list[SyncResult]:
    entries = parse_index(fetcher.text("/cards"))
    known = {entry.code: entry for entry in entries}
    targets: list[ParsedSet] = []
    seen: set[str] = set()
    for code in set_codes:
        entry = known.get(code.upper())
        if entry is None:
            raise ValueError(f"unknown set code: {code}")
        if entry.code not in seen:
            seen.add(entry.code)
            targets.append(entry)
    return _sync_entries(
        conn,
        targets,
        entries,
        fetcher,
        data_root,
        with_images=with_images,
        now=now,
        workers=workers,
        on_progress=on_progress,
    )


def sync_all(
    conn: sqlite3.Connection,
    fetcher: Fetcher,
    data_root: Path,
    *,
    with_images: bool = True,
    now: str | None = None,
    workers: int = 4,
    on_progress: Progress | None = None,
) -> list[SyncResult]:
    entries = parse_index(fetcher.text("/cards"))
    targets = [entry for entry in entries if entry.kind in ("booster", "starter")]
    return _sync_entries(
        conn,
        targets,
        entries,
        fetcher,
        data_root,
        with_images=with_images,
        now=now,
        workers=workers,
        on_progress=on_progress,
    )


def _sync_entries(
    conn: sqlite3.Connection,
    targets: list[ParsedSet],
    entries: list[ParsedSet],
    fetcher: Fetcher,
    data_root: Path,
    *,
    with_images: bool,
    now: str | None,
    workers: int,
    on_progress: Progress | None,
) -> list[SyncResult]:
    for entry in entries:
        catalog.upsert_set(
            conn,
            code=entry.code,
            name=entry.name,
            kind=entry.kind,
            release_date=entry.release_date,
        )

    by_name = {entry.name: entry.code for entry in entries}
    known_codes = set(by_name.values())
    fetched_at = now or datetime.now(UTC).isoformat(timespec="seconds")
    counts = {entry.code: _Counts() for entry in targets}
    jobs: dict[PrintingKey, str] = {}
    owners: dict[PrintingKey, str] = {}

    for entry in targets:
        cards = parse_cards(fetcher.text(f"/cards/{entry.slug}?display=full"))
        counts[entry.code].cards = len(cards)

        for card in cards:
            card_set = card.code.split("-")[0]
            if card_set not in known_codes:
                card_set = entry.code
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
                counts[entry.code].printings += 1

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
                        counts[entry.code].prices += 1

                if (
                    with_images
                    and printing_key not in jobs
                    and not catalog.has_reference_image(conn, *printing_key)
                ):
                    jobs[printing_key] = image_url
                    owners[printing_key] = entry.code

    conn.commit()
    for key in _download_images(
        conn,
        fetcher,
        data_root,
        list(jobs.items()),
        workers=workers,
        on_progress=on_progress,
    ):
        counts[owners[key]].images += 1
    conn.commit()

    return [
        SyncResult(
            set_code=entry.code,
            cards=counts[entry.code].cards,
            printings=counts[entry.code].printings,
            prices=counts[entry.code].prices,
            images=counts[entry.code].images,
        )
        for entry in targets
    ]


def refresh_prices(
    conn: sqlite3.Connection,
    fetcher: Fetcher,
    set_codes: list[str] | None = None,
    *,
    now: str | None = None,
) -> PriceRefresh:
    """Append changed prices for already-synced sets; never creates printings."""
    index = {entry.code: entry for entry in parse_index(fetcher.text("/cards"))}
    if set_codes:
        targets = [code.upper() for code in set_codes]
        for code in targets:
            if code not in index:
                raise ValueError(f"unknown set code: {code}")
    else:
        targets = [
            row[0] for row in conn.execute("SELECT DISTINCT set_code FROM cards ORDER BY set_code")
        ]

    fetched_at = now or datetime.now(UTC).isoformat(timespec="seconds")
    known = {
        (row[0], row[1]) for row in conn.execute("SELECT card_code, print_index FROM printings")
    }
    prices = 0
    unknown: set[PrintingKey] = set()

    for code in targets:
        entry = index.get(code)
        if entry is None:
            continue
        cards = parse_cards(fetcher.text(f"/cards/{entry.slug}?display=full"))
        for card in cards:
            for printing in card.printings:
                key = (card.code, printing.print_index)
                if key not in known:
                    unknown.add(key)
                    continue
                for source, currency, amount in (
                    ("tcgplayer", "USD", printing.usd),
                    ("cardmarket", "EUR", printing.eur),
                ):
                    if amount is not None and catalog.add_price(
                        conn,
                        card_code=key[0],
                        print_index=key[1],
                        source=source,
                        currency=currency,
                        amount=amount,
                        fetched_at=fetched_at,
                    ):
                        prices += 1

    conn.commit()
    return PriceRefresh(sets=len(targets), prices=prices, unknown=len(unknown))


def _set_for_name(conn: sqlite3.Connection, name: str, by_name: dict[str, str]) -> str:
    code = by_name.get(name)
    if code:
        return code

    # Reprinted in a product outside the sets index (promo/collection sets).
    # A synthetic code keeps the foreign key and the printing key honest.
    code = "X-" + re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:60]
    catalog.upsert_set(conn, code=code, name=name, kind="promo", release_date=None)
    return code


def _fetch_image(fetcher: Fetcher, url: str) -> tuple[bytes, str]:
    """Fetch a reference image, falling back to its Japanese print.

    Some reprinted arts exist only in Japanese; the English URL 403s for them.
    """
    try:
        return fetcher.content(url), url
    except httpx.HTTPStatusError:
        if "_EN." not in url:
            raise
        fallback = url.replace("_EN.", "_JP.")
        return fetcher.content(fallback), fallback


def _download_images(
    conn: sqlite3.Connection,
    fetcher: Fetcher,
    data_root: Path,
    jobs: list[tuple[PrintingKey, str]],
    *,
    workers: int,
    on_progress: Progress | None,
) -> list[PrintingKey]:
    if not jobs:
        return []

    downloaded: list[PrintingKey] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_fetch_image, fetcher, url): (key, url) for key, url in jobs}
        for future in as_completed(futures):
            printing_key, url = futures[future]
            try:
                data, actual_url = future.result()
            except httpx.HTTPStatusError as error:
                print(f"warning: {url}: HTTP {error.response.status_code}", file=sys.stderr)
                continue
            except httpx.HTTPError as error:
                print(f"warning: {url}: {type(error).__name__}", file=sys.stderr)
                continue

            if actual_url != url:
                catalog.set_printing_image_url(
                    conn,
                    card_code=printing_key[0],
                    print_index=printing_key[1],
                    image_url=actual_url,
                )
            path, digest = store_image(
                data, data_root, Path(urlsplit(actual_url).path).suffix or ".webp"
            )
            catalog.add_card_image(
                conn,
                card_code=printing_key[0],
                print_index=printing_key[1],
                path=path.relative_to(data_root).as_posix(),
                sha256=digest,
            )
            downloaded.append(printing_key)
            if on_progress is not None:
                on_progress(len(downloaded), len(jobs))
    return downloaded
