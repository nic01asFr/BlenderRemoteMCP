---
id: geometry-nodes
title: Geometry Nodes (Blender 4.0)
summary: Construire et piloter des arbres GN de façon fiable via bpy — profil natif BlenderRemoteMCP.
---

# Geometry Nodes — expertise agent (Blender 4.0.2)

Profil **natif** : pas d’addon tiers. Tout passe par `bpy.data.node_groups`
(`GeometryNodeTree`) + modifier `NODES`, idéalement encapsulé plus tard dans
des tools bridge. En attendant : `execute_python` + `result = …`, en suivant
ce skill et les recipes `gn_*`.

Source de vérité API : introspection live sur l’image service (4.0.2) +
opérateurs officiels `scripts/startup/bl_operators/geometry_nodes.py`
(tag `blender-v4.0-release`). La doc HTML `docs.blender.org` n’est pas
toujours récupérable automatiquement — ne pas inventer des `bl_idname`.

## Règles d’or pour le LLM

1. **Créer le groupe** : `ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')` puis **`ng.is_modifier = True`** si le groupe sert de modifier.
2. **Interface 4.0** : utiliser **`ng.interface.new_socket(name=…, in_out='INPUT'|'OUTPUT', socket_type=…)`**.  
   **Ne pas** utiliser l’ancien `ng.inputs.new` / `ng.outputs.new` (absent / obsolète sur 4.0).
3. **Sockets utiles** : `NodeSocketGeometry`, `NodeSocketFloat`, `NodeSocketInt`, `NodeSocketVector`, `NodeSocketBool`, `NodeSocketObject`, `NodeSocketCollection`, `NodeSocketColor`, `NodeSocketString`.
4. **Toujours** `NodeGroupInput` + `NodeGroupOutput` ; lier la géométrie de bout en bout.
5. **Noms de sockets** : préférer `node.inputs['Density']` / `outputs['Mesh']` (libellés UI). Si `KeyError`, lister `[s.name for s in node.inputs]` — certains sockets sont **unavailable** selon le mode du node.
6. **Modifier inputs** : après assignation `mod.node_group = ng`, les valeurs exposées se règlent avec `mod[item.identifier] = value` où `item` vient de `ng.interface.items_tree` (`in_out == 'INPUT'`, hors géométrie). Identifiers typiques : `Socket_0`, `Socket_1`, …
7. **Champs (fields)** : beaucoup d’inputs (Selection, Position, Density factor…) attendent un **champ**, pas seulement une constante. Une constante via `default_value` marche souvent ; un lien depuis un node Input* construit un champ.
8. **Instances** : `GeometryNodeInstanceOnPoints` sort des **instances**. Pour un mesh évaluable / exportable, enchaîner **`GeometryNodeRealizeInstances`**.
9. **Depsgraph** : après édition, `bpy.context.view_layer.update()` puis `obj.evaluated_get(depsgraph)` pour compter verts/polys.
10. **Ne pas** construire un arbre GN à la main dans le GUI via `send_click` — trop fragile. Code déterministe uniquement.

## Patron minimal (passe-plat)

```python
import bpy

def gn_empty(name="GN_Pass"):
    if name in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[name])
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.is_modifier = True
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n_in = ng.nodes.new("NodeGroupInput")
    n_out = ng.nodes.new("NodeGroupOutput")
    n_in.location = (-200, 0)
    n_out.location = (200, 0)
    ng.links.new(n_in.outputs["Geometry"], n_out.inputs["Geometry"])
    return ng
```

Aligné sur l’opérateur officiel `add_empty_geometry_node_group`.

## Patron scatter (validé sur le service)

Chaîne : `MeshGrid` → `DistributePointsOnFaces` (**RANDOM**) → `InstanceOnPoints` (IcoSphere) → `RealizeInstances` → Group Output.

Points critiques validés :

- `distribute_method = 'RANDOM'` → utiliser **`Density`** (et `Seed`).  
  `Distance Min` / `Density Max` sont **unavailable** en RANDOM → `KeyError` si on y touche.
