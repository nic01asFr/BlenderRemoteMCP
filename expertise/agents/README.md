# Personas L5 (stubs)

Les system prompts **ne vont pas** dans `initialize` du workspace.

| Persona | Source à porter | Usage |
|---------|-----------------|--------|
| BIM MOE | `BigLocalApps/agents/bim_moe/system_prompt.md` | Claude Desktop / futur blender-agent |
| Archviz | dérivé skills lighting/materials + recipe archviz | Idem |
| Roads | `BlenderRoads/conductors/…` + graphe | Produit L4 + persona L5 |

Quand un pod `blender-agent` existera (calque qgis-agent), il chargera ces fichiers comme profil LLM.
