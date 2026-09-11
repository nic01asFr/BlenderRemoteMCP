# Design — Maquette urbaine GIS LOD1→2 (Cerema / référentiel)

**Date :** 2026-09-11  
**Branche :** `feature/blender-gis-lod`  
**Statut :** cadrage + fixtures ; implémentation templates à venir

## Intention

Permettre à un **agent Blender** + un **user expert** de reconstruire une
scène urbaine à partir de données référentielles, en s’approchant d’une
maquette **LOD1 puis LOD2** (esprit CityGML), avec maîtrise permanente des
Geometry Nodes et des materials.

## Non-objectifs

- LOD3 architectural détaillé
- Remplacer un SIG (QGIS reste L4/L5 complémentaire)
- Fusionner BD TOPO dans le monorepo runtime

## Architecture

```
L4 GIS-Blender (ce track)
  skills + recipes + (futurs) gn templates urban_*
       ↓ utilise
L1–L3 opérateur
  skill://geometry-nodes, skill://materials, gn_lib, mat_lib
       ↓ tourne sur
L0 BlenderRemoteMCP
  bpy, desktop, auth, MCP
```

## Contrats de données (LOD1)

Attributs minimaux par bâtiment (GeoJSON properties) :

| Clé | Type | Obligatoire | Notes |
|-----|------|-------------|-------|
| `height` | number (m) | oui | Extrusion Z |
| `id` | string | recommandé | Stable |
| `roof` | string | non | `flat`\|`gable`… pour LOD2 |
| `use` | string | non | Résidentiel / … → mat preset |

CRS : documenter EPSG dans le FeatureCollection (`crs` ou README fixture).
Essais locaux en **métrique locale** (déjà projeté) pour éviter proj dans Blender v1.

## Chemin agent (cible)

1. Déposer / référencer le fichier sous `/projects`
2. Recipe ou tool d’import → objets / attributs
3. `gn_run_template` urban_lod1…
4. `mat_apply_preset` par classe
5. Screenshot + desktop pour l’expert

## Critères de succès LOD1

- N bâtiments extrudés = N features valides
- Hauteurs respectées (± tolérance)
- Temps acceptable sur zone pilote (< quelques minutes)
- Scene digest / counts dans `result`
- Reproductible depuis fixture git

## Lien expériences

Toute validation passe par `docs/experiments/gis-urban-lod/` avant promotion.