- `distribute_method = 'POISSON'` → `Distance Min`, `Density Max`, `Density Factor`, `Seed` (pas `Density`).
- Scale d’instance : float groupe → `ShaderNodeCombineXYZ` → input `Scale` de Instance on Points.
- Inputs modifier : `Density` → `Socket_0`, `Instance Scale` → `Socket_1` (ordre de création des sockets).

Recipe : `gn_scatter_instances`.

## Catalogue `bl_idname` utiles (4.0 — non exhaustif)

**Primitifs mesh** : `GeometryNodeMeshGrid`, `MeshCube`, `MeshIcoSphere`, `MeshUVSphere`, `MeshCylinder`, `MeshCone`, `MeshLine`, `MeshCircle`.

**Points / instances** : `GeometryNodeDistributePointsOnFaces`, `DistributePointsInVolume`, `InstanceOnPoints`, `RealizeInstances`, `TranslateInstances`, `RotateInstances`, `ScaleInstances`, `GeometryToInstance`, `InstancesToPoints`.

**Mesh ops** : `ExtrudeMesh`, `SubdivideMesh`, `SubdivisionSurface`, `MergeByDistance`, `MeshBoolean`, `Triangulate`, `DeleteGeometry`, `SeparateGeometry`, `JoinGeometry`, `Transform`, `SetPosition`, `SetMaterial`, `DualMesh`, `FlipFaces`.

**Courbes** : `CurvePrimitiveLine`, `CurvePrimitiveCircle`, `CurveSpiral`, `ResampleCurve`, `FilletCurve`, `CurveToMesh`, `CurveToPoints`, `MeshToCurve`, `FillCurve`.

**Sample / attributs** : `InputPosition`, `InputNormal`, `InputIndex`, `InputNamedAttribute`, `StoreNamedAttribute`, `CaptureAttribute`, `SampleIndex`, `SampleNearest`, `SampleNearestSurface`, `Proximity`, `Raycast`.

**Zones** : `RepeatInput`/`RepeatOutput`, `SimulationInput`/`SimulationOutput` — puissants, coûteux ; documenter seed et bake si utilisés.

**Infos** : `ObjectInfo`, `CollectionInfo`, `SelfObject`, `IsViewport`, `InputSceneTime`.

Lister dynamiquement si doute :

```python
sorted(n for n in dir(bpy.types) if n.startswith("GeometryNode"))
```

## Brancher un modifier

```python
mod = obj.modifiers.new("GeometryNodes", "NODES")  # ou réutiliser un NODES existant
mod.node_group = ng
for item in ng.interface.items_tree:
    if getattr(item, "in_out", None) != "INPUT":
        continue
    if not hasattr(item, "identifier"):
        continue
    if item.socket_type == "NodeSocketGeometry":
        continue
    # exemple : mod[item.identifier] = 1.0
```

Types d’objets supportés (poll officiel) : `MESH`, `POINTCLOUD`, `VOLUME`, `CURVE`, `FONT`, `CURVES`.

## Attributs vs sockets modifier

- Valeur constante : `mod[identifier] = …`
- Piloter par attribut mesh : `mod[identifier + "_use_attribute"] = True` et `mod[identifier + "_attribute_name"] = "attr"` (helpers dans les opérateurs Blender).

## Anti-patterns

- Improviser 30 nodes sans recipe → préférer `list_recipes` tag `geometry-nodes`.
- Oublier `RealizeInstances` puis s’étonner d’un export / eval vide.
- Mélanger mode RANDOM et sockets Poisson.
- Éditer le node tree d’un asset partagé sans le dupliquer (`ng.copy()`).
- Croire que le socket s’appelle encore `Geometry` en sortie d’un primitif mesh : souvent **`Mesh`**.

## Suite plateforme (bridge)

Tools MCP futurs souhaités (ne pas les inventer tant qu’absents) :

- `gn_list_trees` / `gn_inspect_tree`
- `gn_ensure_modifier`
- `gn_set_input`
- `gn_apply_recipe_tree` (templates versionnés)

Voir `expertise/integrations/geometry_nodes.md`.

## Vérification

Après construction : `get_screenshot` + `get_canvas_url`. Compter la géométrie évaluée dans `result` pour prouver que l’arbre n’est pas mort.
