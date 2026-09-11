# GIS urban LOD (L4) — contrat

**Track expériences :** `docs/experiments/gis-urban-lod/`  
**Spec :** `docs/superpowers/specs/2026-09-11-gis-urban-lod-design.md`

## Rôle

Composer le runtime BlenderRemoteMCP pour des **maquettes urbaines
référentielles** (LOD1→2), sans fusionner un SIG dans ce dépôt.

## Dépendances opérateur (L1–L3)

- Geometry Nodes : `skill://geometry-nodes`, `gn_lib`
- Materials : `skill://materials`, `mat_lib`
- Desktop : validation expert

## Livrables attendus (promotion)

1. Parse / validation contrat GeoJSON (tests)
2. Template GN `urban_lod1_extrude`
3. Recipe `gis_lod1_blocks`
4. Mapping `use`/`roof` → presets mats
5. Procédure données réelles (BD TOPO → `/projects`)

## Hors scope

BIM/IFC (`big_local_apps.md`), Roads (`blender_roads.md`), mesh photogrammétrie
(`ge_mesh.md`) — composition agent, pas absorption.
