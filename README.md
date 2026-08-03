# optcgsim-deckpacks-data

Deckpacks scrapés depuis [onepiece.limitlesstcg.com](https://onepiece.limitlesstcg.com/decks/lists),
au format [`deckpack` v1](https://github.com/hquezser/optcgsim-deckpacks) (spec dans le repo sibling
`optcgsim-deckpacks`). Un pack par tournoi, top 16 inliné en `text` (format natif OPTCGSim).

## Scraper

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# EU, 3 derniers mois, top 16 par tournoi
.venv/bin/python scripts/scrape_limitless.py --region eu --time 3months --top 16

# Autres filtres
.venv/bin/python scripts/scrape_limitless.py --region na --time month --type regional --top 8
```

Args : `--region` (eu/na/la/oc/as/all), `--time` (month/3months/6months/12months),
`--type` (all/regional/treasurecup/...), `--format` (all/OP16/...), `--played`,
`--show` (100), `--top` (16), `--output` (packs), `--delay` (0.5s),
`--limit-tournaments` (0 = tous, utile pour test).

### ChinoizeCupStats

```bash
# Tous les tournois (jusqu'à 100), top 16
.venv/bin/python scripts/scrape_chinoizecup.py --top 16

# Un tournoi précis (ID depuis l'URL /tournaments/{id})
.venv/bin/python scripts/scrape_chinoizecup.py --tournaments 6a43969983fd320299bd4a17 --top 8

# Test rapide
.venv/bin/python scripts/scrape_chinoizecup.py --limit-tournaments 1 --top 4 --output /tmp/test
```

Args : `--top` (16), `--output` (packs), `--delay` (0.5s), `--limit-tournaments` (0 = tous),
`--tournaments` (liste d'IDs pour cibler des tournois précis, skip le listing).

## Valider les packs générés

Le validateur vit dans le repo spec sibling :

```bash
python3 ../optcgsim-deckpacks/scripts/validate.py packs/*
```

## Contenu

- Aucune image, aucun texte de carte — uniquement des IDs de cartes + quantités + méta publique
  (nom du tournoi, date, placement, joueur, archetype).
- Cache par URL de fiche au sein d'un run (une même decklist peut être partagée par plusieurs
  joueurs).
- `--delay` entre requêtes pour rester poli.

## Étendre

- [docs/EXTENDING.md](docs/EXTENDING.md) — guide d'ajout d'un scraper (le scraper Limitless
  sert de template), pas-à-pas, import manuel sans scraper, anti-patterns.
- [docs/data-sources.md](docs/data-sources.md) — catalogue des sources de decklists connues
  + contrat que tout scraper doit respecter.
