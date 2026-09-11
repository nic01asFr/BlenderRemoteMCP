# Design — Profil Materials / Texturing (natif)

**Date :** 2026-09-11  
**Branche :** `feature/blender-materials` (depuis geometry-nodes)  
**Statut :** implémentation

## Objectif

Presets matériaux professionnels, versionnés, pilotables par le LLM —
même pattern que `gn_lib` : peu d’outils MCP, beaucoup de qualité dans la lib.

## Sources

- Introspection Blender **4.0.2** : Principled BSDF (Base Color, Metallic,
  Roughness, Transmission Weight, Coat, Sheen, Emission…).
- Pas de dépendance à des fichiers PBR externes en v1 (procédural Noise/Bump).
- Skill existant `skill://materials` enrichi ; tools MCP déjà présents
  (`create_material`, `apply_material`) restent pour le bas niveau.

## Architecture

```
docker/blender-canvas/mat_lib/
  registry.py      # metadata presets (testable sans bpy)
  builders.py      # création node trees
  __init__.py      # list_presets / apply / create
MCP: mat_list_presets, mat_apply_preset
expertise/skills/materials.md  # guide agent
recipes/mat_studio_presets.json
```

## Presets v1

| id | Intention |
|----|-----------|
| `concrete` | Archviz béton |
| `brushed_metal` | Métal satiné |
| `glass_clear` | Verre (Transmission Weight) |
| `plastic_soft` | Produit / studio |
| `terrain_grass` | Sol / paysage |
| `rubber_matte` | Caoutchouc mat |

## Non-goals v1

- Bibliothèque d’images HDR/PBR packagée
- UDIM / baking
- NodeWrangler UI
