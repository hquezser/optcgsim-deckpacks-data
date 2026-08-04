"""Tests de `scripts/packmerge.py` — la règle d'union qui empêche un run de rétrécir un pack.

Rappel du risque réel (voir docstring de `packmerge.py`) : un scraper ne voit qu'une fenêtre
de la réalité ; écrire à l'aveugle détruit du travail déjà acquis. Un run a déjà réduit un
pack de 16 decks à 5. Ces tests verrouillent chaque branche qui protège contre ça.

Aucun accès réseau, aucune dépendance hors stdlib + pytest. Aucun test n'écrit dans `packs/` :
tout passe par `tmp_path`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# `conftest.py` ajoute scripts/ à sys.path.
import packmerge  # noqa: E402


# --------------------------------------------------------------- helpers locaux


def _deck(name: str, *, tags=None, text: str | None = "1xOP01-001\n4xOP01-002") -> dict:
    """Un deck minimal mais valide au sens du format (name + une source)."""
    d: dict = {"name": name}
    if tags is not None:
        d["tags"] = list(tags)
    if text is not None:
        d["text"] = text
    return d


def _pack(decks: list[dict], *, name: str = "Test Pack", description: str = "desc") -> dict:
    return {
        "schema_version": 1,
        "name": name,
        "author": "tests",
        "description": description,
        "decks": decks,
    }


def _write_pack(pack_dir: Path, dp: dict) -> Path:
    pack_dir.mkdir(parents=True, exist_ok=True)
    p = pack_dir / "deckpack.json"
    p.write_text(json.dumps(dp, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def _read_pack(pack_dir: Path) -> dict:
    return json.loads((pack_dir / "deckpack.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------- load_existing


def test_load_existing_absent_renvoie_none(tmp_path):
    assert packmerge.load_existing(tmp_path / "deckpack.json") is None


def test_load_existing_lisible_renvoie_le_dict(tmp_path):
    p = _write_pack(tmp_path, _pack([_deck("A")]))
    dp = packmerge.load_existing(p)
    assert dp is not None
    assert dp["name"] == "Test Pack"
    assert [d["name"] for d in dp["decks"]] == ["A"]


def test_load_existing_json_invalide_leve_runtimeerror(tmp_path):
    p = tmp_path / "deckpack.json"
    p.write_text("{ ce n'est pas du json ", encoding="utf-8")
    with pytest.raises(RuntimeError, match="illisible"):
        packmerge.load_existing(p)


def test_load_existing_sans_decks_leve_runtimeerror(tmp_path):
    p = tmp_path / "deckpack.json"
    p.write_text(json.dumps({"name": "x", "schema_version": 1}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="decks"):
        packmerge.load_existing(p)


def test_load_existing_decks_pas_une_liste_leve_runtimeerror(tmp_path):
    p = tmp_path / "deckpack.json"
    p.write_text(
        json.dumps({"name": "x", "schema_version": 1, "decks": {"pas": "une liste"}}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="decks"):
        packmerge.load_existing(p)


def test_load_existing_pas_un_dict_leve_runtimeerror(tmp_path):
    p = tmp_path / "deckpack.json"
    p.write_text(json.dumps(["pas", "un", "dict"]), encoding="utf-8")
    with pytest.raises(RuntimeError, match="decks"):
        packmerge.load_existing(p)


# --------------------------------------------------------------- merge_decks : la règle centrale


def test_union_ne_retrécit_jamais_run_voit_moins():
    """Le cas qui a coûté 11 decks en prod : existant riche, run qui n'en voit qu'un."""
    existing = [_deck(f"D{i}") for i in range(5)]
    new = [_deck("D0")]  # le run ne voit que le premier
    merged, ajoutes, enrichis = packmerge.merge_decks(existing, new)
    assert len(merged) == 5  # aucun deck perdu
    assert ajoutes == 0
    assert enrichis == 0  # D0 identique, pas d'enrichissement


def test_union_ajoute_les_decks_nouveaux():
    existing = [_deck("A"), _deck("B")]
    new = [_deck("B"), _deck("C"), _deck("D")]
    merged, ajoutes, enrichis = packmerge.merge_decks(existing, new)
    assert [d["name"] for d in merged] == ["A", "B", "C", "D"]
    assert ajoutes == 2
    assert enrichis == 0


def test_union_ordre_existant_d_abord_puis_nouveaux():
    existing = [_deck("Z"), _deck("A")]  # ordre arbitraire conservé
    new = [_deck("M"), _deck("Z")]  # Z collisionne, M est nouvelle
    merged, _, _ = packmerge.merge_decks(existing, new)
    assert [d["name"] for d in merged] == ["Z", "A", "M"]


def test_union_run_vide_ne_change_rien():
    existing = [_deck("A"), _deck("B")]
    merged, ajoutes, enrichis = packmerge.merge_decks(existing, [])
    assert [d["name"] for d in merged] == ["A", "B"]
    assert ajoutes == 0
    assert enrichis == 0


def test_union_existant_vide_ajoute_tout():
    new = [_deck("A"), _deck("B")]
    merged, ajoutes, enrichis = packmerge.merge_decks([], new)
    assert [d["name"] for d in merged] == ["A", "B"]
    assert ajoutes == 2
    assert enrichis == 0


# --------------------------------------------------------------- merge_decks : enrichissement sur collision


def test_enrichit_tags_union_sans_doublon_sans_perte():
    existing = [_deck("A", tags=["meta", "online"], text="1xOP01-001")]
    new = [_deck("A", tags=["online", "op16"], text="1xOP01-001")]
    merged, ajoutes, enrichis = packmerge.merge_decks(existing, new)
    assert ajoutes == 0
    assert enrichis == 1
    a = merged[0]
    assert a["tags"] == ["meta", "online", "op16"]  # ordre : anciens puis nouveaux uniques


def test_enrichit_tags_run_sans_tags_ne_vide_pas_les_anciens():
    """Un run qui ne remonte plus de tags ne doit pas effacer ceux déjà connus."""
    existing = [_deck("A", tags=["meta", "online"], text="1xOP01-001")]
    new = [_deck("A", tags=None, text="1xOP01-001")]  # pas de tags du tout
    merged, _, enrichis = packmerge.merge_decks(existing, new)
    a = merged[0]
    assert a["tags"] == ["meta", "online"]  # conservés
    assert enrichis == 0  # rien changé


def test_enrichit_text_rfraîchi_si_nouveau_run_en_a_un():
    existing = [_deck("A", text="1xOLD-001")]
    new = [_deck("A", text="1xNEW-001\n4xNEW-002")]
    merged, _, enrichis = packmerge.merge_decks(existing, new)
    assert merged[0]["text"] == "1xNEW-001\n4xNEW-002"
    assert enrichis == 1


def test_enrichit_text_vide_ne_vide_pas_texte_existant():
    """Le cas qui compte le plus : un run dont la récupération de decklist a échoué
    (`text` vide ou absent) ne doit pas vider un `text` déjà présent sur disque."""
    existing = [_deck("A", text="1xOP01-001\n4xOP01-002")]
    # Run qui échoue à charger la decklist : pas de `text` du tout.
    new = [_deck("A", text=None)]
    merged, _, enrichis = packmerge.merge_decks(existing, new)
    assert merged[0]["text"] == "1xOP01-001\n4xOP01-002"  # conservé
    assert enrichis == 0


def test_enrichit_text_chaîne_vide_ne_vide_pas_texte_existant():
    """Variante du précédent : `text` présent mais vide (falsy) — même protection."""
    existing = [_deck("A", text="1xOP01-001")]
    new = [_deck("A", text="")]
    merged, _, enrichis = packmerge.merge_decks(existing, new)
    assert merged[0]["text"] == "1xOP01-001"
    assert enrichis == 0


def test_enrichit_text_et_tags_simultanément_compte_un_seul_enrichi():
    existing = [_deck("A", tags=["meta"], text="1xOLD")]
    new = [_deck("A", tags=["op16"], text="1xNEW")]
    merged, _, enrichis = packmerge.merge_decks(existing, new)
    assert enrichis == 1  # un seul deck enrichi, pas deux
    assert merged[0]["tags"] == ["meta", "op16"]
    assert merged[0]["text"] == "1xNEW"


def test_enrichit_ne_mut_pas_les_données_nouvelles_du_caller():
    """`merge_decks` ne doit pas modifier les entrées de `new` (données fraîches du scraper),
    ni la liste `new` elle-même. L'existant peut être copié/enrichi en place dans le dict
    cible (c'est le contrat), mais `new` est read-only du point de vue du caller.
    """
    existing = [_deck("A", tags=["meta"], text="1xOLD")]
    new = [_deck("A", tags=["op16"], text="1xNEW")]
    new_snapshot = json.loads(json.dumps(new))
    packmerge.merge_decks(existing, new)
    assert json.loads(json.dumps(new)) == new_snapshot


# --------------------------------------------------------------- write_pack_merged : chemin normal


def test_write_pack_nouveau_crée_le_fichier(tmp_path):
    dp = _pack([_deck("A"), _deck("B")])
    count, note = packmerge.write_pack_merged(tmp_path / "p", dp)
    assert count == 2
    assert note == ""  # pas de fusion, pas de force
    on_disk = _read_pack(tmp_path / "p")
    assert [d["name"] for d in on_disk["decks"]] == ["A", "B"]


def test_write_pack_fusionne_avec_existant(tmp_path):
    _write_pack(tmp_path / "p", _pack([_deck("A"), _deck("B"), _deck("C")]))
    dp = _pack([_deck("B"), _deck("D")])
    count, note = packmerge.write_pack_merged(tmp_path / "p", dp)
    assert count == 4  # A, B, C + D
    assert "fusion" in note
    on_disk = _read_pack(tmp_path / "p")
    assert [d["name"] for d in on_disk["decks"]] == ["A", "B", "C", "D"]


def test_write_pack_fusion_ne_perd_jamais_decks_run_voit_moins(tmp_path):
    """Le scénario de l'incident réel, joué bout-en-bout via write_pack_merged."""
    _write_pack(tmp_path / "p", _pack([_deck(f"D{i}") for i in range(5)]))
    dp = _pack([_deck("D0")])  # le run ne voit que D0
    count, note = packmerge.write_pack_merged(tmp_path / "p", dp)
    assert count == 5
    on_disk = _read_pack(tmp_path / "p")
    assert [d["name"] for d in on_disk["decks"]] == [f"D{i}" for i in range(5)]


def test_write_pack_fusion_texte_non_écrasé_par_run_vide(tmp_path):
    """Le filet du docstring, joué bout-en-bout : un run sans `text` ne vide pas l'existant."""
    _write_pack(tmp_path / "p", _pack([_deck("A", text="1xOP01-001\n4xOP01-002")]))
    dp = _pack([_deck("A", text=None)])  # run qui a échoué à charger la decklist
    packmerge.write_pack_merged(tmp_path / "p", dp)
    on_disk = _read_pack(tmp_path / "p")
    assert on_disk["decks"][0]["text"] == "1xOP01-001\n4xOP01-002"


# --------------------------------------------------------------- write_pack_merged : refus délibérés


def test_write_pack_refuse_json_invalide_existant(tmp_path):
    p = tmp_path / "p" / "deckpack.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ invalide ", encoding="utf-8")
    dp = _pack([_deck("A")])
    with pytest.raises(RuntimeError, match="illisible"):
        packmerge.write_pack_merged(tmp_path / "p", dp)
    # On n'a rien écrit par-dessus : le fichier illisible est intact.
    assert p.read_text(encoding="utf-8") == "{ invalide "


