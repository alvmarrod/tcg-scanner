from pathlib import Path

from tcg_scanner.catalog.sync import sync_set
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
            "SELECT source, currency, amount FROM latest_prices WHERE printing_id = ?",
            (base["id"],),
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
