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

Args principaux : `--region` (eu/na/la/oc/asia/all), `--time` (1months/3months/6months/12months),
`--type` (all/regional/treasure/championship/unofficial/offline/online), `--format` (all/OP16/...),
`--played` (all/leader/...), `--show` (100, max 500), `--top` (16), `--output` (default `packs`),
`--delay` (0.5s entre requêtes, minimum), `--limit-tournaments` (0 = tous, utile pour test),
`--max-pages` (50), `--force`.

Trois pièges du site, détaillés dans [README.md](README.md#--region-all) :

- `region`/`time`/`type` **ignorent silencieusement** toute valeur inconnue et renvoient un
  listing non filtré. Le scraper valide donc localement au lieu d'envoyer n'importe quoi ;
  `as`/`month`/`treasurecup` ne sont pas des valeurs du site (alias tolérés).
- Il n'existe pas d'option `region=all` : `--region all` n'envoie aucun `region`, ce qui est
  plus large que l'union des continents (certains tournois n'ont pas de continent).
- Le listing pagine par **ligne de deck**, pas par tournoi. Un tournoi à cheval sur deux pages
  n'expose qu'une partie de ses lignes sur chacune ; il faut parcourir `?page=N` et fusionner
  par URL de tournoi, sinon les tournois sont tronqués sans le moindre signal.

Écriture non destructive : un run fusionne avec le pack existant (clé = nom de deck), donc un
pack ne perd jamais de decks. `--force` pour remplacer (destructif).

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
