#!/usr/bin/env python3
"""Scrape chinoizecupstats.com decklists and emit one deckpack per tournament.

Each tournament's top-N decks are written to packs/<date-slug>/deckpack.json in the
deckpack v1 format (see ../optcgsim-deckpacks/SPEC-deckpack.md). Decklists are inlined
as `text` in OPTCGSim native format (`1x<leader>\\n4x<card>\\n...`).

Only card IDs + quantities + public meta (tournament name, date, placement, player,
leader) are extracted. No card text, no images.

Source: https://chinoizecupstats.com (Next.js SSR site). The tournaments listing at
/tournaments exposes up to 100 events as <a href="/tournaments/{id}"> cards. Each
tournament page embeds a SportsEvent JSON-LD block (name, startDate) and a standings
table (Place / Player / Leader / Record) with per-row decklist links
/decklists/{tournament_id}/{player_slug}. Each decklist page inlines the leader image
+ one row per unique card with a `× N` count.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import packmerge  # noqa: E402  (chemin ajusté juste au-dessus)
from bs4 import BeautifulSoup

BASE = "https://chinoizecupstats.com"
USER_AGENT = "optcgsim-deckpacks-data/1.0 (community scraper; +https://github.com/hquezser)"

# Card image URL pattern: .../one-piece/<SET>/<CARD_ID>_EN.webp
CARD_IMG_RE = re.compile(
    r"limitlesstcg\.nyc3\.cdn\.digitaloceanspaces\.com/one-piece/[^/]+/([^/]+)_EN\.webp"
)
COUNT_RE = re.compile(r"×\s*(\d+)")
# A native decklist line: "4xOP15-061". Used to verify a fetched deck is complete.
DECK_LINE_RE = re.compile(r"^(\d+)x([A-Za-z0-9][A-Za-z0-9-]*)$", re.MULTILINE)


@dataclass
class DeckRow:
    placement: str  # "1", "2", ... (1 for the champion row which has an empty cell)
    player: str
    leader: str  # leader display name (used as archetype proxy)
    url: str  # absolute decklist URL


@dataclass
class Tournament:
    name: str
    url: str
    date: str | None  # ISO YYYY-MM-DD (from SportsEvent startDate)
    slug: str
    format_tag: str  # generic "op" — site does not expose per-event format version
    decks: list[DeckRow] = field(default_factory=list)


@dataclass
class Decklist:
    leader_id: str
    cards: list[tuple[int, str]]  # (count, id) in DOM order


# ---------- listing page ----------

def fetch_listing(session: requests.Session) -> str:
    r = session.get(f"{BASE}/tournaments", timeout=30)
    r.raise_for_status()
    return r.text


def parse_listing(html: str) -> list[str]:
    """Return tournament IDs (in listing order) from the tournaments page."""
    soup = BeautifulSoup(html, "html.parser")
    ids: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=re.compile(r"^/tournaments/[a-f0-9]+$")):
        tid = a["href"].rsplit("/", 1)[1]
        if tid in seen:
            continue
        seen.add(tid)
        ids.append(tid)
    return ids


# ---------- tournament detail page ----------

def parse_sports_event(html: str) -> dict | None:
    """Extract the SportsEvent JSON-LD block (name, startDate, ...)."""
    soup = BeautifulSoup(html, "html.parser")
    for s in soup.find_all("script", type="application/ld+json"):
        if not s.string:
            continue
        try:
            data = json.loads(s.string)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "SportsEvent":
            return data
    return None


def parse_standings(html: str) -> list[DeckRow]:
    """Parse the standings table → list[DeckRow] (placement, player, leader, decklist url)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise RuntimeError("standings table not found — site layout may have changed")
    rows: list[DeckRow] = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        place = tds[0].get_text(strip=True)
        # champion row has an empty Place cell (crown icon) → treat as "1"
        if not place:
            place = "1"
        if not place.isdigit():
            continue
        # player: first <span> inside the player cell (second span is the country code)
        player_spans = tds[1].find_all("span")
        player = player_spans[0].get_text(strip=True) if player_spans else tds[1].get_text(strip=True)
        leader = tds[2].get_text(strip=True)
        a = tr.find("a", href=re.compile(r"^/decklists/"))
        if not a:
            continue
        rows.append(DeckRow(
            placement=place,
            player=player,
            leader=leader,
            url=BASE + a["href"],
        ))
    return rows


def fetch_tournament(
    session: requests.Session, tid: str
) -> tuple[str, str | None, list[DeckRow]]:
    """Fetch /tournaments/{tid} → (name, iso_date, decks). One request."""
    url = f"{BASE}/tournaments/{tid}"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    html = r.text
    event = parse_sports_event(html)
    name = (event or {}).get("name") or tid
    start = (event or {}).get("startDate")
    date_iso = str(start)[:10] if start else None
    decks = parse_standings(html)
    return name, date_iso, decks


# ---------- decklist detail page ----------

