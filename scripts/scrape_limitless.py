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
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

BASE = "https://onepiece.limitlesstcg.com"
USER_AGENT = "optcgsim-deckpacks-data/1.0 (community scraper; +https://github.com/hquezser)"

MAX_SHOW = 500  # above this the site returns a page with no decklists-table at all

# Values accepted by the region/time/type selects on /decks/lists. Unknown values are
# silently IGNORED by the site (you get an unfiltered listing), so anything not in these
# maps must be rejected locally rather than sent — see _normalizer below.
#
# The region select has no "all" option: "all" here means "send no region param". That is
# genuinely exhaustive — paginated unfiltered is a superset of the union of the continent
# codes, which on their own miss region-less events (e.g. World Finals 2026 is returned by
# region=jp but by none of eu/na/la/oc/asia).
REGION_MAP = {
    "eu": "Europe",
    "na": "North America",
    "la": "Latin America",
    "oc": "Oceania",
    "asia": "Asia",
    "all": "all",
}
REGION_ALIASES = {"as": "asia"}
TIME_VALUES = ("1months", "3months", "6months", "12months")
TIME_ALIASES = {"month": "1months"}
TYPE_VALUES = ("all", "regional", "treasure", "championship", "unofficial", "offline", "online")
TYPE_ALIASES = {"treasurecup": "treasure"}


def _normalizer(name: str, valid: Iterable[str], aliases: dict[str, str]):
    valid = tuple(valid)

    def norm(raw: str) -> str:
        v = raw.strip().lower()
        if v in aliases:
            canon = aliases[v]
            print(f"! --{name} {raw!r} is not a site value; using {canon!r}", file=sys.stderr)
            return canon
        if v not in valid:
            raise argparse.ArgumentTypeError(
                f"{raw!r} is not a valid --{name} (the site silently ignores unknown "
                f"values and returns everything). Choose from: {', '.join(valid)}"
            )
        return v

    return norm


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


def fetch_listing(session: requests.Session, params: dict, page: int = 1) -> str:
    p = dict(params)
    if page > 1:
        p["page"] = str(page)
    r = session.get(f"{BASE}/decks/lists", params=p, timeout=30)
    r.raise_for_status()
    return r.text


def collect_listing(
    session: requests.Session,
    params: dict,
    show: int,
    delay: float,
    max_pages: int,
) -> list[Tournament]:
    """Walk every page of the listing and merge the results.

    The listing paginates by DECK ROW, not by tournament: `show` caps deck rows per page,
    so a tournament straddling a page boundary appears on both pages with only part of its
    rows on each. Fetching a single page therefore yields silently truncated tournaments
    (e.g. Treasure Cup Utrecht: 5 rows on page 1, 11 on page 2). Merge by tournament URL
    and concatenate rows, keeping the site's placement order.
    """
    merged: dict[str, Tournament] = {}
    order: list[str] = []
    truncated = False
    page = 1
    while True:
        html = fetch_listing(session, params, page)
        try:
            tournaments = parse_listing(html)
        except RuntimeError:
            if page == 1:
                raise
            break  # past the last page the table is gone
        if not tournaments:
            break
        rows = 0
        gained = 0
        for t in tournaments:
            rows += len(t.decks)
            cur = merged.get(t.url)
            if cur is None:
                merged[t.url] = t
                order.append(t.url)
                gained += len(t.decks)
                continue
            seen = {(d.placement, d.url) for d in cur.decks}
            fresh = [d for d in t.decks if (d.placement, d.url) not in seen]
            cur.decks.extend(fresh)
            gained += len(fresh)
        print(
            f"  listing page {page}: {len(tournaments)} tournament(s), {rows} deck row(s)",
            file=sys.stderr,
        )
        if gained == 0:
            # Page repeated what we already had: the site stopped honouring ?page=. Stop
            # rather than hammer it for --max-pages requests that add nothing.
            if page > 1:
                print(f"! listing page {page} added no new rows, stopping", file=sys.stderr)
            break
        if rows < show:
            break  # short page = last page
        if page >= max_pages:
            truncated = True
            break
        page += 1
        time.sleep(delay)

    if truncated:
        print(
            f"! stopped at --max-pages {max_pages}; the listing has more results. "
            f"Raise --max-pages (or --show, up to {MAX_SHOW}) to cover everything.",
            file=sys.stderr,
        )
    return [merged[u] for u in order]


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
    # "all" is the absence of a region filter, not a region — don't tag decks with it.
    tags_template = ["meta"] + ([] if region_label == "all" else [region_label])
    tags_template += [t.format_tag.lower(), year]
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
        "description": describe(t, len(decks), region_label, time_label, False),
        "decks": decks,
    }


def strip_internal(dp: dict) -> dict:
    for d in dp["decks"]:
        d.pop("_source_url", None)
        d.pop("_placement", None)
    return dp


