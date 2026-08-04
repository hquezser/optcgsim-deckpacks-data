"""Pytest config : rendre `scripts/` importable sans toucher au code de production.

On n'ajoute pas `scripts/` au PYTHONPATH global (effet de bord hors tests) ; on se contente
d'insérer le répertoire `scripts/` en tête de `sys.path` pour les tests de ce dépôt, qui
n'a pas de package installable.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