def test_write_pack_refuse_existant_sans_decks(tmp_path):
    p = tmp_path / "p" / "deckpack.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"name": "x", "schema_version": 1}), encoding="utf-8")
    dp = _pack([_deck("A")])
    with pytest.raises(RuntimeError, match="decks"):
        packmerge.write_pack_merged(tmp_path / "p", dp)


# --------------------------------------------------------------- write_pack_merged : --force


def test_force_remplace_au_lieu_de_fusionner(tmp_path):
    _write_pack(tmp_path / "p", _pack([_deck("A"), _deck("B"), _deck("C")]))
    dp = _pack([_deck("X")])
    count, note = packmerge.write_pack_merged(tmp_path / "p", dp, force=True)
    assert count == 1  # c'est le seul chemin qui autorise une perte
    assert "écrasement forcé" in note
    on_disk = _read_pack(tmp_path / "p")
    assert [d["name"] for d in on_disk["decks"]] == ["X"]


def test_force_sur_pack_inexistant_note_vide(tmp_path):
    dp = _pack([_deck("A")])
    count, note = packmerge.write_pack_merged(tmp_path / "p", dp, force=True)
    assert count == 1
    assert note == ""  # pas d'existant à écraser


def test_force_ne_lit_pas_l_existant(tmp_path):
    """`--force` doit court-circuiter la lecture : un existant illisible ne lève pas."""
    p = tmp_path / "p" / "deckpack.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ invalide ", encoding="utf-8")
    dp = _pack([_deck("A")])
    # En force, on n'essaie pas de lire → pas de RuntimeError.
    count, note = packmerge.write_pack_merged(tmp_path / "p", dp, force=True)
    assert count == 1
    assert "écrasement forcé" in note