def parse_decklist(html: str) -> Decklist | None:
    """Parse a /decklists/{tid}/{player} page → Decklist (leader_id + cards)."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    if main is None:
        return None
    leader_id: str | None = None
    cards: list[tuple[int, str]] = []
    for img in main.find_all("img"):
        src = img.get("src") or ""
        m = CARD_IMG_RE.search(src)
        if not m:
            continue
        card_id = m.group(1)
        # card rows live inside a div.relative.group; the leader image does not
        row = img.find_parent("div", class_="group")
        if row is None:
            if leader_id is None:
                leader_id = card_id
            continue
        txt = row.get_text(" ", strip=True)
        cm = COUNT_RE.search(txt)
        if not cm:
            continue
        n = int(cm.group(1))
        if n <= 0:
            continue
        cards.append((n, card_id))
    if not leader_id or not cards:
        return None
    return Decklist(leader_id=leader_id, cards=cards)


def fetch_decklist(
    session: requests.Session, url: str, cache: dict[str, Decklist | None]
) -> Decklist | None:
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
    lines = [f"1x{dl.leader_id}"]
    lines.extend(f"{n}x{cid}" for n, cid in dl.cards)
    return "\n".join(lines)


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "tournament"


def build_deckpack(t: Tournament, top: int) -> dict:
    year = t.date.split("-")[0] if t.date else "unknown"
    tags_template = ["meta", "online", t.format_tag.lower(), year]
    decks = []
    for row in t.decks[:top]:
        decks.append({
            "name": f"{row.leader} — {row.player} ({row.placement})",
            "tags": list(tags_template),
            "text": "",
            "_source_url": row.url,
            "_placement": row.placement,
        })
    return {
        "schema_version": 1,
        "name": t.name,
        "author": "chinoizecup-scraper",
        "description": (
            f"Top {len(decks)} from \"{t.name}\" "
            f"(source=chinoizecupstats.com, online cup). "
            f"Scraped from {BASE}/tournaments. "
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

def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=16, help="decks per tournament")
    ap.add_argument("--output", default="packs", help="output directory")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    ap.add_argument(
        "--limit-tournaments", type=int, default=0,
        help="0 = all; otherwise scrape only the first N tournaments from the listing",
    )
    ap.add_argument(
        "--tournaments", nargs="*", default=[],
        help="specific tournament IDs to scrape (skips the listing fetch). "
             "Example: 6a43969983fd320299bd4a17",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="replace existing packs instead of merging into them. Off by default: a run "
             "that sees fewer decks must never destroy a richer pack already on disk.",
    )
    args = ap.parse_args(argv)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    if args.tournaments:
        tids = args.tournaments
        print(f"→ {len(tids)} tournament ID(s) provided via --tournaments", file=sys.stderr)
    else:
        print(f"→ fetching listing {BASE}/tournaments", file=sys.stderr)
        html = fetch_listing(session)
        tids = parse_listing(html)
        print(f"→ {len(tids)} tournament(s) found", file=sys.stderr)
        if args.limit_tournaments:
            tids = tids[: args.limit_tournaments]

    cache: dict[str, Decklist | None] = {}
    written = 0
    skipped = 0
    for tid in tids:
        turl = f"{BASE}/tournaments/{tid}"
        try:
            name, date_iso, decks = fetch_tournament(session, tid)
        except requests.RequestException as e:
            print(f"  ! tournament {tid} fetch failed: {e}", file=sys.stderr)
            skipped += 1
            continue
        time.sleep(args.delay)
        if not decks:
            print(f"  · {tid}: no decks in standings, skipping", file=sys.stderr)
            skipped += 1
            continue
        if date_iso:
            slug = f"{date_iso}-{slugify(name)}"
        else:
            slug = slugify(name)
        t = Tournament(
            name=name,
            url=turl,
            date=date_iso,
            slug=slug,
            format_tag="op",
            decks=decks,
        )
        dp = build_deckpack(t, args.top)
        for d in dp["decks"]:
            dl = fetch_decklist(session, d["_source_url"], cache)
            time.sleep(args.delay)
            if dl is None:
                continue
            d["text"] = decklist_to_text(dl)
        before = len(dp["decks"])
        dp["decks"] = [d for d in dp["decks"] if d.get("text")]
        # A One Piece deck is exactly 1 leader + 50 cards. A shorter list means the fetch
        # came back incomplete: OPTCGSim refuses it at import ("Deck de 47 cartes (attendu
        # 50)"), so shipping it would publish a decklist nobody can use. Drop it here rather
        # than let a broken pack reach consumers.
        kept = []
        for d in dp["decks"]:
            total = sum(int(m.group(1)) for m in DECK_LINE_RE.finditer(d["text"]))
            leader = DECK_LINE_RE.match(d["text"].lstrip().splitlines()[0]) if d["text"] else None
            if leader and total - int(leader.group(1)) == 50:
                kept.append(d)
            else:
                print(f"  · {t.slug}: {d['name']}: {total - (int(leader.group(1)) if leader else 0)}"
                      f" cards (expected 50), incomplete fetch — dropping", file=sys.stderr)
        dp["decks"] = kept
        dropped = before - len(dp["decks"])
        if not dp["decks"]:
            print(f"  · {t.slug}: 0 decks fetched, skipping", file=sys.stderr)
            skipped += 1
            continue
        dp = strip_internal(dp)

        # Union avec ce qui est déjà sur disque, jamais un remplacement : un run qui voit
        # moins de decks (site incomplet, decklist en échec) ne doit pas détruire un pack
        # plus riche. Vu en usage réel sur l'autre scraper : 16 decks réduits à 5.
        def describe(n: int, fusionne: bool, _t=t) -> str:
            base = (f"Top {n} from \"{_t.name}\" (source=chinoizecupstats.com, online cup). "
                    f"Scraped from {BASE}/tournaments. Source tournament: {_t.url}")
            return base + (" Merged across runs." if fusionne else "")

        try:
            count, note = packmerge.write_pack_merged(
                out / t.slug, dp, force=args.force, describe=describe)
        except RuntimeError as e:
            print(f"  ! {t.slug}: {e} — skipping", file=sys.stderr)
            skipped += 1
            continue
        suffixe = f" — {note}" if note else ""
        print(f"  ✓ {t.slug}: {count} decks (dropped {dropped}){suffixe}", file=sys.stderr)
        written += 1

    print(f"\nDone: {written} pack(s) written, {skipped} skipped → {out}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