# ---------- non-destructive write ----------

NAME_PLACEMENT_RE = re.compile(r"\((\d+)(?:st|nd|rd|th)\)\s*$")


def placement_key(deck: dict) -> tuple[int, str]:
    """Sort key from the trailing placement in a deck name ('… (12th)'). Unparseable last."""
    m = NAME_PLACEMENT_RE.search(deck.get("name", ""))
    return (int(m.group(1)) if m else 10**6, deck.get("name", ""))


def load_existing(path: Path) -> dict | None:
    """Return the pack already on disk, or None if there is none.

    Raises on a file that exists but cannot be understood — refusing to write is the only
    safe move there, since we cannot tell what we would be destroying.
    """
    if not path.exists():
        return None
    try:
        dp = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"unreadable existing pack: {e}") from e
    if not isinstance(dp, dict) or not isinstance(dp.get("decks"), list):
        raise RuntimeError("existing pack has no 'decks' list")
    return dp


# Délai de grâce avant de considérer un tournoi comme définitivement collecté. Même valeur
# et même raison que dans le scraper ChinoizeCup : un tournoi terminé ne change plus, mais
# ses decklists peuvent arriver en retard sur la source.
JOURS_DE_GRACE = 3


def deja_collecte(path: Path, attendu: int, slug: str) -> bool:
    """Le pack sur disque rend-il inutile de re-télécharger ses decklists ?

    Vrai seulement si le pack existe, contient au moins autant de decks AVEC TEXTE que ce
    que le listing propose, et que le tournoi est plus vieux que JOURS_DE_GRACE.

    Sans ce garde-fou, chaque passage re-téléchargeait toutes les decklists de la fenêtre —
    une par requête — alors que les packs étaient déjà complets. Le coût d'un tournoi doit
    être payé une fois, pas tous les jours.

    Les trois portes de rattrapage restent ouvertes : pack absent, pack incomplet (à
    n'importe quel âge), ou tournoi récent.
    """
    try:
        dp = load_existing(path)
    except RuntimeError:
        # Pack illisible : on ne saute pas. Le recollecter est la seule issue utile.
        return False
    if dp is None:
        return False
    avec_texte = sum(1 for d in dp["decks"] if d.get("text"))
    if avec_texte < attendu or avec_texte == 0:
        return False
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", slug)
    if not m:
        return True          # pas de date lisible : « complet » est le seul signal
    return (date.today() - date(*map(int, m.groups()))).days > JOURS_DE_GRACE


def merge_decks(existing: list[dict], new: list[dict]) -> tuple[list[dict], int, int]:
    """Union existing and freshly scraped decks, keyed on deck name.

    Deck names are `<archetype> — <player> (<placement>)`, which is stable across runs for
    a given tournament. On a name hit we keep the existing entry and only enrich it (union
    the tags, refresh the text if the new run actually fetched one) so a run that sees
    fewer decks — a partial listing page, a fetch failure, a smaller --top — can never
    shrink a pack. Returns (decks, added, updated).
    """
    out = [dict(d) for d in existing]
    index = {d.get("name"): d for d in out}
    added = updated = 0
    for nd in new:
        cur = index.get(nd.get("name"))
        if cur is None:
            out.append(dict(nd))
            index[nd.get("name")] = out[-1]
            added += 1
            continue
        changed = False
        tags = list(cur.get("tags") or [])
        for tag in nd.get("tags") or []:
            if tag not in tags:
                tags.append(tag)
                changed = True
        cur["tags"] = tags
        if nd.get("text") and nd["text"] != cur.get("text"):
            cur["text"] = nd["text"]
            changed = True
        updated += changed
    out.sort(key=placement_key)
    return out, added, updated


def describe(t: Tournament, count: int, region_label: str, time_label: str, merged: bool) -> str:
    return (
        f"Top {count} from \"{t.name}\" "
        f"(region={region_label}, time={time_label}). "
        f"Scraped from {BASE}/decks/lists. "
        + ("Merged with the previously scraped pack. " if merged else "")
        + f"Source tournament: {t.url}"
    )


def write_pack(
    pack_dir: Path,
    dp: dict,
    t: Tournament,
    region_label: str,
    time_label: str,
    force: bool,
) -> tuple[int, str]:
    """Write deckpack.json without ever losing decks already on disk.

    Returns (deck_count, human-readable note).
    """
    path = pack_dir / "deckpack.json"
    existing = None if force else load_existing(path)
    if existing is None:
        note = "forced overwrite" if force and path.exists() else ""
        dp["description"] = describe(t, len(dp["decks"]), region_label, time_label, False)
    else:
        before = len(existing["decks"])
        decks, added, updated = merge_decks(existing["decks"], dp["decks"])
        dp["decks"] = decks
        dp["description"] = describe(t, len(decks), region_label, time_label, True)
        note = f"merged: {before} existing + {added} new"
        if updated:
            note += f", {updated} updated"
        if len(decks) < before:  # merge is a union, so this is unreachable — assert it anyway
            raise RuntimeError(f"refusing to write: merge shrank the pack {before} → {len(decks)}")

    pack_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dp, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return len(dp["decks"]), note


