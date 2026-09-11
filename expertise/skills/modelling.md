---
id: modelling
title: Modélisation
summary: Créer et organiser la géométrie proprement dans la scène remote.
---

# Modélisation

## Ordre recommandé

1. `initialize_scene` ou `clear_scene` selon le besoin.
2. Créer les primitives (`create_object`) plutôt que du mesh raw en Python au début.
3. Organiser en collections (`create_collection`, lier les objets).
4. Transforms via `modify_object` (location / rotation degrés / scale).

## Conventions

- Collections : `Building`, `Ground`, `Furniture`, `Lights`, `Cameras`.
- Un objet = un rôle ; éviter les « Cube.012 » orphelins — renommer tôt.
- Avant bevel / boolean complexes : préfère une recipe ou un skill workflow ; sinon `execute_python` court et testé.

## Voir aussi

- Recipe `clear_and_studio`
- Skill `materials`, `lighting`
