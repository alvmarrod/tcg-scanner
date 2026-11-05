from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, Tag

_CODE_RE = re.compile(r"^[A-Z]{1,4}\d+$")
_KINDS = {"Booster Packs": "booster", "Starter Decks": "starter"}


@dataclass(frozen=True)
class ParsedSet:
    code: str
    name: str
    kind: str
    release_date: str | None
    slug: str


@dataclass(frozen=True)
class ParsedPrinting:
    set_name: str
    variant_label: str
    print_index: int
    current: bool
    usd: float | None
    eur: float | None
    tcgplayer_id: str | None
    cardmarket_id: str | None


@dataclass(frozen=True)
class ParsedCard:
    code: str
    name: str
    category: str | None
    color: str | None
    cost: int | None
    power: int | None
    counter: int | None
    life: int | None
    attribute: str | None
    traits: str | None
    effect: str | None
    image_url: str
    printings: list[ParsedPrinting]


def parse_index(html: str) -> list[ParsedSet]:
    table = BeautifulSoup(html, "html.parser").find("table", class_="sets-table")
    if table is None:
        return []

    sets: list[ParsedSet] = []
    kind: str | None = None
    for row in table.find_all("tr"):
        heading = row.find("th", class_="sub-heading")
        if heading:
            kind = _KINDS.get(heading.get_text(strip=True), "promo")
            continue

        cells = row.find_all("td")
        link = cells[0].find("a") if len(cells) >= 3 else None
        if kind is None or link is None:
            continue
        code = link.get_text(strip=True)
        if not _CODE_RE.match(code):
            continue

        sets.append(
            ParsedSet(
                code=code,
                name=cells[1].get_text(strip=True),
                kind=kind,
                release_date=_release_date(cells[2].get_text(strip=True)),
                slug=link["href"].removeprefix("/cards/"),
            )
        )
    return sets


def parse_cards(html: str) -> list[ParsedCard]:
    """Parse one entry per card, preferring its base-print image.

    The source emits one block per print, so parallel arts repeat the card code.
    """
    soup = BeautifulSoup(html, "html.parser")
    containers = soup.find_all("div", class_="card-page-main")
    cards: dict[str, ParsedCard] = {}
    for container in containers:
        card = _parse_card(container)
        if card is None:
            continue
        existing = cards.get(card.code)
        if existing is None or _image_rank(card.image_url) < _image_rank(existing.image_url):
            cards[card.code] = card
    return list(cards.values())


def variant_image_url(base_url: str, index: int) -> str:
    if index == 0:
        return base_url
    return re.sub(r"_([A-Z]{2})\.webp$", lambda m: f"_p{index}_{m.group(1)}.webp", base_url)


def base_image_url(url: str) -> str:
    """Strip a print suffix so variants can be derived from it."""
    return re.sub(r"_p\d+(_[A-Z]{2}\.webp)$", r"\1", url)


def _image_rank(url: str) -> int:
    match = re.search(r"_p(\d+)_[A-Z]{2}\.webp$", url)
    return int(match.group(1)) if match else 0


def _parse_card(container: Tag) -> ParsedCard | None:
    profile = container.find("div", class_="card-profile")
    text = container.find("div", class_="card-text")
    image = container.select_one(".card-image img")
    if profile is None or text is None or image is None:
        return None

    code = _text(text, ".card-text-id")
    name = _text(text, ".card-text-name")
    image_url = image.get("src")
    if not code or not name or not image_url:
        return None

    type_line = text.find("p", class_="card-text-type")
    type_text = type_line.get_text(" ", strip=True) if type_line else ""
    power = counter = attribute = traits = None
    effects: list[str] = []

    for section in text.find_all(["p", "div"], class_="card-text-section"):
        section_text = section.get_text(" ", strip=True)
        power = power if power is not None else _int(section_text, r"(\d+)\s*Power")
        counter = counter if counter is not None else _int(section_text, r"\+(\d+)\s*Counter")
        attribute = attribute or _tooltip(section, "Attribute")
        traits = traits or _tooltip(section, "Type")
        if section_text and section.find(attrs={"data-tooltip": True}) is None:
            effects.append(section_text)

    return ParsedCard(
        code=code,
        name=name,
        category=_tooltip(type_line, "Category"),
        color=_tooltip(type_line, "Color"),
        cost=_int(type_text, r"(\d+)\s*Cost"),
        power=power,
        counter=counter,
        life=_int(type_text, r"(\d+)\s*Life"),
        attribute=attribute,
        traits=traits,
        effect="\n".join(effects) or None,
        image_url=image_url,
        printings=_parse_printings(container, image_url),
    )


def _parse_printings(container: Tag, entry_image: str) -> list[ParsedPrinting]:
    table = container.find("table", class_="card-prints-versions")
    if table is None:
        return []

    printings: list[ParsedPrinting] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        cell = cells[0]
        label = cell.find("span", class_="prints-table-card-number")
        variant = label.get_text(strip=True) if label else ""
        if label:
            label.extract()
        link = cell.find("a")
        href = link.get("href") if link else None
        current = "current" in (row.get("class") or [])
        if href and "?v=" in href:
            index = _variant_index(href)
        elif href:
            index = 0
        else:
            # The current print has no link; its ordinal is the entry image's suffix.
            index = _image_rank(entry_image)

        printings.append(
            ParsedPrinting(
                set_name=cell.get_text(" ", strip=True),
                variant_label=variant or "base",
                print_index=index,
                current=current,
                usd=_price(row.select_one("a.card-price.usd")),
                eur=_price(row.select_one("a.card-price.eur")),
                tcgplayer_id=_path_id(row, "tcgplayer.com", r"/product/(\d+)/"),
                cardmarket_id=_path_id(row, "cardmarket.com", None),
            )
        )
    return printings


def _text(node: Tag, selector: str) -> str | None:
    found = node.select_one(selector)
    return found.get_text(strip=True) if found else None


def _tooltip(node: Tag | None, name: str) -> str | None:
    if node is None:
        return None
    found = node.find(attrs={"data-tooltip": name})
    return found.get_text(strip=True) if found else None


def _int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def _release_date(text: str) -> str | None:
    try:
        return datetime.strptime(text, "%d %b %y").date().isoformat()
    except ValueError:
        return None


def _variant_index(href: str | None) -> int | None:
    match = re.search(r"[?&]v=(\d+)", href or "")
    return int(match.group(1)) if match else None


def _price(anchor: Tag | None) -> float | None:
    if anchor is None:
        return None
    digits = re.sub(r"[^\d.,]", "", anchor.get_text(strip=True))
    if not digits:
        return None
    # The source uses '.' as the decimal separator; ',' only appears as thousands.
    digits = digits.replace(",", "")
    try:
        return float(digits)
    except ValueError:
        return None


def _path_id(row: Tag, host: str, pattern: str | None) -> str | None:
    for anchor in row.find_all("a", href=True):
        href = unquote(anchor["href"])
        if host not in href:
            continue
        if pattern:
            match = re.search(pattern, href)
            return match.group(1) if match else None
        return urlsplit(href).path
    return None
