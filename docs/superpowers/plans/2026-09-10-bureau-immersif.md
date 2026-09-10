# Bureau immersif — Implementation Plan

> **For agentic workers:** implement task-by-task. Steps use checkbox syntax.

**Goal:** Bureau Blender immersif (`/desktop`) sans chrome web, alias `/canvas`, URLs MCP en `/desktop`, prêt pour embed hub.

**Architecture:** Même handler HTML pour `/desktop` et `/canvas` ; template RFB minimal ; `_canvas_url` → `/desktop`.

**Tech Stack:** FastAPI/Starlette templates, noVNC RFB vendored, pytest.

## Global Constraints

- Pas de jargon noVNC/VNC dans l’UI utilisateur.
- Conserver le nom d’outil `get_canvas_url`.
- Ne pas construire le hub QGIS-like.

---

### Task 1: Tests

- [ ] Mettre à jour / ajouter assertions `/desktop`, absences de chrome, URLs MCP.
- [ ] `python -m pytest tests/test_transport.py -q` (échoue avant code).

### Task 2: Template + routes + wording

- [ ] Réécrire `templates/blender_canvas.html`.
- [ ] Handler partagé + route `/desktop` ; auth pages neutres.
- [ ] `_canvas_url`, instructions, landing, MCP App.
- [ ] Pytest vert.

### Task 3: Doc design déjà écrite

- [ ] Spec dans `docs/superpowers/specs/2026-09-10-bureau-immersif-design.md`.
