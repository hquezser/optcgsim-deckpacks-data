"""Tests de `scripts/backfill_deck_meta.py` — migration hors-ligne de la méta structurée.

Verrouille les trois règles du script : combler sans écraser, ne rien deviner,
idempotence octale. Aucun accès réseau, tout dans `tmp_path`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# `conftest.py` ajoute scripts/ à sys.path.
import backfill_deck_meta as bf  # noqa: E402


def _pack(decks: list[dict], **extra) -> dict:
    return {"schema_version": 1, "name": "OP16 Test - Regional X", "author": "t",
            "description": "d", **extra, "decks": decks}


# --------------------------------------------------------------- deck level

def test_comble_archetype_player_placement_depuis_le_nom():
    dp = _pack([{"name": "Purple Enel — Joueuse A (3rd)", "text": "1xOP01-001"}])
    out, ajouts = bf.backfill(dp, "2026-07-12-regional-x")
    d = out["decks"][0]
    assert (d["archetype"], d["player"], d["placement"]) == ("Purple Enel", "Joueuse A", 3)
    assert ajouts == 3 + 2  # 3 champs deck + format + date


def test_placement_sans_suffixe_ordinal():
    """Convention chinoizecup : « (1) » et non « (1st) »."""
    dp = _pack([{"name": "Lim — GreenD (1)", "text": "1xOP01-001"}])
    out, _ = bf.backfill(dp, "2025-12-03-chinoizecup-110")
    assert out["decks"][0]["placement"] == 1


def test_n_ecrase_jamais_un_champ_declare():
    dp = _pack([{"name": "A — B (1st)", "archetype": "Déclaré", "placement": 9,
                 "text": "1xOP01-001"}])
    out, _ = bf.backfill(dp, "2026-07-12-x")
    d = out["decks"][0]
    assert d["archetype"] == "Déclaré" and d["placement"] == 9
    assert d["player"] == "B"  # seul le manquant est comblé


def test_nom_non_conforme_ne_produit_rien():
    """Pas de regex, pas de champs : mieux vaut l'absence qu'une valeur devinée."""
    dp = _pack([{"name": "Deck libre sans convention", "text": "1xOP01-001"}])
    out, ajouts = bf.backfill(dp, "x")
    assert "archetype" not in out["decks"][0]
    assert ajouts == 1  # format du préfixe « OP16 » seulement (slug sans date)


def test_ordre_canonique_name_puis_meta():
    dp = _pack([{"name": "A — B (2nd)", "tags": ["meta"], "text": "1xOP01-001"}])
    out, _ = bf.backfill(dp, "2026-07-12-x")
    assert list(out["decks"][0])[:5] == ["name", "archetype", "player", "placement", "tags"]


# --------------------------------------------------------------- pack level

def test_format_depuis_prefixe_du_nom():
    dp = _pack([{"name": "A — B (1st)", "text": "t"}], name="[OP17] ChinoizeCup #9")
    out, _ = bf.backfill(dp, "x")
    assert out["format"] == "OP17"


def test_format_depuis_tag_quand_nom_muet():
    dp = _pack([{"name": "A — B (1st)", "tags": ["meta", "op14.5"], "text": "t"}],
               name="ChinoizeCup #9")
    out, _ = bf.backfill(dp, "x")
    assert out["format"] == "OP14.5"


def test_format_absent_si_rien_ne_le_déclare():
    """Le tag « op » nu (cas chinoizecup réel) ne suffit pas : pas de format deviné."""
    dp = _pack([{"name": "A — B (1st)", "tags": ["meta", "op"], "text": "t"}],
               name="ChinoizeCup #9")
    out, _ = bf.backfill(dp, "x")
    assert "format" not in out


def test_date_depuis_le_slug():
    dp = _pack([{"name": "A — B (1st)", "text": "t"}])
    out, _ = bf.backfill(dp, "2026-07-12-regional-x")
    assert out["date"] == "2026-07-12"


def test_pack_meta_positionnee_apres_name():
    dp = _pack([{"name": "A — B (1st)", "text": "t"}])
    out, _ = bf.backfill(dp, "2026-07-12-x")
    assert list(out)[:4] == ["schema_version", "name", "format", "date"]


def test_idempotent_second_run_zero_champ():
    dp = _pack([{"name": "A — B (1st)", "text": "t"}])
    once, _ = bf.backfill(dp, "2026-07-12-x")
    twice, ajouts = bf.backfill(once, "2026-07-12-x")
    assert ajouts == 0 and twice == once


# --------------------------------------------------------------- bout-en-bout fichier

def test_main_ecrit_et_check_signale(tmp_path, capsys):
    pack_dir = tmp_path / "packs" / "2026-07-12-regional-x"
    pack_dir.mkdir(parents=True)
    (pack_dir / "deckpack.json").write_text(
        json.dumps(_pack([{"name": "A — B (1st)", "text": "t"}])))
    assert bf.main(["--packs", str(tmp_path / "packs"), "--check"]) == 1  # diffs à venir
    assert bf.main(["--packs", str(tmp_path / "packs")]) == 0
    on_disk = json.loads((pack_dir / "deckpack.json").read_text())
    assert on_disk["decks"][0]["placement"] == 1 and on_disk["format"] == "OP16"
    assert bf.main(["--packs", str(tmp_path / "packs"), "--check"]) == 0  # plus rien
