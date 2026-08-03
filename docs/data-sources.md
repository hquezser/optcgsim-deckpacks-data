# Sources de decklists & scrapers

Ce document liste les sources de decklists connues, comment le format `deckpack` les
accueille, et le **contrat que tout scraper doit respecter** pour produire des packs
valides. Le format lui-même est défini dans le repo sibling `optcgsim-deckpacks` (spec +
schéma + validateur) — voir `../optcgsim-deckpacks/SPEC-deckpack.md`.

## Architecture

```
optcgsim-deckpacks            (sibling — spec du format)
├── SPEC-deckpack.md          ← contrat du format
├── schema/deckpack.schema.json
├── scripts/validate.py       ← arbitre : un pack est valide ou non
└── packs/example-op16/       ← exemple de référence

optcgsim-deckpacks-data       (CE dépôt — production de packs)
├── scripts/scrape_limitless.py   ← scraper de référence (template)
├── docs/data-sources.md          ← CE fichier (catalogue + contrat)
├── docs/EXTENDING.md             ← guide d'ajout d'un scraper
└── packs/<date-slug>/            ← packs scrapés, validés par le validateur ci-dessus
```

**Séparation** : le repo spec dit *ce qu'est* un pack valide ; ce dépôt dit *comment produire*
des packs à partir du web. Un scraper n'est jamais accepté dans `optcgsim-deckpacks`.

## Sources connues

| Source | URL | Statut | Scraper | Notes |
|---|---|---|---|---|
| Limitless TCG (OP) | `onepiece.limitlesstcg.com/decks/lists` | ✅ scraper de référence | `scripts/scrape_limitless.py` | Top N par tournoi ; HTML statique ; IDs Bandai directement exploitables. ToS à respecter (voir ci-dessous). |
| ChinoizeCupStats | `chinoizecupstats.com/tournaments` | ✅ scraper | `scripts/scrape_chinoizecup.py` | Tournois online ChinoizeCup (jusqu'à 100 events). Next.js SSR : listing de cartes `<a href="/tournaments/{id}">`, page tournoi = JSON-LD `SportsEvent` (name, startDate) + table de standings (Place/Player/Leader/Record) avec liens `/decklists/{tid}/{player}`. Fiche decklist = images cartes (`..._EN.webp` → ID Bandai) + comptes `× N` ; leader = 1ère image hors `div.relative.group`. Pas de filtre region/time (cup online unique). `format_tag` générique `op` (le site n'expose pas la version de format par event). |
| Saisie manuelle | — | ✅ | — | Pour un pack perso/rogue : écrire `deckpack.json` à la main (voir [docs/EXTENDING.md § Importer sans scraper](EXTENDING.md)). |
| Autres agrégateurs | — | ⏳ à ajouter | — | Tout nouveau scraper va ici. Ouvrir une PR dans CE dépôt. |

## Comment le format accueille chaque source

Trois modes de `decks[].source` (exactement un par deck) couvrent tous les cas — voir
`../optcgsim-deckpacks/SPEC-deckpack.md` pour la spec complète :

- **`text`** — decklist inline au format natif. **Mode par défaut pour tout pack scrapé** :
  le scraper extrait IDs + quantités et les inline. Avantages : reproductible hors-ligne,
  validation CI possible sans réseau, pas de lien mort dans 6 mois.
- **`file`** — chemin relatif vers un `.txt` dans le pack. Utile pour de grosses decklists
  ou quand on veut les éditer séparément.
- **`source_url`** — URL résolue par le studio à l'import (best-effort). Utile quand le
  scrape est fragile ou interdit par les ToS : on pointe vers la fiche et le studio fait
  la résolution au moment de l'import. **Pas validé par `validate.py`** (zéro réseau).

## Contrat que tout scraper doit respecter

Un scraper est acceptable s'il produit, pour un dossier `packs/<slug>/`, un
`deckpack.json` qui :

1. **Passe `python3 ../optcgsim-deckpacks/scripts/validate.py packs/<slug>`** — c'est
   l'arbitre unique. Pas de validation = pas de merge.
2. **N'extrait que des données factuelles** : IDs de cartes, quantités, méta publique
   (nom du tournoi, date, placement, joueur, archetype). **Aucun texte de carte, aucune
   image, aucun asset** — le dépôt est public et ne doit contenir aucun contenu sous
   copyright Bandai/Shueisha/Toei.
3. **Inline les decklists en `text`** (mode préféré) sauf raison valable d'utiliser
   `source_url`. Le format natif est `1x<leader>\n4x<card>\n…`, leader en premier.
4. **Cite la source dans `description`** : URL de la page liste, filtres utilisés
   (région, période, type), date du run.
5. **Est poli** : User-Agent identifié, délai entre requêtes (`--delay`, défaut ~0.5s),
  cache par URL de fiche au sein d'un run (une même decklist peut être partagée par
  plusieurs joueurs).
6. **Respecte les ToS de la source**. Vérifier les conditions d'utilisation avant tout
  scrape en masse destiné à un dépôt public. En cas de doute, préférer le mode
  `source_url` (le studio résout à l'import) plutôt que d'inline du contenu scrapé.

## Ajouter un nouveau scraper

Voir [docs/EXTENDING.md](EXTENDING.md) pour le guide concret (structure du script,
parsing, émission du pack, tests). Le scraper Limitless (`scripts/scrape_limitless.py`)
sert de template.

## Ajouter une nouvelle source au catalogue

Pour ajouter une ligne au tableau « Sources connues » ci-dessus, ouvrir une PR dans CE
dépôt avec :

- le nom de la source + URL ;
- le statut (scraper existant / prévu / non autorisé) ;
- un scraper fonctionnel sous `scripts/` si la source est scrapable et que ses ToS
  l'autorisent ;
- une note sur les particularités (HTML statique vs JS-rendered, IDs Bandai directement
  exploitables ou non, etc.).
