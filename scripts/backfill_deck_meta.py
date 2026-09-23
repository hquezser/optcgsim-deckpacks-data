#!/usr/bin/env python3
"""Backfill de la méta structurée (deckpack v1 additif) sur les packs existants.

Les scrapers émettent `archetype`/`player`/`placement` par deck et `format`/`date` par
pack depuis le passage de la spec ; ce script déclare la même chose sur les packs écrits
avant, en déduisant les champs des conventions historiques :

- deck : `name` = `<archétype> — <joueur> (<placement>)` (tiret cadratin, suffixe
  ordinal optionnel) ;
- pack : `format` depuis le préfixe du nom (`OP16 ...` ou `[OP17] ...`), sinon un tag
  de deck `op\d+(\.\d+)?` ; `date` depuis le préfixe du slug de dossier.

Règles :

- **Combler, jamais écraser** : un champ déjà déclaré n'est pas touché.
- **Rien deviner** : un nom non conforme ou un slug sans date ne produit aucun champ —
  le consommateur garde son chemin de déduction.
- **Idempotent** : relancer sur un pack déjà déclaré ne change aucun octet.
- Réécriture avec la même sérialisation que les scrapers (`indent=2, ensure_ascii=False`),
  ordre canonique des clés : schema_version, name, format, date, …puis l'existant ;

    python3 scripts/backfill_deck_meta.py            # écrit + rapporte
    python3 scripts/backfill_deck_meta.py --check    # rapporte sans écrire (≠0 si diffs)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Même convention que les scrapers ET que sitegen/parse.py : tiret cadratin entouré
# d'espaces, suffixe ordinal anglais facultatif (limitless « (1st) », chinoizecup « (1) »).
_NAME_RE = re.compile(
    r"^(?P<archetype>.+?)\s+—\s+(?P<player>.+?)\s+\((?P<place>\d+)(?:st|nd|rd|th)?\)$"
)
_FORMAT_NAME_RE = re.compile(r"^\[?(OP\d+(?:\.\d+)?)\]?", re.IGNORECASE)
_FORMAT_TAG_RE = re.compile(r"^op\d+(?:\.\d+)?$", re.IGNORECASE)
_SLUG_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

# Ordre canonique : les champs déclaratifs se lisent juste après `name`, avant le reste.
_DECK_META = ("archetype", "player", "placement")
_PACK_META = ("format", "date")


def _deck_meta(name: str) -> dict:
    m = _NAME_RE.match(name or "")
    if not m:
        return {}
    return {"archetype": m.group("archetype"), "player": m.group("player"),
            "placement": int(m.group("place"))}


def _pack_format(dp: dict) -> str | None:
    m = _FORMAT_NAME_RE.match(dp.get("name") or "")
    if m:
        return m.group(1).upper()
    for d in dp.get("decks") or []:
        for tag in d.get("tags") or []:
            if _FORMAT_TAG_RE.fullmatch(tag or ""):
                return tag.upper()
    return None


def backfill(dp: dict, slug: str) -> tuple[dict, int]:
    """Renvoie (manifeste complété, nombre de champs ajoutés). Jamais de réécriture."""
    ajouts = 0

    decks = []
    for d in dp.get("decks") or []:
        if not isinstance(d, dict):
            decks.append(d)
            continue
        declare = {k: v for k, v in _deck_meta(d.get("name", "")).items() if k not in d}
        ajouts += len(declare)
        if declare:
            # name + méta déclarée + le reste dans l'ordre d'origine.
            if "name" in d:
                d = {"name": d["name"], **declare,
                     **{k: v for k, v in d.items() if k != "name"}}
            else:
                d = {**declare, **d}
        decks.append(d)

    declare_pack: dict[str, str] = {}
    if "format" not in dp:
        fmt = _pack_format(dp)
        if fmt:
            declare_pack["format"] = fmt
    if "date" not in dp:
        m = _SLUG_DATE_RE.match(slug)
        if m:
            declare_pack["date"] = m.group(1)
    ajouts += len(declare_pack)

    out: dict = {}
    for k, v in dp.items():
        out[k] = v
        if k == "name":  # format/date se déclarent juste après le nom
            out.update(declare_pack)
    else:
        if "name" not in dp:
            out.update(declare_pack)
    out["decks"] = decks
    return out, ajouts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--packs", default="packs", help="dossier corpus (défaut: packs)")
    ap.add_argument("--check", action="store_true",
                    help="rapporte sans écrire ; code 1 si des champs manquent")
    args = ap.parse_args(argv)

    packs_dir = Path(args.packs)
    touchés = champs = 0
    for pack_dir in sorted(packs_dir.iterdir()):
        manifest_path = pack_dir / "deckpack.json"
        if not pack_dir.is_dir() or not manifest_path.is_file():
            continue
        dp = json.loads(manifest_path.read_text(encoding="utf-8"))
        out, ajouts = backfill(dp, pack_dir.name)
        if not ajouts:
            continue
        touchés += 1
        champs += ajouts
        print(f"  {pack_dir.name}: +{ajouts} champ(s)", file=sys.stderr)
        if not args.check:
            manifest_path.write_text(
                json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")

    mode = "à compléter" if args.check else "complété(s)"
    print(f"{touchés} pack(s) {mode}, {champs} champ(s) au total.", file=sys.stderr)
    return 1 if args.check and touchés else 0


if __name__ == "__main__":
    sys.exit(main())
