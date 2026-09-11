# Materials pro — Implementation Plan

> **For agentic workers:** task-by-task ; valider `mat_apply_preset` sur prod 4.0.2.

**Goal:** Presets Principled professionnels via `mat_lib` + 2 tools MCP.

**Architecture:** Miroir de `gn_lib` ; injecté dans `execute_python` ; apply sur objet nommé.

**Tech Stack:** Blender 4.0.2 shader nodes, FastAPI bridge, MCP.

## Global Constraints

- Noms de sockets Principled **4.0** (`Transmission Weight`, pas `Transmission`)
- Couleurs RGBA 0–1
- Pas d’images externes en v1

---

### Task 1 — mat_lib
- [ ] registry + builders (6 presets)
- [ ] `list_presets` / `apply(preset_id, object_name, params)`

### Task 2 — Bridge MCP
- [ ] Inject `mat_lib` dans blender_addon
- [ ] Dockerfile COPY
- [ ] `mat_list_presets` / `mat_apply_preset`

### Task 3 — Expertise + verify
- [ ] skill materials, recipe, tests, deploy smoke
