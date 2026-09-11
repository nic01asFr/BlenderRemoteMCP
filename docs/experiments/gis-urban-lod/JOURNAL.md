# Journal — GIS urban LOD

Format d’entrée :

```
## YYYY-MM-DD — titre
- Objectif :
- Données :
- Procédure :
- Résultat (métriques) :
- Écarts / bugs :
- Capitalisé vers :
- Suite :
```

---

## 2026-09-11 — Cadrage initial (chat → track)

- **Objectif :** structurer le travail pour que les essais GIS/LOD
  redeviennent specs + fonctionnalités sans perte d’info.
- **Données :** pas encore d’extrait BD TOPO ; fixture synthétique créée.
- **Procédure :** capitalisation conceptuelle + arborescence experiments.
- **Résultat :**
  - Distinction posée : GN/mats = littératie opérateur ; maquette LOD = résultat métier.
  - Cible Cerema : données référentielles → GN → materials → scène validable.
  - LOD1 P0, LOD2 P1, LOD3 différé.
- **Écarts :** pas encore de template `urban_lod1_*` dans `gn_lib`.
- **Capitalisé vers :**
  - `docs/experiments/README.md` (boucle promotion)
  - ce journal + README track
  - spec + plan + `expertise/integrations/gis_urban_lod.md`
  - `skill://gis-blender` (amorce)
  - fixture `fixtures/blocks_lod1.geojson`
- **Suite :**
  1. Smoke : importer fixture dans Blender (execute_python) + extrude manuel/GN
  2. Stabiliser → promouvoir en `gn_lib` template `urban_lod1_extrude`
  3. Recipe `gis_lod1_blocks` + mats façade/toiture
  4. Remplacer fixture par extrait BD TOPO zone pilote

## 2026-09-11 — Smoke LOD1 baseline (script + Chrome)

- **Objectif :** valider fixture → extrusion hauteurs → mats → vue bureau.
- **Données :** `fixtures/blocks_lod1.geojson` (5 bâtiments, embedded in MCP call).
- **Procédure :**
  1. `clear_scene` + `setup_studio_lighting`
  2. `execute_python` bmesh extrude + `mat_lib.apply` (mapping use→preset)
  3. Caméra (85, -70, 55) lens 35 clip_end 500
  4. Validation MCP `get_screenshot` + Chrome DevTools screenshot bureau
- **Résultat (métriques) :**
  - `buildings`: 5, `heights_match`: **True**
  - B1 12.0m, B2 18.5m, B3 9.0m, B4 24.0m, B5 6.0m (bbox = attr)
  - Presets : concrete / brushed_metal / concrete / concrete / plastic_soft + ground grass
  - Chrome : sol vert + volumes colorés visibles (MATERIAL shading) ; outliner `LOD1_B*`
  - MCP X11 screenshot plus « workbench » (gris) — moins fiable pour juger les mats
- **Écarts / bugs :**
  - `mat_apply_preset` pas encore dans le catalogue Cursor MCP discovery (ok via `mat_lib` in execute_python)
  - get_screenshot ≠ fidelity materials du noVNC
- **Capitalisé vers :**
  - `scripts/lod1_extrude_baseline.py`
  - PROMOTE.md (baseline prêt pour template GN)
- **Suite :**
  1. Promouvoir logique en `gn_lib.urban_lod1_extrude` (ou importer curves→mesh en GN)
  2. Recipe `gis_lod1_blocks`
  3. Toiture LOD2 lite pour `roof=gable`
