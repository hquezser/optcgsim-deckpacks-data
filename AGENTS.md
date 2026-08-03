# optcgsim-deckpacks-data — Guide de développement

## Rôle dans l'écosystème

Dépôt **sibling** de `optcgsim-deckpacks` (la spec du format). Ici on héberge :

- `scripts/scrape_limitless.py` — scraper réutilisable (onepiece.limitlesstcg.com)
- `packs/<date-slug>/deckpack.json` — un pack par tournoi scrapé, top 16 en `text`

Ce dépôt **ne définit pas le format** — il consomme `optcgsim-deckpacks` (schéma + validateur).
Pour valider les packs générés :

```bash
python3 ../optcgsim-deckpacks/scripts/validate.py packs/*
```

## Scraper

```bash
python3 scripts/scrape_limitless.py --region eu --time 3months --top 16
```

Args principaux : `--region` (eu/na/la/oc/as/all), `--time` (month/3months/6months/12months),
`--type` (all/regional/treasurecup/...), `--format` (all/OP16/...), `--played` (all/leader/...),
`--show` (100), `--top` (16), `--output` (default `packs`), `--delay` (0.5s entre requêtes),
`--limit-tournaments` (0 = tous, utile pour test).

## Étendre (ajouter un scraper, importer d'autres sources)

Voir [docs/EXTENDING.md](docs/EXTENDING.md) — le scraper Limitless sert de template. Le
contrat : tout scraper produit des `packs/<slug>/deckpack.json` qui passent
`../optcgsim-deckpacks/scripts/validate.py` (l'arbitre unique, dans le repo spec sibling).
Catalogue des sources connues + contrat scrapers : [docs/data-sources.md](docs/data-sources.md).

## Invariants

- **Zéro contenu copyright** : on n'extrait que des IDs de cartes + quantités + méta publique
  (nom du tournoi, date, placement, joueur, archetype). Aucun texte de carte, aucune image.
- **Cache par URL de fiche** au sein d'un run : la même decklist peut être partagée par
  plusieurs joueurs, on ne la re-fetch pas.
- **Politesse réseau** : `--delay` entre requêtes (défaut 0.5s), User-Agent identifié.
- **Format natif OPTCGSim** : `1x{leader}\n4x{card}\n…` — leader en premier (donné par l'ordre
  du DOM limitless), Don!! non listé (implicite à l'import côté studio).
