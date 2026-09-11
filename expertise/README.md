# Expertise workspace — contrat d’intégration

Ce dossier est la **couche L1–L3** : ce que le client LLM doit lire pour bien
utiliser BlenderRemoteMCP, sans gonfler le catalogue d’outils.

## Ajouter un skill

1. Créer `skills/{id}.md` (id = slug kebab-case, ex. `materials.md` → `skill://materials`).
2. Front-matter optionnel YAML :

```yaml
---
id: materials
title: Matériaux Principled
summary: Assigner et régler des matériaux sans pivoter à tâtons.
---
```

3. Relancer le serveur (chargement au démarrage). Tests : `tests/test_guidance.py`.

## Ajouter une recipe

1. Créer `recipes/{id}.json` (schéma : `id`, `name`, `description`, `tags`, `parameters`, `steps`).
2. Chaque step : `{ "id", "tool", "params"?, "code"?, "description" }`.
   - `tool` = nom d’outil MCP primitif (`setup_studio_lighting`, `execute_python`, …).
   - `code` seulement si `tool` = `execute_python`.
3. Visible via `list_recipes` / `get_recipe` / `run_recipe`.

## Ajouter un prompt MCP

Éditer `prompts/prompts.json` : `name`, `description`, `arguments`, `messages`.

## Personas (L5) et métier (L4)

- Personas : voir `agents/README.md` — ne pas les injecter dans `initialize`.
- Métier (BIM, route, mesh) : voir `integrations/` — compose le runtime, ne le pollue pas.
- Profil **natif** Geometry Nodes : `skill://geometry-nodes`, recipes `gn_*`, contrat `integrations/geometry_nodes.md`.
- Profil **natif** Materials : `skill://materials`, `mat_lib`, tools `mat_*`, contrat `integrations/materials.md`.
