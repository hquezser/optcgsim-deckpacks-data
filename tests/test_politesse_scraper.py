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
