# optcgsim-deckpacks-data

Deckpacks scrapés depuis [onepiece.limitlesstcg.com](https://onepiece.limitlesstcg.com/decks/lists),
au format [`deckpack` v1](https://github.com/hquezser/optcgsim-deckpacks) (spec dans le repo sibling
`optcgsim-deckpacks`). Un pack par tournoi, top 16 inliné en `text` (format natif OPTCGSim).

## Scraper

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# EU, 3 derniers mois, top 16 par tournoi
.venv/bin/python scripts/scrape_limitless.py --region eu --time 3months --top 16

# Toutes régions confondues
.venv/bin/python scripts/scrape_limitless.py --region all --time 6months --top 16

# Autres filtres
.venv/bin/python scripts/scrape_limitless.py --region na --time 1months --type regional --top 8
```

Args : `--region` (eu/na/la/oc/asia/all), `--time` (1months/3months/6months/12months),
`--type` (all/regional/treasure/championship/unofficial/offline/online),
`--format` (all/OP16/...), `--played`, `--show` (100, max 500), `--top` (16),
`--output` (packs), `--delay` (0.5s, minimum 0.5), `--limit-tournaments` (0 = tous, utile
pour test), `--max-pages` (50), `--force`.

Les valeurs de `--region`, `--time` et `--type` sont validées localement : le site **ignore
silencieusement** une valeur inconnue et renvoie alors un listing non filtré, donc une faute
de frappe passerait pour un succès. `as` → `asia`, `month` → `1months` et `treasurecup` →
`treasure` sont acceptés comme alias (avec un avertissement).

### `--region all`

Le `<select name="region">` du site n'a **pas** d'option `all` (ses valeurs sont
`eu`/`na`/`la`/`oc`/`asia`) : `--region all` n'envoie donc aucun paramètre `region`, ce qui
est le listing non filtré. C'est bien exhaustif — et strictement plus large que l'union des
régions, qui rate les tournois sans région (ex. World Finals 2026, renvoyé par `region=jp`
mais par aucun code de continent). Sur `--time 6months` : 32 tournois pour `all`, contre 15
(eu) + 12 (na) + 3 (la) + 1 (oc) + 0 (asia) = 31 pour l'union.

### Pagination

Le listing pagine par **ligne de deck**, pas par tournoi : `--show` plafonne le nombre de
decks par page, donc un tournoi à cheval sur deux pages n'expose qu'une partie de ses lignes
sur chacune. Le scraper parcourt toutes les pages (`?page=N`) et fusionne par URL de tournoi.
Ne lire que la première page tronquait silencieusement les tournois — c'est ce qui faisait
tomber Treasure Cup Utrecht de 16 à 5 decks.

### Écriture non destructive

Un run fusionne avec le pack déjà sur disque (déduplication par nom de deck), donc **un pack
ne peut jamais perdre de decks** : un run partiel, un fetch en échec ou un `--top` plus petit
n'enlèvent rien. Sur un nom de deck déjà présent, les tags sont unionnés et le `text` n'est
remplacé que si le nouveau run en a effectivement récupéré un. Un pack existant illisible fait
échouer ce tournoi (code de sortie 1) plutôt que d'être écrasé. `--force` remplace le pack au
lieu de fusionner — destructif, à n'utiliser que pour repartir de zéro.

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
