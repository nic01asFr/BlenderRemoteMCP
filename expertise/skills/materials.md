---
id: materials
title: Matériaux
summary: Principled BSDF, presets, et pièges de shading sur instance remote.
---

# Matériaux

## Outils

- `set_material` / outils matériaux du catalogue — toujours un objet nommé existant.
- Pour du Principled fin : `execute_python` avec `bpy.data.materials.new` + nodes, puis assignation.

## Règles

- Base Color en linéaire 0–1.
- Roughness : béton ~0.7–0.9, métal peint ~0.3–0.5, verre roughness bas + transmission.
- Un matériau partagé = même `material` sur plusieurs objets (pas de copie inutile).

## Corpus étendu

Les guides détaillés BigLocalApps (`principled_bsdf`, `materials_library`) se portent ici en enrichissant ce skill ou en ajoutant `skills/principled-bsdf.md`.