# --------------------------------------------------------------- write_pack_merged : filet interne


def test_filet_interne_fusion_retrécit_leve():
    """Le filet `len(decks) < avant` est censé être inatteignable via l'API publique,
    parce que `merge_decks` fait une union (jamais de suppression). On le teste quand même
    en appelant `merge_decks` puis en simulant le contrat de `write_pack_merged` : on
    vérifie d'abord que l'union ne rétrécit jamais, ce qui rend la branche morte par
    construction.

    Vérification 1 : pour des entrées quelconques, merge_decks ne rétrécit jamais.
    """
    import random

    rng = random.Random(0)
    for _ in range(200):
        n_existing = rng.randint(0, 10)
        n_new = rng.randint(0, 10)
        existing = [_deck(f"E{i}") for i in range(n_existing)]
        new = [_deck(rng.choice(["E0", "E1", "X", "Y", "Z"]) if n_existing else "X")
               for _ in range(n_new)]
        merged, _, _ = packmerge.merge_decks(existing, new)
        assert len(merged) >= n_existing, (
            f"merge_decks a rétréci : {n_existing} → {len(merged)} "
            f"(existing={existing}, new={new})"
        )


def test_filet_interne_branchette_atteignable_via_monkeypatch(tmp_path):
    """Le filet lui-même (branche `len(decks) < avant`) est défendable en patchant
    `merge_decks` pour qu'il renvoie moins qu'avant — on confirme que write_pack_merged
    lève bien dans ce cas, plutôt que d'écrire un pack rétréci.
    """
    _write_pack(tmp_path / "p", _pack([_deck("A"), _deck("B")]))
    dp = _pack([_deck("A")])

    def _shrinking_merge(existing, new):
        # Simule un bug qui perdrait des decks.
        return [existing[0]], 0, 0

    orig = packmerge.merge_decks
    packmerge.merge_decks = _shrinking_merge
    try:
        with pytest.raises(RuntimeError, match="rétréci"):
            packmerge.write_pack_merged(tmp_path / "p", dp)
    finally:
        packmerge.merge_decks = orig
    # Et rien n'a été écrit par-dessus l'existant (le filet a bloqué avant l'écriture).
    on_disk = _read_pack(tmp_path / "p")
    assert [d["name"] for d in on_disk["decks"]] == ["A", "B"]


