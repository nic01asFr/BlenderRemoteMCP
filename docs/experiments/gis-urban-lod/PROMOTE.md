# Promotion — GIS urban LOD → service

Tableau vivant : ce que les essais ont déjà fait entrer (ou vont faire entrer)
dans le produit.

| Élément | Statut | Cible code / docs |
|---------|--------|-------------------|
| Boucle experiments | Fait | `docs/experiments/README.md` |
| Design LOD | Fait | `docs/superpowers/specs/2026-09-11-gis-urban-lod-design.md` |
| Plan | Fait | `docs/superpowers/plans/2026-09-11-gis-urban-lod.md` |
| Contrat intégration | Fait | `expertise/integrations/gis_urban_lod.md` |
| Skill amorce | Fait | `expertise/skills/gis-blender.md` |
| Fixture GeoJSON LOD1 | Fait | `fixtures/blocks_lod1.geojson` |
| Parse attributs GeoJSON (test unitaire) | À faire | `tests/test_gis_fixtures.py` |
| Template `gn_lib.urban_lod1_extrude` | À faire | `docker/blender-canvas/gn_lib/` |
| Recipe `gis_lod1_blocks` | À faire | `expertise/recipes/` |
| Tools MCP `gis_*` (optionnel) | Différé | seulement si recipes insuffisantes |
| Import BD TOPO réel | Différé | volume `/projects`, hors git si licence |

## Règle

Toute case « À faire » qui réussit en essai doit passer à **Fait** *et*
mettre à jour le JOURNAL + ce tableau dans le même commit si possible.
