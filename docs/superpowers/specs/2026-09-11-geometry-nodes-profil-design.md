# Design — Profil Geometry Nodes (natif)

**Date :** 2026-09-11  
**Statut :** expertise L1–L3 intégrée ; bridge `gn_*` différé

## Objectif

Faire de Geometry Nodes un **profil natif** BlenderRemoteMCP : le LLM
construit et pilote des arbres GN de façon fiable, sans addon tiers, en
préparant le même mécanisme d’extension que les profils métier lourds.

## Sources

- Introspection live Blender **4.0.2** (service prod) : `GeometryNodeTree`,
  `NodeTreeInterface.new_socket`, catalogue `GeometryNode*`, modes
  `DistributePointsOnFaces` (RANDOM vs POISSON).
- Code officiel `blender-v4.0-release` :
  `scripts/startup/bl_operators/geometry_nodes.py` (`is_modifier`,
  interface sockets, poll objets).
- Doc HTML `docs.blender.org` : non récupérable ici (403/409) — non bloquant
  grâce à l’introspection versionnée sur l’image.

## Livrables cette passe

1. `expertise/skills/geometry-nodes.md` → `skill://geometry-nodes`
2. Recipes `gn_scatter_instances`, `gn_curve_to_mesh_pipe`
3. Prompt MCP `geometry_nodes`
4. `expertise/integrations/geometry_nodes.md` (contrat bridge)
5. `substitute_params` : support `{{param}}` / `repr` pour code recipes

## Non-goals

- Tools MCP `gn_*` (prochaine itération bridge)
- Simulation / Repeat zones avancées (mentionnées, pas templatées)
- Port 4.5 / Bonsai

## Validation

- Scatter exécuté sur prod : `evaluated_polygons > 0`, modifier inputs
  `Socket_0` / `Socket_1`.
- Tests `tests/test_guidance.py` étendus.
