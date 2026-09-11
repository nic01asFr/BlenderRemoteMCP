---
id: materials
title: Matériaux & texturing (Blender 4.0)
summary: Presets Principled pro via mat_lib — couleurs 0–1, Transmission Weight, Noise/Bump.
---

# Matériaux (profil natif)

## Chemin recommandé (LLM)

1. `mat_list_presets`
2. `mat_apply_preset` avec `object_name` + params (`tint`, `roughness`, …)
3. `get_screenshot` / `get_canvas_url`

Ne reconstruis un arbre Principled à la main que si aucun preset ne convient.

## Outils bas niveau (toujours valides)

- `create_material`, `apply_material`, `set_color`, `list_materials`
- `execute_python` : `mat_lib` est injecté (`result = mat_lib.apply(...)`)

## Principled 4.0 — noms critiques

Validés sur le service **4.0.2** :

- `Base Color`, `Metallic`, `Roughness`, `IOR`, `Alpha`
- **`Transmission Weight`** (pas l’ancien `Transmission`)
- `Coat Weight` / `Coat Roughness`, `Sheen Weight`
- `Emission Color` / `Emission Strength`

## Presets `mat_lib`

| id | Usage |
|----|--------|
| `concrete` | Archviz, Noise bump |
| `brushed_metal` | Produit / métal satiné |
| `glass_clear` | Verre (transmission) |
| `plastic_soft` | Studio produit + coat |
| `terrain_grass` | Sol procédural bi-couleur |
| `rubber_matte` | Caoutchouc |

## Règles

- Couleurs **RGBA 0–1** (pas 0–255).
- Un matériau partagé = même datablock sur plusieurs objets.
- Textures image / UDIM / baking : hors scope v1 — reste sur procédural.
- Après `gn_run_template`, enchaîne `mat_apply_preset` sur `GN_Terrain`, `GN_Facade`, etc.

## Recipe

`mat_studio_presets` — sphères studio + presets, puis screenshot.