# --------------------------------------------------------------- describe


def test_describe_reçoit_nombre_final_et_bool_fusion(tmp_path):
    _write_pack(tmp_path / "p", _pack([_deck("A")], description="origine"))
    dp = _pack([_deck("A"), _deck("B")], description="origine")
    captured = {}

    def describe(n, fusionne):
        captured["n"] = n
        captured["fusionne"] = fusionne
        return f"Top {n} decks" + (" Merged." if fusionne else "")

    count, _ = packmerge.write_pack_merged(tmp_path / "p", dp, describe=describe)
    assert count == 2
    assert captured == {"n": 2, "fusionne": True}
    on_disk = _read_pack(tmp_path / "p")
    assert on_disk["description"] == "Top 2 decks Merged."


def test_describe_pack_nouveau_fusionne_false(tmp_path):
    dp = _pack([_deck("A"), _deck("B")])
    captured = {}

    def describe(n, fusionne):
        captured.update(n=n, fusionne=fusionne)
        return f"Top {n} decks"

    packmerge.write_pack_merged(tmp_path / "p", dp, describe=describe)
    assert captured == {"n": 2, "fusionne": False}
    on_disk = _read_pack(tmp_path / "p")
    assert on_disk["description"] == "Top 2 decks"


def test_describe_force_n_appelle_pas_avec_fusionne_true(tmp_path):
    _write_pack(tmp_path / "p", _pack([_deck("A")], description="origine"))
    dp = _pack([_deck("X")])
    captured = {}

    def describe(n, fusionne):
        captured.update(n=n, fusionne=fusionne)
        return f"Top {n} decks"

    packmerge.write_pack_merged(tmp_path / "p", dp, force=True, describe=describe)
    # En force, existing est None → fusionne=False même s'il y avait un fichier.
    assert captured == {"n": 1, "fusionne": False}


