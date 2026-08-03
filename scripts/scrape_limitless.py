#!/usr/bin/env python3
"""Scrape one piece.limitlesstcg.com decklists and emit one deckpack per tournament.

Each tournament's top-N decks are written to packs/<date-slug>/deckpack.json in the
deckpack v1 format (see ../optcgsim-deckpacks/SPEC-deckpack.md). Decklists are inlined
as `text` in OPTCGSim native format (`1x<leader>\\n4x<card>\\n...`).

Only card IDs + quantities + public meta (tournament name, date, placement, player,
archetype) are extracted. No card text, no images.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

BASE = "https://onepiece.limitlesstcg.com"
USER_AGENT = "optcgsim-deckpacks-data/1.0 (community scraper; +https://github.com/hquezser)"

REGION_MAP = {
    "eu": "Europe",
    "na": "North America",
    "la": "Latin America",
    "oc": "Oceania",
    "as": "Asia",
    "all": "all",
}


@dataclass
class DeckRow:
    placement: str
    archetype: str
    player: str
    url: str  # absolute


@dataclass
class Tournament:
    name: str  # raw heading text, e.g. "OP16 12th July 2026 - Treasure Cup Utrecht"
    url: str
    date: str | None  # ISO YYYY-MM-DD if parseable
    slug: str  # date-prefixed slug
    format_tag: str  # e.g. "OP16" (first token of the heading)
    decks: list[DeckRow] = field(default_factory=list)


@dataclass
class Decklist:
    cards: list[tuple[int, str]]  # (count, id) in DOM order (leader first)


# ---------- listing page ----------

PLACEMENT_RE = re.compile(r"^(\d+)(st|nd|rd|th)$")
HEADING_DATE_RE = re.compile(
    r"^\s*[A-Z0-9]+\s+"  # format tag (OP16, ST31, ...)
    r"(\d{1,2})(?:st|nd|rd|th)\s+"
    r"([A-Za-z]+)\s+"
    r"(\d{4})\s*-\s*(.+)$"
)
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_tournament_heading(text: str) -> tuple[str | None, str, str]:
    """Return (iso_date, name, format_tag) from a heading like 'OP16 12th July 2026 - Treasure Cup Utrecht'."""
    s = text.strip()
    format_tag = s.split()[0] if s else ""
    m = HEADING_DATE_RE.match(s)
    if not m:
        return None, s, format_tag
    day, month_name, year, name = m.groups()
    month = MONTHS.get(month_name.lower())
    if not month:
        return None, name.strip(), format_tag
    try:
        iso = datetime(int(year), month, int(day)).date().isoformat()
    except ValueError:
        iso = None
    return iso, name.strip(), format_tag


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "tournament"


def fetch_listing(session: requests.Session, params: dict) -> str:
    r = session.get(f"{BASE}/decks/lists", params=params, timeout=30)
    r.raise_for_status()
    return r.text


def parse_listing(html: str) -> list[Tournament]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="decklists-table")
    if not table:
        raise RuntimeError("decklists-table not found — site layout may have changed")

    tournaments: list[Tournament] = []
    current: Tournament | None = None
    for tr in table.find_all("tr"):
        sub = tr.find("th", class_="sub-heading")
        if sub:
            a = sub.find("a")
            if not a:
                continue
            heading = a.get_text(strip=True)
            iso_date, name, format_tag = parse_tournament_heading(heading)
            if iso_date:
                slug = f"{iso_date}-{slugify(name)}"
            else:
                slug = slugify(heading)
            current = Tournament(
                name=heading,
                url=BASE + a["href"],
                date=iso_date,
                slug=slug,
                format_tag=format_tag,
            )
            tournaments.append(current)
            continue
        tds = tr.find_all("td")
        if len(tds) != 2 or current is None:
            continue
        placement = tds[0].get_text(strip=True)
        if not PLACEMENT_RE.match(placement):
            continue
        a = tds[1].find("a")
        if not a:
            continue
        annotation = a.find("span", class_="annotation")
        player = annotation.get_text(strip=True) if annotation else ""
        # strip the "by " prefix
        if player.lower().startswith("by "):
            player = player[3:].strip()
        # archetype = anchor text without the annotation span
        archetype = a.get_text(strip=True)
        if annotation:
            archetype = archetype.replace(annotation.get_text(strip=True), "").strip()
        current.decks.append(DeckRow(
            placement=placement,
            archetype=archetype,
            player=player,
            url=BASE + a["href"],
        ))
    return tournaments


# ---------- deck detail page ----------

def parse_decklist(html: str) -> Decklist | None:
    soup = BeautifulSoup(html, "html.parser")
    cards: list[tuple[int, str]] = []
    for div in soup.select("div.decklist-card"):
        count = div.get("data-count")
        card_id = div.get("data-id")
        if not count or not card_id:
            continue
        try:
            n = int(count)
        except ValueError:
            continue
        if n <= 0 or not card_id:
            continue
        cards.append((n, card_id))
    if not cards:
        return None
    return Decklist(cards=cards)


def fetch_decklist(session: requests.Session, url: str, cache: dict[str, Decklist | None]) -> Decklist | None:
    if url in cache:
        return cache[url]
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        dl = parse_decklist(r.text)
    except requests.RequestException as e:
        print(f"  ! fetch failed {url}: {e}", file=sys.stderr)
        dl = None
    cache[url] = dl
    return dl


# ---------- deckpack emission ----------

def decklist_to_text(dl: Decklist) -> str:
    return "\n".join(f"{n}x{cid}" for n, cid in dl.cards)


def build_deckpack(t: Tournament, top: int, region_label: str, time_label: str) -> dict:
    year = t.date.split("-")[0] if t.date else "unknown"
    tags_template = ["meta", region_label, t.format_tag.lower(), year]
    decks = []
    for row in t.decks[:top]:
        decks.append({
            "name": f"{row.archetype} — {row.player} ({row.placement})",
            "tags": list(tags_template),
            "text": "",  # filled by caller after fetch
            "_source_url": row.url,
            "_placement": row.placement,
        })
    return {
        "schema_version": 1,
        "name": t.name,
        "author": "limitlesstcg-scraper",
        "description": (
            f"Top {len(decks)} from \"{t.name}\" "
            f"(region={region_label}, time={time_label}). "
            f"Scraped from {BASE}/decks/lists. "
            f"Source tournament: {t.url}"
        ),
        "decks": decks,
    }


def strip_internal(dp: dict) -> dict:
    for d in dp["decks"]:
        d.pop("_source_url", None)
        d.pop("_placement", None)
    return dp


# ---------- main ----------

def build_params(args) -> dict:
    p = {
        "show": str(args.show),
        "time": args.time,
        "type": args.type,
        "format": args.format,
        "region": args.region,
        "played": args.played,
    }
    return p


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="eu", help="eu/na/la/oc/as/all")
    ap.add_argument("--time", default="3months", help="month/3months/6months/12months")
    ap.add_argument("--type", default="all", help="all/regional/treasurecup/...")
    ap.add_argument("--format", default="all", help="all/OP16/...")
    ap.add_argument("--played", default="all")
    ap.add_argument("--show", type=int, default=100)
    ap.add_argument("--top", type=int, default=16, help="decks per tournament")
    ap.add_argument("--output", default="packs", help="output directory")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    ap.add_argument("--limit-tournaments", type=int, default=0, help="0 = all")
    args = ap.parse_args(argv)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    params = build_params(args)
    print(f"→ fetching listing {BASE}/decks/lists?{params}", file=sys.stderr)
    html = fetch_listing(session, params)
    tournaments = parse_listing(html)
    if args.limit_tournaments:
        tournaments = tournaments[: args.limit_tournaments]
    print(f"→ {len(tournaments)} tournament(s) found", file=sys.stderr)

    region_label = REGION_MAP.get(args.region, args.region)
    cache: dict[str, Decklist | None] = {}
    written = 0
    skipped = 0
    for t in tournaments:
        if not t.decks:
            print(f"  · {t.slug}: no decks, skipping", file=sys.stderr)
            skipped += 1
            continue
        dp = build_deckpack(t, args.top, region_label, args.time)
        # fetch decklists
        for d in dp["decks"]:
            url = d["_source_url"]
            dl = fetch_decklist(session, url, cache)
            time.sleep(args.delay)
            if dl is None:
                continue
            d["text"] = decklist_to_text(dl)
        # drop decks we couldn't fetch
        before = len(dp["decks"])
        dp["decks"] = [d for d in dp["decks"] if d.get("text")]
        dropped = before - len(dp["decks"])
        if not dp["decks"]:
            print(f"  · {t.slug}: 0 decks fetched, skipping", file=sys.stderr)
            skipped += 1
            continue
        dp = strip_internal(dp)
        pack_dir = out / t.slug
        pack_dir.mkdir(parents=True, exist_ok=True)
        (pack_dir / "deckpack.json").write_text(
            json.dumps(dp, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"  ✓ {t.slug}: {len(dp['decks'])} decks (dropped {dropped})", file=sys.stderr)
        written += 1

    print(f"\nDone: {written} pack(s) written, {skipped} skipped → {out}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
