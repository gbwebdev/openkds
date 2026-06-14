# OpenKDS — Instructions pour Claude Code

## Git

- **Ne jamais pousser directement sur `main`** — main est protégé.
- Tout changement passe par une branche feature/fix et une Pull Request.
- Nommage des branches : `feat/<sujet>`, `fix/<sujet>`, `docs/<sujet>`, `chore/<sujet>`.
- Créer la PR immédiatement après le push de la branche (ne pas attendre).
- Quand une PR dépend d'une autre branche non encore mergée, la cibler comme base.
- Toujours mettre à jour le README dans le même commit/branche quand l'architecture ou la configuration change.
- Messages de commit en anglais, format Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`).

## Architecture

- **`menu.yaml`** — source de vérité pour le menu, les ateliers, les imprimantes et la config grillade.
  Fichier par défaut dans `openkds/defaults/menu.yaml` ; surcharge possible dans `OPENKDS_DATA_DIR/menu.yaml`.
- **`config.json`** — paramètres runtime (devices imprimantes, couleurs, org_name, next_order_number…).
  Modifiable via l'UI. Ne pas y mettre de config structurelle (menu, ateliers).
- **Templates tickets** — Jinja2 en texte plain avec directives `[center]`, `[big]`, `[cut]`, etc.
  Défauts dans `openkds/default_templates/` ; surcharge dans `OPENKDS_DATA_DIR/templates/`.
- **`OPENKDS_DATA_DIR`** — variable d'environnement qui pointe vers le répertoire de données runtime
  (config.json, openkds.db, overrides menu.yaml et templates). Défaut : répertoire courant.

## Base de données

- Changement de menu ou d'ateliers = reset DB obligatoire (schéma lié aux IDs des items).
- Pas de migrations : reset propre assumé et documenté.

## Imprimantes

- Les imprimantes sont déclarées dans `menu.yaml` sous `printers:` avec un identifiant nommé.
- Les ateliers référencent les imprimantes par cet ID (string), jamais par un numéro.
- Les chemins de devices sont dans `config.json` sous `printer_devices: {id: path}`.
- Ajouter une imprimante = modifier `menu.yaml` uniquement, aucun changement de code.

## Python

- `from __future__ import annotations` en tête de tous les nouveaux fichiers Python
  (le projet tourne sur Python 3.9, la syntaxe `X | Y` n'est pas supportée nativement).
- Dépendances dans `pyproject.toml` uniquement (plus de `requirements.txt`).

## Frontend

- SPA vanilla JS, pas de framework, pas de build step.
- Les listes dynamiques (imprimantes, items du menu, couleurs…) sont générées depuis les APIs,
  jamais codées en dur dans le HTML.

## README

- Mettre à jour le README dans le même commit que tout changement d'architecture,
  de configuration ou d'API publique.
