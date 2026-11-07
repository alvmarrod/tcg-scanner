from pathlib import Path

import pytest

from tcg_scanner.catalog.sync import refresh_prices, sync_set
from tcg_scanner.db import init_catalog, open_catalog

FIXTURES = Path(__file__).parent / "fixtures"
SET_PAGE = "/cards/op08-two-legends?display=full"


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
        SET_PAGE: (FIXTURES / "op08_cards.html").read_text(),
    }


def _seeded(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    sync_set(conn, "OP08", FakeFetcher(_pages()), tmp_path, now="2026-01-01T00:00:00Z")
    return conn


def test_refresh_appends_only_changed_prices(tmp_path):
    conn = _seeded(tmp_path)
    try:
        pages = _pages()
        pages[SET_PAGE] = pages[SET_PAGE].replace("$0.20", "$0.30")

        result = refresh_prices(conn, FakeFetcher(pages), ["OP08"], now="2026-01-02T00:00:00Z")

        assert result.sets == 1
        assert result.prices == 1
        assert result.unknown == 0
        latest = conn.execute(
            "SELECT amount FROM latest_prices WHERE card_code = 'OP08-001' "
            "AND print_index = 0 AND source = 'tcgplayer'"
        ).fetchone()[0]
        assert latest == 0.30
    finally:
        conn.close()


def test_refresh_defaults_to_every_synced_set(tmp_path):
    conn = _seeded(tmp_path)
    try:
        result = refresh_prices(conn, FakeFetcher(_pages()), now="2026-01-02T00:00:00Z")

        assert result.sets == 1
        assert result.prices == 0
    finally:
        conn.close()


def test_refresh_never_creates_printings(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        result = refresh_prices(conn, FakeFetcher(_pages()), ["OP08"])

        assert result.prices == 0
        assert result.unknown == 4
        assert conn.execute("SELECT COUNT(*) FROM printings").fetchone()[0] == 0
    finally:
        conn.close()


def test_refresh_rejects_an_unknown_set(tmp_path):
    conn = _seeded(tmp_path)
    try:
        with pytest.raises(ValueError, match="NOPE"):
            refresh_prices(conn, FakeFetcher(_pages()), ["NOPE"])
    finally:
        conn.close()
