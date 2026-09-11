---
id: bpy-pitfalls
title: Pièges bpy / Blender 4.0
summary: Éviter les erreurs classiques (contexte, unités, thread, résultats).
---

# Pièges bpy (Blender 4.0 remote)

- **Main thread** : tout `bpy` passe déjà par le bridge ; n’essaie pas de « paralléliser » côté agent.
- **`execute_python`** : assigne `result = …` pour renvoyer une valeur ; sinon tu n’as que le succès muet.
- **Noms d’objets** : toujours `get_scene_info` / `list_objects` avant `modify_object` — les noms changent après duplications.
- **Couleurs** : RGBA 0–1, pas 0–255.
- **Unités** : métrique ; un étage ≈ 3 m. Vérifie l’échelle après import.
- **Rendu CPU** : sur SSPCloud sans GPU, `configure_render` → Cycles CPU + denoising.
- **GUI** : après des changements importants, `get_screenshot` puis `get_canvas_url` pour l’humain.
- **Ne pas** réinventer l’éclairage : `setup_studio_lighting` + skill `lighting` / recipe `studio_product`.
- **Geometry Nodes** : interface via `ng.interface.new_socket` (pas `ng.inputs.new`) ; `ng.is_modifier = True` ; voir `skill://geometry-nodes` et recipes `gn_*`.
