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

## 2026-09-11 — Socle opérateur déjà disponible (ne pas réinventer)

État du service au moment du cadrage (branches materials/GN) :

- `gn_run_template` : scatter_poisson, terrain_displace, facade_extrude, curve_railing
- `mat_apply_preset` : concrete, brushed_metal, glass_clear, plastic_soft, terrain_grass, rubber_matte
- Recipes : `gn_pro_showcase`, `mat_studio_presets`
- Bureau : `/desktop` pour validation expert

Ces briques sont le **socle** des essais LOD (réutiliser, ne pas forker).
