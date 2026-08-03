# Étendre : ajouter un scraper, importer d'autres decks

Ce dépôt (`optcgsim-deckpacks-data`) héberge les scrapers et les packs scrapés. Le format
auquel les packs doivent se conformer est défini dans le repo sibling
`optcgsim-deckpacks` (spec + schéma + validateur). **L'arbitre unique de la validité d'un
pack est `../optcgsim-deckpacks/scripts/validate.py`** — tout scraper doit produire des
packs qui passent ce validateur.

## Contrat (rappel)

Tout scraper ajouté ici doit :

1. Produire `packs/<slug>/deckpack.json` valide selon
   `../optcgsim-deckpacks/scripts/validate.py`.
2. N'extraire que des IDs + quantités + méta publique. **Aucun texte/image/asset** (copyright
   Bandai/Shueisha/Toei).
3. Inline les decklists en `text` (format natif `1x<leader>\n4x<card>\n…`, leader en premier).
4. Citer la source dans `description` (URL, filtres, date du run).
5. Être poli réseau : User-Agent identifié, `--delay` entre requêtes, cache par URL de fiche.
6. Respecter les ToS de la source. En cas de doute, préférer `source_url` (résolution studio)
   plutôt qu'inline du contenu scrapé.

Voir aussi [docs/data-sources.md](data-sources.md) pour le catalogue des sources.

## Template : le scraper Limitless

`scripts/scrape_limitless.py` est la référence. Structure à imiter pour tout nouveau scraper :

```
scripts/scrape_<source>.py
├── constants (BASE, USER_AGENT, REGION_MAP…)
├── @dataclass DeckRow / Tournament / Decklist
├── parse_<source>_listing(html) -> list[Tournament]   # page liste → blocs tournoi
├── parse_<source>_decklist(html) -> Decklist | None    # fiche deck → (count, id)[]
├── fetch_decklist(session, url, cache)                 # cache par URL
├── build_deckpack(t, top, ...) -> dict                 # émet le manifeste
├── decklist_to_text(dl) -> str                         # 1x<leader>\n4x<card>\n…
└── main(argv) avec argparse (--region/--time/--top/--output/--delay/…)
```

Points-clés du template à reproduire :

- **Cache par URL de fiche** (`cache: dict[str, Decklist | None]`) : une même decklist peut
  être partagée par plusieurs joueurs d'un même top 16 — on ne la re-fetch pas.
- **`--delay`** (défaut 0.5s) entre chaque requête, User-Agent identifié.
- **Slug date-prefixed** : `<YYYY-MM-DD>-<slugify(name)>` pour un tri chronologique naturel.
- **Tags** : `["meta", <region>, <format_tag>.lower(), <year>]` — cohérents avec ce que le
  studio attend pour filtrer.
- **Drop des decks non fetchés** : si une fiche échoue, on la retire du pack plutôt que
  d'écrire un deck sans `text` (un deck sans source est invalide selon le schéma).
- **`description`** cite l'URL de la page liste + les filtres + l'URL du tournoi source.

## Ajouter un nouveau scraper : pas-à-pas

1. **Vérifier les ToS** de la source cible avant tout. Si le scrape en masse est interdit,
   ne pas écrire de scraper — utiliser `source_url` dans un pack manuel (le studio résout
   à l'import).
2. **Inspecter le HTML brut** de la page liste et d'une fiche deck (curl + grep sur les
   classes/attributs pertinents). Ne pas se fier au rendu webfetch qui dénature le DOM.
3. **Identifier les sélecteurs** :
   - page liste : conteneur des blocs tournoi + lignes de decks (placement, archetype,
     joueur, URL de fiche) ;
   - fiche deck : conteneur des cartes avec quantité + ID Bandai (ex. Limitless expose
     `data-count` et `data-id` sur `div.decklist-card`).
4. **Copier `scrape_limitless.py`** comme squelette, renommer, adapter les fonctions de
   parsing. Garder la structure (dataclasses, cache, argparse, `--delay`).
5. **Tester sur un sous-ensemble** : `--limit-tournaments 1 --top 4 --output /tmp/test`.
6. **Valider la sortie** :
   ```bash
   python3 ../optcgsim-deckpacks/scripts/validate.py /tmp/test/*
   ```
   Si ça ne passe pas, le scraper est en tort — corriger le scraper, pas le validateur.
7. **Run complet** + valider tous les packs générés.
8. **Documenter la source** dans [docs/data-sources.md](data-sources.md) (tableau des
   sources connues) — c'est le catalogue commun, dans ce dépôt.

## Importer des decks sans scraper

Pour un petit lot (deck perso, rogue, import manuel depuis un forum), pas besoin de scraper :
créer directement un `deckpack.json` à la main dans ce dépôt sous `packs/<mon-pack>/`. Pour
le format des champs et le format natif OPTCGSim (`1x<leader>\n4x<card>\n…`), voir
`../optcgsim-deckpacks/SPEC-deckpack.md`. Valider avec :

```bash
python3 ../optcgsim-deckpacks/scripts/validate.py packs/<mon-pack>
```

## Dépendances

`requirements.txt` : `requests` + `beautifulsoup4`. Pas de dépendance au-delà — pas de
playwright/selenium sauf si la source est rendue en JS (alors documenter pourquoi et isoler
dans un scraper séparé pour ne pas alourdir le commun).

## Ne pas faire

- Ne pas modifier `../optcgsim-deckpacks/scripts/validate.py` pour faire passer un pack
  invalide — le validateur est l'arbitre, c'est le scraper qui s'adapte.
- Ne pas committer d'images, de textes de cartes, ou d'assets — uniquement IDs + méta.
- Ne pas pousser de packs scrapés vers `optcgsim-deckpacks` (la spec) — ils restent ici.
- Ne pas ajouter de logique d'import/résolution de cartes ici — c'est le rôle du studio.
