---
id: camera-render
title: Caméra et rendu
summary: Cadrage, moteur, et boucle screenshot → bureau.
---

# Caméra et rendu

## Boucle agent

1. Modifier la scène.
2. `get_screenshot` — validation dans le chat.
3. `get_canvas_url` / `blender_desktop_ui` — validation humaine.
4. `configure_render` puis rendu (outil dédié ou `execute_python`).

## Réglages

- `detect_gpu` avant Cycles GPU ; sinon CPU + denoising.
- Résolution : alignée à `DISPLAY_GEOMETRY` / besoin livrable (pas 4K par défaut sur pod 4 CPU).

## Voir aussi

- Recipe `studio_product`
- Skill `bpy-pitfalls`
