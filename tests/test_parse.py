from pathlib import Path

from tcg_scanner.catalog.parse import (
    base_image_url,
    language_image_url,
    parse_cards,
    parse_index,
    parse_promos,
    variant_image_url,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_index_reads_codes_kinds_and_dates():
    sets = {entry.code: entry for entry in parse_index((FIXTURES / "op08_index.html").read_text())}

    op08 = sets["OP08"]
    assert op08.name == "Two Legends"
    assert op08.kind == "booster"
    assert op08.release_date == "2024-09-13"
    assert op08.slug == "op08-two-legends"
    assert sets["ST36"].kind == "starter"


def test_parse_cards_reads_leader_and_character_fields():
    cards = {card.code: card for card in parse_cards((FIXTURES / "op08_cards.html").read_text())}

    leader = cards["OP08-001"]
    assert leader.name == "Tony Tony.Chopper"
    assert leader.category == "Leader"
    assert leader.color == "Red/Green"
    assert leader.life == 4
    assert leader.power == 5000
    assert leader.cost is None
    assert leader.attribute == "Strike"
    assert leader.traits == "Animal/Drum Kingdom/Straw Hat Crew"
    assert leader.effect

    character = cards["OP08-003"]
    assert character.category == "Character"
    assert character.cost == 2
    assert character.power == 2000
    assert character.counter == 1000


def test_parse_cards_reads_printings_and_prices():
    cards = {card.code: card for card in parse_cards((FIXTURES / "op08_cards.html").read_text())}

    printings = cards["OP08-001"].printings
    assert [printing.variant_label for printing in printings] == ["base", "aa", "base"]
    assert [printing.print_index for printing in printings] == [0, 1, 2]
    assert [printing.current for printing in printings] == [True, False, False]
    assert printings[0].set_name == "Two Legends"
    assert printings[0].usd == 0.20
    assert printings[0].eur == 0.10
    assert printings[0].tcgplayer_id == "558021"
    assert printings[2].set_name == "Anime 25th Collection"


def test_variant_image_url_inserts_the_print_suffix():
    base = "https://cdn.example/one-piece/OP08/OP08-001_EN.webp"
    assert variant_image_url(base, 2) == "https://cdn.example/one-piece/OP08/OP08-001_p2_EN.webp"
    assert variant_image_url(base, 0) == base


def test_base_image_url_strips_an_existing_print_suffix():
    url = "https://cdn.example/one-piece/OP07/OP07-109_p3_EN.webp"
    assert base_image_url(url) == "https://cdn.example/one-piece/OP07/OP07-109_EN.webp"
    plain = "https://cdn.example/one-piece/OP08/OP08-001_EN.webp"
    assert base_image_url(plain) == plain


def test_language_image_url_swaps_the_language_suffix():
    base = "https://cdn.example/one-piece/OP08/OP08-001_EN.webp"
    assert language_image_url(base, "jp") == "https://cdn.example/one-piece/OP08/OP08-001_JP.webp"
    variant = "https://cdn.example/one-piece/OP08/OP08-001_p2_EN.webp"
    assert (
        language_image_url(variant, "jp")
        == "https://cdn.example/one-piece/OP08/OP08-001_p2_JP.webp"
    )
    assert language_image_url(variant, "en") == variant


def test_parse_promos_reads_products():
    promos = parse_promos((FIXTURES / "promos_index.html").read_text())

    assert len(promos) == 1
    promo = promos[0]
    assert promo.code == "X-TOURNAMENT-PACK-2026-VOL-4"
    assert promo.name == "Tournament Pack 2026 Vol.4"
    assert promo.kind == "promo"
    assert promo.release_date == "2026-10-01"
    assert promo.slug == "tournament-pack-16"


def test_parse_promo_product_page_maps_the_product_print():
    cards = {
        card.code: card for card in parse_cards((FIXTURES / "promo_products.html").read_text())
    }

    printings = cards["OP09-099"].printings

    assert [(printing.print_index, printing.set_name) for printing in printings][:3] == [
        (0, "Emperors in the New World"),
        (1, "Tournament Pack 2026 Vol.4"),
        (2, "Tournament Pack 2026 Vol.4"),
    ]
