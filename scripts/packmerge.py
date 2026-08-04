"""Écriture d'un deckpack sans jamais perdre de decks déjà sur disque.

Un scraper ne voit qu'une fenêtre de la réalité : un filtre différent, une pagination
tronquée ou un site momentanément incomplet renvoient moins de decks qu'un run précédent.
Écrire à l'aveugle détruit alors du travail. C'est arrivé en usage réel : un run a réduit
un pack de 16 decks à 5.

La règle est donc l'**union**, pas le remplacement. La clé est le nom de deck
(`<archétype> — <joueur> (<placement>)`), stable d'un run à l'autre pour un tournoi donné.

Module partagé pour que la règle n'existe qu'en un endroit — le README de ce dépôt note
déjà qu'une même règle en trois copies dérive.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["load_existing", "merge_decks", "write_pack_merged"]


def load_existing(path: Path) -> dict | None:
    """Le pack déjà sur disque, ou None s'il n'y en a pas.

    Lève si le fichier existe mais est incompréhensible : refuser d'écrire est le seul geste
    sûr, puisqu'on ne peut pas savoir ce qu'on détruirait.
    """
    if not path.exists():
        return None
    try:
        dp = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"pack existant illisible : {e}") from e
    if not isinstance(dp, dict) or not isinstance(dp.get("decks"), list):
        raise RuntimeError("le pack existant n'a pas de liste « decks »")
    return dp


def merge_decks(existing: list[dict], new: list[dict]) -> tuple[list[dict], int, int]:
    """Union de l'existant et du fraîchement scrapé, clé = nom de deck.

    Sur collision de nom, on garde l'entrée existante et on l'enrichit seulement : union des
    tags, et rafraîchissement du `text` si le nouveau run en a effectivement récupéré un.
    Un run qui échoue à charger une decklist ne peut donc pas vider celle déjà en place.

    Renvoie (decks fusionnés, ajoutés, enrichis).
    """
    par_nom: dict[str, dict] = {d.get("name", ""): dict(d) for d in existing}
    ordre = [d.get("name", "") for d in existing]
    ajoutes = enrichis = 0

    for d in new:
        nom = d.get("name", "")
        if nom not in par_nom:
            par_nom[nom] = dict(d)
            ordre.append(nom)
            ajoutes += 1
            continue
        cible = par_nom[nom]
        avant = (tuple(cible.get("tags") or ()), cible.get("text"))
        tags = list(cible.get("tags") or ())
        for t in d.get("tags") or ():
            if t not in tags:
                tags.append(t)
        if tags:
            cible["tags"] = tags
        if d.get("text"):
            cible["text"] = d["text"]
        if (tuple(cible.get("tags") or ()), cible.get("text")) != avant:
            enrichis += 1

    return [par_nom[n] for n in ordre], ajoutes, enrichis


def write_pack_merged(pack_dir: Path, dp: dict, *, force: bool = False,
                      describe=None) -> tuple[int, str]:
    """Écrit `pack_dir/deckpack.json` en fusionnant avec l'existant.

    `describe(nb_decks, fusionne)` (optionnel) recalcule la description, qui mentionne
    généralement un décompte devenu faux après fusion.

    Renvoie (nombre de decks écrits, note lisible).
    """
    path = pack_dir / "deckpack.json"
    existing = None if force else load_existing(path)

    if existing is None:
        note = "écrasement forcé" if force and path.exists() else ""
    else:
        avant = len(existing["decks"])
        decks, ajoutes, enrichis = merge_decks(existing["decks"], dp["decks"])
        dp["decks"] = decks
        note = f"fusion : {avant} existant(s) + {ajoutes} nouveau(x)"
        if enrichis:
            note += f", {enrichis} enrichi(s)"
        # L'union ne peut pas rétrécir : si ça arrive, c'est un bug ici et il vaut mieux
        # échouer que perdre des decks en silence.
        if len(decks) < avant:
            raise RuntimeError(
                f"refus d'écrire : la fusion a rétréci le pack {avant} → {len(decks)}")

    if describe is not None:
        dp["description"] = describe(len(dp["decks"]), existing is not None)

    pack_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dp, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(dp["decks"]), note
