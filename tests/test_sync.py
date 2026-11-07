from pathlib import Path

import httpx

from tcg_scanner.catalog.sync import (
    sync_all,
    sync_promos,
    sync_set,
    sync_sets,
)
from tcg_scanner.db import init_catalog, open_catalog

FIXTURES = Path(__file__).parent / "fixtures"


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def text(self, path: str) -> str:
        return self.pages[path]

    def content(self, url: str) -> bytes:
        return url.encode()


def _pages() -> dict[str, str]:
    return {
        "/cards": (FIXTURES / "op08_index.html").read_text(),
        "/cards/op08-two-legends?display=full": (FIXTURES / "op08_cards.html").read_text(),
    }


def _sync(conn, data_root: Path, now: str):
    return sync_set(conn, "op08", FakeFetcher(_pages()), data_root, now=now)


def test_sync_populates_sets_cards_printings_prices_and_images(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        result = _sync(conn, tmp_path, "2026-01-01T00:00:00Z")

        assert result.set_code == "OP08"
        assert result.cards == 2
        assert result.printings == 4
        assert result.prices == 8
        assert result.images == 4

        sets = {row["code"] for row in conn.execute("SELECT code FROM sets")}
        assert {"OP08", "EB05", "OP01", "ST36"} <= sets
        assert "X-ANIME-25TH-COLLECTION" in sets

        cards = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        printings = conn.execute("SELECT COUNT(*) FROM printings").fetchone()[0]
        assert cards == 2
        assert printings == 4

        base = conn.execute(
            "SELECT * FROM printings WHERE card_code = 'OP08-001' AND variant_label = 'base' "
            "AND set_code = 'OP08'"
        ).fetchone()
        assert base["tcgplayer_id"] == "558021"

        latest = conn.execute(
            "SELECT source, currency, amount FROM latest_prices "
            "WHERE card_code = ? AND print_index = ?",
            (base["card_code"], base["print_index"]),
        ).fetchall()
        assert {(row["source"], row["currency"], row["amount"]) for row in latest} == {
            ("tcgplayer", "USD", 0.20),
            ("cardmarket", "EUR", 0.10),
        }

        images = conn.execute("SELECT path FROM card_images").fetchall()
        assert len(images) == 4
        for row in images:
            assert (tmp_path / row["path"]).is_file()
    finally:
        conn.close()


def test_second_sync_adds_no_prices_or_images(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        _sync(conn, tmp_path, "2026-01-01T00:00:00Z")
        again = _sync(conn, tmp_path, "2026-01-02T00:00:00Z")

        assert again.cards == 2
        assert again.prices == 0
        assert again.images == 0
        assert conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0] == 8
    finally:
        conn.close()


def test_unknown_set_code_raises(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        try:
            sync_set(conn, "NOPE", FakeFetcher(_pages()), tmp_path)
        except ValueError as error:
            assert "NOPE" in str(error)
        else:
            raise AssertionError("expected ValueError")
    finally:
        conn.close()


def test_sync_sets_deduplicates_codes(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        results = sync_sets(
            conn, ["OP08", "op08"], FakeFetcher(_pages()), tmp_path, now="2026-01-01T00:00:00Z"
        )
        assert [result.set_code for result in results] == ["OP08"]
    finally:
        conn.close()


def test_sync_all_covers_every_booster_and_starter(tmp_path):
    class AnyPageFetcher(FakeFetcher):
        def text(self, path: str) -> str:
            if path == "/cards":
                return self.pages["/cards"]
            return self.pages["/cards/op08-two-legends?display=full"]

    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        results = sync_all(conn, AnyPageFetcher(_pages()), tmp_path, now="2026-01-01T00:00:00Z")

        assert {result.set_code for result in results} == {"EB05", "OP08", "OP01", "ST36"}
        assert sum(result.images for result in results) == 4
    finally:
        conn.close()


class FailingJapaneseFetcher(FakeFetcher):
    def __init__(self, pages: dict[str, str]) -> None:
        super().__init__(pages)
        self.downloads = 0

    def content(self, url: str) -> bytes:
        self.downloads += 1
        if "_JP.webp" in url:
            request = httpx.Request("GET", url)
            response = httpx.Response(403, request=request)
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)
        return url.encode()


def test_missing_japanese_art_stores_english_and_records_a_miss(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        fetcher = FailingJapaneseFetcher(_pages())

        result = sync_set(conn, "OP08", fetcher, tmp_path, now="2026-01-01T00:00:00Z")

        assert result.images == 4
        assert result.fallbacks == 4
        languages = {row[0] for row in conn.execute("SELECT DISTINCT language FROM card_images")}
        assert languages == {"en"}
        misses = conn.execute("SELECT language FROM image_misses").fetchall()
        assert [row[0] for row in misses] == ["jp"] * 4
    finally:
        conn.close()


def test_refresh_retries_missing_art_by_default(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        sync_set(
            conn, "OP08", FailingJapaneseFetcher(_pages()), tmp_path, now="2026-01-01T00:00:00Z"
        )
        second = FailingJapaneseFetcher(_pages())

        sync_set(conn, "OP08", second, tmp_path, now="2026-01-02T00:00:00Z")

        assert second.downloads == 4  # the four JP misses were retried
    finally:
        conn.close()


def test_skip_missing_does_not_retry(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        sync_set(
            conn, "OP08", FailingJapaneseFetcher(_pages()), tmp_path, now="2026-01-01T00:00:00Z"
        )
        second = FailingJapaneseFetcher(_pages())

        sync_set(
            conn,
            "OP08",
            second,
            tmp_path,
            skip_missing=True,
            now="2026-01-02T00:00:00Z",
        )

        assert second.downloads == 0
    finally:
        conn.close()


def test_sync_defaults_to_japanese_images(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        sync_set(conn, "OP08", FakeFetcher(_pages()), tmp_path, now="2026-01-01T00:00:00Z")

        languages = {row[0] for row in conn.execute("SELECT DISTINCT language FROM card_images")}
        assert languages == {"jp"}
        urls = [row[0] for row in conn.execute("SELECT image_url FROM printings")]
        assert urls and all("_JP.webp" in url for url in urls)
    finally:
        conn.close()


def test_sync_english_mode_stores_english_images(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        sync_set(
            conn,
            "OP08",
            FakeFetcher(_pages()),
            tmp_path,
            language="en",
            now="2026-01-01T00:00:00Z",
        )

        languages = {row[0] for row in conn.execute("SELECT DISTINCT language FROM card_images")}
        assert languages == {"en"}
        urls = [row[0] for row in conn.execute("SELECT image_url FROM printings")]
        assert urls and all("_EN.webp" in url for url in urls)
    finally:
        conn.close()


def test_second_language_keeps_the_printing_identity(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        sync_set(
            conn,
            "OP08",
            FakeFetcher(_pages()),
            tmp_path,
            language="en",
            now="2026-01-01T00:00:00Z",
        )
        english_urls = {
            (row[0], row[1]): row[2]
            for row in conn.execute("SELECT card_code, print_index, image_url FROM printings")
        }

        sync_set(conn, "OP08", FakeFetcher(_pages()), tmp_path, now="2026-01-02T00:00:00Z")

        japanese_urls = {
            (row[0], row[1]): row[2]
            for row in conn.execute("SELECT card_code, print_index, image_url FROM printings")
        }
        assert japanese_urls == english_urls
        assert conn.execute("SELECT COUNT(*) FROM card_images").fetchone()[0] == 8
        languages = {row[0] for row in conn.execute("SELECT DISTINCT language FROM card_images")}
        assert languages == {"en", "jp"}
    finally:
        conn.close()


def test_sync_promos_keeps_base_and_promo_prints_distinct(tmp_path):
    def pages() -> dict[str, str]:
        return {
            "/cards": (FIXTURES / "op08_index.html").read_text(),
            "/cards/promos": (FIXTURES / "promos_index.html").read_text(),
            "/cards/tournament-pack-16?display=full": (
                FIXTURES / "promo_products.html"
            ).read_text(),
        }

    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        results = sync_promos(conn, FakeFetcher(pages()), tmp_path, now="2026-01-01T00:00:00Z")

        assert [result.set_code for result in results] == ["X-TOURNAMENT-PACK-2026-VOL-4"]
        urls = {
            (row[0], row[1]): row[2]
            for row in conn.execute("SELECT card_code, print_index, image_url FROM printings")
        }
        assert urls[("OP09-099", 0)].endswith("OP09-099_JP.webp")
        assert urls[("OP09-099", 1)].endswith("OP09-099_p1_JP.webp")
        assert urls[("OP09-099", 2)].endswith("OP09-099_p2_JP.webp")
    finally:
        conn.close()
