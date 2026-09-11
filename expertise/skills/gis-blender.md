---
id: gis-blender
title: GIS → Blender (maquette urbaine)
summary: Du référentiel (GeoJSON/BD TOPO) à une maquette LOD1/2 via GN et materials.
---

# GIS dans Blender (amorce)

Profil **métier** qui compose les écrans opérateur :

- `skill://geometry-nodes` + `gn_run_template` (futur `urban_lod1_*`)
- `skill://materials` + `mat_apply_preset` (façade / toiture / sol)

## Intention

Reconstruire un lieu depuis des données référentielles pour validation expert
(esprit maquette **LOD1 → LOD2**). Ce n’est pas un remplacement de QGIS.

## Contrat attributs LOD1

Voir spec `docs/superpowers/specs/2026-09-11-gis-urban-lod-design.md`.

Minimal : polygone + `height` (m). Recommandé : `id`, `roof`, `use`.

## Données d’essai

Fixture git : `docs/experiments/gis-urban-lod/fixtures/blocks_lod1.geojson`

## Workflow agent (cible)

1. Lire ce skill + le JOURNAL du track experiments si un essai est en cours.
2. Charger le GeoJSON (fichier `/projects` ou fixture montée).
3. Extruder (baseline script puis template GN promu).
4. Appliquer materials par `use` / `roof`.
5. `get_screenshot` + `get_canvas_url` pour l’expert.

## Ne pas faire

- Improviser 50 nodes GN sans template/recipe une fois qu’ils existent.
- Committer des extraits BD TOPO sous licence non claire.
- Viser LOD3 avant d’avoir LOD1 reproductible.
