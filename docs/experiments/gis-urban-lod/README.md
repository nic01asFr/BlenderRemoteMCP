# Track — GIS urban LOD (maquette référentielle)

**Branche :** `feature/blender-gis-lod`  
**Objectif métier :** reconstruire une scène urbaine depuis des données
référentielles (BD TOPO / emprises + hauteurs, MNT…) en Geometry Nodes,
avec materials maîtrisés — s’approcher d’une maquette **LOD1 puis LOD2**
(CityGML), dans un cadre agent Blender + user expert (ex. Cerema).

## Cadre conceptuel (ne pas perdre)

- **GN + mats** ne sont pas le livrable : ce sont les *écrans métier Blender*
  que l’agent utilise finement en production.
- Le **résultat** = maquette territoriale / projet, validée sur le bureau
  (`/desktop`) par l’expert.
- Spécialisation GIS-dans-Blender = profil L4 qui *compose* le runtime
  BlenderRemoteMCP (ne pas polluer `MCP_TOOLS` génériques).

## Niveaux LOD (cible)

| LOD | Contenu | Priorité essai |
|-----|---------|----------------|
| LOD1 | Emprises + extrusion hauteur | **P0 — premier essai** |
| LOD2 | Toitures simplifiées (pente / type) | P1 |
| LOD3 | Détail façades / ouvertures | P2+ (hors scope court) |

## Données

| Source | Usage | État |
|--------|--------|------|
| Fixture synthétique `fixtures/blocks_lod1.geojson` | Dev / CI / smoke | **Disponible** |
| Extrait BD TOPO (bâtiments) | Zone pilote réelle | À fournir (non commit si licence) |
| MNT / RGE ALTI | Sol | Optionnel P1 |
| Ortho | Texturing | Plus tard |

## Pipeline cible

```
GeoJSON/GPKG (polygones + height [, roof])
  → import /projects (+ parse attributs)
  → GN template urban_lod1_extrude (futur gn_lib)
  → mat_apply_preset (façade concrete, toiture, sol grass…)
  → get_screenshot + desktop validation
```

## Fichiers du track

| Fichier | Rôle |
|---------|------|
| `JOURNAL.md` | Toutes les observations d’essais |
| `fixtures/` | Données redistribuables de test |
| `PROMOTE.md` | Ce qui a été / sera promu vers le service |
| Spec | `docs/superpowers/specs/2026-09-11-gis-urban-lod-design.md` |
| Plan | `docs/superpowers/plans/2026-09-11-gis-urban-lod.md` |
| Expertise | `expertise/integrations/gis_urban_lod.md`, `skill://gis-blender` |

## Lien avec le reste du service

- Opérateur GN : `skill://geometry-nodes`, `gn_lib`
- Opérateur mats : `skill://materials`, `mat_lib`
- Mesh externe : `integrations/ge_mesh.md`
- BIM : `integrations/big_local_apps.md` (orthogonal ; IFC ≠ LOD CityGML)
