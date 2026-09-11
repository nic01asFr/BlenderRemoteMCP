# Geometry Nodes — profil natif (L1–L3 + bridge)

Profil **Blender natif** (pas L4 métier).

## État

| Élément | Statut |
|---------|--------|
| `skill://geometry-nodes` | Fait |
| Recipes `gn_*` + `gn_pro_showcase` | Fait |
| Prompt `geometry_nodes` | Fait |
| `gn_lib` dans l’image | Fait (`scatter_poisson`, `terrain_displace`, `facade_extrude`, `curve_railing`) |
| Tools `gn_list_templates` / `gn_run_template` | Fait |
| Tools inspect/set_input fins | À venir |

## Usage agent

1. `gn_list_templates`
2. `gn_run_template` avec params
3. `get_screenshot` + `get_canvas_url`
4. Recipe `gn_pro_showcase` pour une scène démo complète

## Extension client

Ajouter un builder dans `gn_lib/builders.py` + entrée `registry.py` — sans forker le runtime MCP.