# ---------- main ----------

def build_params(args) -> dict:
    """Only send filters that actually narrow the listing.

    "all" is not a value any of these selects accepts; omitting the param is what the site
    means by unfiltered, and sending a bogus value happens to do the same thing. Omitting
    says what we mean.
    """
    p = {"show": str(args.show)}
    for key, value in (
        ("time", args.time),
        ("type", args.type),
        ("format", args.format),
        ("region", args.region),
        ("played", args.played),
    ):
        if value and value != "all":
            p[key] = value
    return p


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--region",
        default="eu",
        type=_normalizer("region", REGION_MAP, REGION_ALIASES),
        help="eu/na/la/oc/asia, or all (= every region, including region-less events)",
    )
    ap.add_argument(
        "--time",
        default="3months",
        type=_normalizer("time", TIME_VALUES, TIME_ALIASES),
        help="/".join(TIME_VALUES),
    )
    ap.add_argument(
        "--type",
        default="all",
        type=_normalizer("type", TYPE_VALUES, TYPE_ALIASES),
        help="/".join(TYPE_VALUES),
    )
    ap.add_argument("--format", default="all", help="all/OP16/...")
    ap.add_argument("--played", default="all")
    ap.add_argument("--show", type=int, default=100, help=f"deck rows per listing page (max {MAX_SHOW})")
    ap.add_argument("--top", type=int, default=16, help="decks per tournament")
    ap.add_argument("--output", default="packs", help="output directory")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    ap.add_argument("--limit-tournaments", type=int, default=0, help="0 = all")
    ap.add_argument("--max-pages", type=int, default=50, help="listing pages to walk at most")
    ap.add_argument(
        "--resync", action="store_true",
        help="re-télécharger même les tournois déjà collectés (non destructif, "
             "contrairement à --force)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="replace existing packs instead of merging into them (destructive)",
    )
    args = ap.parse_args(argv)

    if not 1 <= args.show <= MAX_SHOW:
        ap.error(f"--show must be between 1 and {MAX_SHOW} (the site returns no table above that)")
    if args.delay < 0.5:
        ap.error("--delay must be >= 0.5s to stay polite")

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    params = build_params(args)
    print(f"→ fetching listing {BASE}/decks/lists?{params}", file=sys.stderr)
    tournaments = collect_listing(session, params, args.show, args.delay, args.max_pages)
    if args.limit_tournaments:
        tournaments = tournaments[: args.limit_tournaments]
    print(
        f"→ {len(tournaments)} tournament(s) found, "
        f"{sum(len(t.decks) for t in tournaments)} deck row(s)",
        file=sys.stderr,
    )

    region_label = REGION_MAP.get(args.region, args.region)
    cache: dict[str, Decklist | None] = {}
    written = 0
    skipped = 0
    sautes = 0
    failed = 0
    slugs: dict[str, str] = {}  # slug -> tournament url, so two events never share a pack
    for t in tournaments:
        if not t.decks:
            print(f"  · {t.slug}: no decks, skipping", file=sys.stderr)
            skipped += 1
            continue
        owner = slugs.setdefault(t.slug, t.url)
        if owner != t.url:
            n = 2
            while slugs.setdefault(f"{t.slug}-{n}", t.url) != t.url:
                n += 1
            print(f"  ! slug collision on {t.slug}, using {t.slug}-{n}", file=sys.stderr)
            t.slug = f"{t.slug}-{n}"
        dp = build_deckpack(t, args.top, region_label, args.time)
        # Déjà collecté et réglé : aucune requête. C'est ce qui rend une fenêtre large
        # gratuite, et donc le rattrapage des trous possible.
        if not (args.resync or args.force) and \
                deja_collecte(Path(args.output) / t.slug / "deckpack.json",
                              len(dp["decks"]), t.slug):
            sautes += 1
            continue
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
        try:
            count, note = write_pack(out / t.slug, dp, t, region_label, args.time, args.force)
        except RuntimeError as e:
            print(f"  ! {t.slug}: not written — {e}", file=sys.stderr)
            failed += 1
            continue
        detail = ", ".join(x for x in (f"dropped {dropped}" if dropped else "", note) if x)
        print(
            f"  ✓ {t.slug}: {count} decks" + (f" ({detail})" if detail else ""),
            file=sys.stderr,
        )
        written += 1

    print(
        f"\nDone: {written} pack(s) written, {skipped} skipped"
        + (f", {sautes} déjà collecté(s) et non redemandé(s)" if sautes else "")
        + (f", {failed} failed" if failed else "")
        + f" → {out}/",
        file=sys.stderr,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
