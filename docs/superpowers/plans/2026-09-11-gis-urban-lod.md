# GIS urban LOD — Implementation Plan

> **For agentic workers:** s’appuyer sur `docs/experiments/gis-urban-lod/JOURNAL.md`
> et `PROMOTE.md`. Ne pas skipper la capitalisation.

**Goal:** Maquette LOD1 depuis GeoJSON (fixture puis BD TOPO), via GN + mats.

**Architecture:** Fixture → parse → (futur) `gn_lib.urban_lod1_extrude` → mats ;
expertise `gis-blender` guide l’agent.

**Tech Stack:** GeoJSON, Blender 4.0 GN, mat_lib, MCP recipes.

## Global Constraints

- Attribut `height` en mètres
- Pas de gros extrait IGN dans git
- Réutiliser `gn_lib` / `mat_lib` (pas de second pont)

---

### Task 1 — Cadre (cette passe)
- [x] `docs/experiments/` boucle promotion
- [x] Spec + plan + integration + skill amorce
- [x] Fixture `blocks_lod1.geojson`
- [x] Journal + PROMOTE

### Task 2 — Smoke Blender (prochaine)
- [ ] Script execute_python : lire fixture, créer meshes extrudés (baseline sans GN)
- [ ] Journaliser métriques
- [ ] Comparer à une version GN dès que template prêt

### Task 3 — Promotion gn_lib
- [ ] `urban_lod1_extrude` template
- [ ] Recipe `gis_lod1_blocks`
- [ ] Tests parse GeoJSON hors Blender
- [ ] mat presets toiture / façade sur classes

### Task 4 — Données réelles
- [ ] Procédure obtention extrait BD TOPO zone pilote
- [ ] Mapping champs BD TOPO → contrat attributs
- [ ] Essai + journal + éventuel ajustement spec
