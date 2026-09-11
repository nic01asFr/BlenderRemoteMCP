# Geometry Nodes pro — Implementation Plan

> **For agentic workers:** exécuter task-by-task ; valider chaque template sur Blender 4.0.2 prod.

**Goal:** Permettre au LLM de produire des résultats Geometry Nodes professionnels/complexes via templates versionnés + tools MCP, pas via improvisation.

**Architecture:** Bibliothèque `gn_lib` dans l’image blender-canvas (injectée dans `execute_python`) ; tools `gn_list_templates` / `gn_run_template` ; skill avancé + recipes minces.

**Tech Stack:** Blender 4.0.2 `GeometryNodeTree` + `NodeTreeInterface`, FastAPI bridge, MCP tools.

## Global Constraints

- Blender **4.0.2** ; interface sockets via `ng.interface.new_socket` ; `ng.is_modifier = True`
- Pas de prolifération de 20 tools GN — **2 tools** + templates
- Réponses `{ok, template, object, tree, evaluated_*, warnings}`

---

### Task 1 — `gn_lib` builders
- [ ] `docker/blender-canvas/gn_lib/` : scatter_poisson, terrain_displace, facade_extrude, curve_railing
- [ ] `list_templates()` / `run(id, params, object_name)`

### Task 2 — Bridge
- [ ] Injecter `gn_lib` dans namespace `execute_python`
- [ ] Dockerfile COPY `gn_lib`
- [ ] API optionnelle ou purement via execute (MCP suffit)

### Task 3 — MCP
- [ ] `gn_list_templates`, `gn_run_template` dans main_mcp + MCP_TOOLS + handle branch
- [ ] Recipes `gn_pro_*` + skill advanced + prompt update

### Task 4 — Verify
- [ ] pytest guidance/tools
- [ ] rebuild + rollout + run templates on prod + screenshot
