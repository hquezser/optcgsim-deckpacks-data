"""Le scraper doit cesser d'insister quand la source dit qu'elle est saturée.

Ce n'est pas de la théorie : le 2026-09-03, chinoizecupstats.com répondait 503 et son
robots.txt renvoyait « usage_exceeded ». Avec l'ancien comportement — un « skip » par
tournoi puis on continue — le scraper enchaînait ses 20 tournois, soit une vingtaine de
requêtes contre un serveur qui venait de dire qu'il n'en pouvait plus.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scrape_chinoizecup as sc  # noqa: E402


def _erreur(code: int) -> requests.HTTPError:
    r = requests.Response()
    r.status_code = code
    return requests.HTTPError(response=r)


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_un_code_serveur_compte_comme_saturation(code):
    assert sc._est_saturation(_erreur(code))


@pytest.mark.parametrize("code", [400, 401, 403, 404, 410])
def test_un_code_client_ne_compte_pas(code):
    """Un 404 concerne UN tournoi ; arrêter toute la collecte pour ça la rendrait inutile."""
    assert not sc._est_saturation(_erreur(code))


def test_les_pannes_reseau_comptent_comme_saturation():
    """Pas de code HTTP, mais le même verdict : insister ne sert à rien."""
    assert sc._est_saturation(requests.Timeout())
    assert sc._est_saturation(requests.ConnectionError())


def test_une_exception_sans_reponse_ni_type_connu_n_interrompt_pas():
    """Prudence dans le bon sens : on n'interrompt que sur un signal qu'on reconnaît."""
    assert not sc._est_saturation(requests.RequestException())


def test_le_seuil_laisse_passer_un_incident_isole():
    """Un 503 isolé arrive. Abandonner au premier rendrait la collecte inutilement fragile ;
    c'est une SÉRIE qui prouve que le serveur est en difficulté.
    """
    assert sc.MAX_ECHECS_SERVEUR >= 2


# ── Ne pas redemander ce qu'on a déjà ───────────────────────────────────────────────────
# Mesuré le 2026-09-03 : la synchro re-téléchargeait chaque jour les 20 tournois les plus
# récents — 1 listing + 20 pages + 320 decklists = 341 requêtes — alors que les 20 étaient
# déjà complets localement. Environ 340 requêtes quotidiennes pour rien.

import json
from datetime import date, timedelta


def _pack(racine, slug, tid, n_decks=16, n_avec_texte=16):
    d = racine / slug
    d.mkdir(parents=True)
    (d / "deckpack.json").write_text(json.dumps({
        "schema_version": 1,
        "name": slug,
        "author": "chinoizecup-scraper",
        "description": f"Top 16 … Source tournament: https://chinoizecupstats.com/tournaments/{tid}",
        "decks": [{"name": f"A — J{i} ({i + 1})", "tags": ["meta"],
                   **({"text": "1xOP17-001\n4xOP17-020"} if i < n_avec_texte else {})}
                  for i in range(n_decks)],
    }), encoding="utf-8")


def _slug_age(jours):
    return (date.today() - timedelta(days=jours)).isoformat()


def test_un_tournoi_complet_et_ancien_ne_sera_plus_redemande(tmp_path):
    _pack(tmp_path, f"{_slug_age(30)}-chinoizecup-1", "a" * 24)
    assert sc.indexer_deja_collectes(tmp_path) == {"a" * 24: True}


def test_un_tournoi_recent_reste_redemande(tmp_path):
    """Les decklists arrivent parfois en retard sur la source : rejouer un tournoi frais
    pendant quelques jours rattrape ces ajouts. Sauter tout de suite les perdrait.
    """
    _pack(tmp_path, f"{_slug_age(1)}-chinoizecup-2", "b" * 24)
    assert sc.indexer_deja_collectes(tmp_path) == {"b" * 24: False}


def test_un_pack_incomplet_reste_redemande_quel_que_soit_son_age(tmp_path):
    """Le cas qui compte le plus : un deck sans texte est une collecte ratée, et le saut ne
    doit JAMAIS empêcher de la rattraper — sinon un pack tronqué le reste pour toujours.
    """
    _pack(tmp_path, f"{_slug_age(90)}-chinoizecup-3", "c" * 24, n_decks=16, n_avec_texte=9)
    assert sc.indexer_deja_collectes(tmp_path) == {"c" * 24: False}


def test_un_pack_vide_reste_redemande(tmp_path):
    _pack(tmp_path, f"{_slug_age(90)}-chinoizecup-4", "d" * 24, n_decks=0, n_avec_texte=0)
    assert sc.indexer_deja_collectes(tmp_path) == {"d" * 24: False}


def test_un_tournoi_inconnu_n_est_pas_dans_l_index(tmp_path):
    """Un tournoi jamais vu doit être collecté : l'index ne répond que sur ce qu'il connaît."""
    _pack(tmp_path, f"{_slug_age(30)}-chinoizecup-5", "e" * 24)
    index = sc.indexer_deja_collectes(tmp_path)
    assert not index.get("f" * 24), "un tid inconnu ne doit jamais être considéré comme réglé"


def test_un_pack_sans_date_lisible_compte_comme_regle_s_il_est_complet(tmp_path):
    """Faute de date, « complet » est le seul signal disponible. On s'y tient plutôt que de
    redemander indéfiniment un pack qui n'a rien à gagner.
    """
    _pack(tmp_path, "op14-5-tournoi-sans-prefixe-de-date", "0" * 24)
    assert sc.indexer_deja_collectes(tmp_path) == {"0" * 24: True}


def test_un_manifeste_illisible_n_interrompt_pas_l_indexation(tmp_path):
    """Un JSON cassé ne doit pas faire tomber toute la synchro — au pire il sera recollecté."""
    _pack(tmp_path, f"{_slug_age(30)}-chinoizecup-6", "1" * 24)
    casse = tmp_path / "2026-01-01-casse"
    casse.mkdir()
    (casse / "deckpack.json").write_text("{ pas du json", encoding="utf-8")
    assert sc.indexer_deja_collectes(tmp_path) == {"1" * 24: True}


def test_un_dossier_de_sortie_absent_donne_un_index_vide(tmp_path):
    assert sc.indexer_deja_collectes(tmp_path / "absent") == {}