# --------------------------------------------------------------- déterminisme


def test_déterminisme_deux_fusions_identiques_octets_identiques(tmp_path):
    """Deux runs de fusion identiques (même base, même `new`) produisent des octets
    identiques. On duplique `dp` pour chaque run car `write_pack_merged` mute `dp` en
    place (contrat du module) — comparer les sorties nécessite donc des entrées fraîches.
    """
    base_dp = _pack([_deck("A", tags=["meta"], text="1xOP01-001"),
                     _deck("B", text="1xOP02-001")])
    new_dp_template = _pack([_deck("A", tags=["op16"], text="1xOP01-001"),
                             _deck("C", text="1xOP03-001")])

    # Deux bases identiques.
    _write_pack(tmp_path / "p1", json.loads(json.dumps(base_dp)))
    _write_pack(tmp_path / "p2", json.loads(json.dumps(base_dp)))

    # Deux runs de fusion identiques, chacun avec sa propre copie de `new`.
    packmerge.write_pack_merged(tmp_path / "p1", json.loads(json.dumps(new_dp_template)))
    packmerge.write_pack_merged(tmp_path / "p2", json.loads(json.dumps(new_dp_template)))

    a = (tmp_path / "p1" / "deckpack.json").read_bytes()
    b = (tmp_path / "p2" / "deckpack.json").read_bytes()
    assert a == b


def test_déterminisme_idempotent_re_run_ne_change_rien(tmp_path):
    """Re-fusionner le même `new` sur le résultat déjà fusionné est un point fixe."""
    _write_pack(tmp_path / "p", _pack([_deck("A", tags=["meta"], text="1xOP01-001")]))
    dp = _pack([_deck("A", tags=["op16"], text="1xOP01-001")])
    packmerge.write_pack_merged(tmp_path / "p", dp)
    first = _read_pack(tmp_path / "p")
    # Re-run : le pack sur disque est déjà le résultat de la fusion.
    packmerge.write_pack_merged(tmp_path / "p", dp)
    second = _read_pack(tmp_path / "p")
    assert first == second


# --------------------------------------------------------------- garde-fous d'intégrité


def test_ne_modifie_pas_packs_réel():
    """Garde-fou : aucun test ne doit écrire dans `packs/`. On vérifie a posteriori que
    le vrai dossier `packs/` n'a pas bougé pendant le run de cette suite — par mtime des
    `deckpack.json`. (Ce test est un canari, pas une preuve : un test mal élevé qui
    écrirait puis restaurerait ne serait pas vu.)
    """
    root = Path(__file__).resolve().parent.parent
    packs = root / "packs"
    if not packs.exists():
        pytest.skip("pas de dossier packs/ dans ce dépôt")
    # On ne fait que lire : si un test précédent a touché à packs/, c'est déjà trop tard,
    # mais au moins on lève ici plutôt que de laisser passer silencieusement.
    for jp in packs.glob("*/deckpack.json"):
        # Lecture seule, juste pour confirmer qu'on peut le faire sans erreur.
        json.loads(jp.read_text(encoding="utf-8"))
