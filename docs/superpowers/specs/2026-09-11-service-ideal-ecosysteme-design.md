# Design — Service Blender idéal (écosystème IA)

**Date :** 2026-09-11  
**Statut :** structure d’intégration (L0–L5)

## Principe

```
L5  Agent / hub (option)     personas, mémoire, enrichisseurs     → qgis-sspcloud pattern
L4  Produits métier          BIM, route, mesh                     → repos séparés
L1–L3 Guidance workspace     skills, recipes, prompts, _context   → CE dépôt (expertise/)
L0  Runtime                  bpy, auth, desktop, outils primitifs → BlenderRemoteMCP actuel
```

**BlenderRemoteMCP reste le workspace.** L’expertise versionnée vit dans `expertise/` et est exposée en MCP. Le métier (BlenderRoads, BigLocalApps BIM, ge-mesh) **compose** le runtime, il ne fusionne pas dedans.

## Carte d’intégration

| Source locale | Intégration | Couche |
|---------------|-------------|--------|
| BigQgisMCP (skills/recipes/prompts/_context) | **Patron** à calquer | L1–L3 |
| BigLocalApps `skills/blender/**` | Corpus → `expertise/skills/` (+ workflows → recipes) | L1–L2 |
| BigLocalApps `agents/*/system_prompt.md` | Copier/adapter → `expertise/agents/` (pas dans initialize) | L5 |
| BlenderRoads conductor + graphe | Client MCP séparé ou tools métier via bridge ; pas dans `MCP_TOOLS` générique | L4 |
| ge-mesh-mcp / Panoramax | MCP externe composé par l’agent | L4 |
| qgis-sspcloud agent | Futur `blender-agent` SSPCloud | L5 |
| wikichat | Atelier / capitalisation, hors package expertise | L7 |

## Arborescence (ce dépôt)

```
expertise/
  README.md                 # contrat d’ajout
  skills/*.md               → resource skill://{id}
  recipes/*.json            → list/get/run_recipe
  prompts/prompts.json      → prompts/list|get
  agents/README.md          # personas L5 (stubs + liens BigLocalApps)
  integrations/             # contrats L4 (BlenderRoads, BIM, mesh…)
src/guidance.py             # chargeurs + build_context + catalogue MCP
```

## Contrats MCP

1. **`initialize.instructions`** — workflow + « lis les skills / recipes avant d’improviser en execute_python ».
2. **`prompts/*`** — starters qui pointent vers skills/recipes.
3. **`resources`** — `skill://…`, `ui://…`, `blender://scene` (à enrichir), `blender://projects`.
4. **Tools guidance** — `list_recipes`, `get_recipe`, `run_recipe`, `get_blender_context` (phase légère).
5. **`_context`** — joint aux réponses d’outils mutants (phase, counts, hint).
6. **Outils primitifs** — restent plats ; pas de prolifération métier dans `MCP_TOOLS`.

## Hors scope de cette passe

Implémentation du pod agent, port BIM/Roads, graphe FAISS. La structure `integrations/` et `agents/` les prépare.
