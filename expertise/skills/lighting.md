---
id: lighting
title: Éclairage
summary: Studio et archviz — partir des helpers, pas d’une lumière unique au hasard.
---

# Éclairage

## Défaut sûr

1. `setup_studio_lighting` pour un 3-point correct.
2. `setup_camera` pour un cadrage de départ.
3. Ajuster intensités via `execute_python` si besoin (Energy, Color).

## Archviz extérieur

- HDRI / sun : voir recipe `archviz_exterior` (étapes) et corpus BigLocalApps `lighting_architectural`.
- Éviter dix Area lights « pour remplir » — une direction dominante + fill doux.

## Rendu

- Après lighting : skill `camera-render` + `configure_render` / `detect_gpu`.
