# Service idéal — plan d’intégration L0–L5

> **For agentic workers:** L1–L3 est posé dans ce dépôt ; L4–L5 = phases suivantes.

**Goal:** Workspace BlenderRemoteMCP = runtime + guidance (skills/recipes/prompts/_context), prêt à composer métier et agent.

**Architecture:** `expertise/` versionné + `src/guidance.py` + branchement MCP. Métier et personas hors `MCP_TOOLS`.

## Global Constraints

- Ne pas coller BIM/ARP/mesh dans le catalogue d’outils primitifs.
- Bearer + OAuth inchangés.
- Corpus BigLocalApps : porter par fichiers dans `expertise/`, pas de copie aveugle de tout le monorepo.

---

### Done (cette passe)

- [x] Spec `docs/superpowers/specs/2026-09-11-service-ideal-ecosysteme-design.md`
- [x] `expertise/{skills,recipes,prompts,agents,integrations}`
- [x] `src/guidance.py` + tools + prompts MCP + skill:// + `_context`
- [x] Image AIO copie `expertise/`

### Next — L1 enrichissement

- [ ] Porter MD BigLocalApps manquants (`principled_bsdf`, `lighting_architectural`, workflows → recipes)
- [ ] Enrichir `blender://scene` (JSON scène réelle)
- [ ] `get_blender_context` live (mode/workspace via execute_python)

### Next — L4

- [ ] Bridge / composition BlenderRoads + ge-mesh (doc déjà dans `integrations/`)
- [ ] Option: tools métier préfixés `roads_*` dans un plugin image, pas dans le core

### Next — L5

- [ ] Copier personas dans `expertise/agents/`
- [ ] Pod `blender-agent` (calque qgis-agent) : recipe_matcher + tips
