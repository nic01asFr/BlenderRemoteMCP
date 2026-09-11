# Geometry Nodes — profil natif (L1–L3, bridge futur)

Profil **Blender natif** (pas L4 métier). Les clients peuvent s’en inspirer
pour packager d’autres profils (skills + recipes + helpers image).

## État

| Élément | Statut |
|---------|--------|
| `skill://geometry-nodes` | Fait (API 4.0.2 live + opérateurs Blender) |
| Recipes `gn_scatter_instances`, `gn_curve_to_mesh_pipe` | Fait |
| Prompt `geometry_nodes` | Fait |
| Tools MCP `gn_*` dédiés | À venir (bridge) — aujourd’hui `execute_python` |

## Contrat tools bridge (cible)

Ne pas les exposer tant qu’absents du catalogue. Cible LLM-friendly :

1. `gn_list_trees` — node groups `GeometryNodeTree` + objets qui les utilisent
2. `gn_inspect_tree` — nodes, links, interface sockets (JSON)
3. `gn_ensure_modifier(object, tree?)` — crée/assigne modifier NODES
4. `gn_set_input(object, name|identifier, value)` — `mod[identifier] = …`
5. `gn_new_tree_from_template(id)` — templates versionnés (scatter, pipe, …)

Réponses homogènes : `{ok, data, warnings, scene_digest}`.

## Extension par le client

Déposer skills/recipes additionnels sous `expertise/` (ou volume profil
futur) sans forker le runtime. Les arbres `.blend` / assets GN peuvent
vivre dans `/projects`.
