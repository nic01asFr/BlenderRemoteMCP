"""Professional Geometry Nodes builders (Blender 4.0.2)."""

from __future__ import annotations

from typing import Any, Dict

import bpy


def _new_tree(name: str) -> bpy.types.GeometryNodeTree:
    if name in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[name])
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.is_modifier = True
    ng.nodes.clear()
    return ng


def _socket(ng, name: str, in_out: str, socket_type: str, default=None):
    sock = ng.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    if default is not None and hasattr(sock, "default_value"):
        try:
            sock.default_value = default
        except Exception:
            pass
    return sock


def _ensure_host(name: str, location=(0.0, 0.0, 0.0), size: float = 1.0) -> bpy.types.Object:
    if name in bpy.data.objects:
        obj = bpy.data.objects[name]
        obj.location = location
        return obj
    bpy.ops.mesh.primitive_plane_add(size=size, location=location)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def _assign_modifier(obj: bpy.types.Object, ng: bpy.types.GeometryNodeTree, values: Dict[str, Any]):
    mod = next((m for m in obj.modifiers if m.type == "NODES"), None)
    if mod is None:
        mod = obj.modifiers.new("GeometryNodes", "NODES")
    mod.node_group = ng
    for item in ng.interface.items_tree:
        if getattr(item, "in_out", None) != "INPUT":
            continue
        if not hasattr(item, "identifier"):
            continue
        if item.socket_type == "NodeSocketGeometry":
            continue
        if item.name in values:
            mod[item.identifier] = values[item.name]
    return mod


def _stats(obj: bpy.types.Object) -> Dict[str, int]:
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(deps)
    mesh = getattr(ev, "data", None)
    if mesh is None:
        return {"evaluated_verts": 0, "evaluated_polygons": 0}
    return {
        "evaluated_verts": len(mesh.vertices),
        "evaluated_polygons": len(mesh.polygons),
    }


def _link_seed(links, seed_out, rand_node):
    for s in rand_node.inputs:
        if s.name == "ID":
            links.new(seed_out, s)
            return


def build_scatter_poisson(params: Dict[str, Any]) -> Dict[str, Any]:
    density_max = float(params.get("density_max", 40.0))
    distance_min = float(params.get("distance_min", 0.25))
    instance_scale = float(params.get("instance_scale", 0.12))
    grid_size = float(params.get("grid_size", 6.0))
    seed = int(params.get("seed", 1))
    object_name = str(params.get("object_name", "GN_Scatter"))

    ng = _new_tree("GN_TPL_ScatterPoisson")
    nodes, links = ng.nodes, ng.links

    _socket(ng, "Density Max", "INPUT", "NodeSocketFloat", density_max)
    _socket(ng, "Distance Min", "INPUT", "NodeSocketFloat", distance_min)
    _socket(ng, "Instance Scale", "INPUT", "NodeSocketFloat", instance_scale)
    _socket(ng, "Seed", "INPUT", "NodeSocketInt", seed)
    _socket(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

    n_in = nodes.new("NodeGroupInput")
    n_in.location = (-900, 0)
    n_out = nodes.new("NodeGroupOutput")
    n_out.location = (700, 0)

    grid = nodes.new("GeometryNodeMeshGrid")
    grid.location = (-650, 120)
    grid.inputs["Size X"].default_value = grid_size
    grid.inputs["Size Y"].default_value = grid_size
    grid.inputs["Vertices X"].default_value = 64
    grid.inputs["Vertices Y"].default_value = 64

    dist = nodes.new("GeometryNodeDistributePointsOnFaces")
    dist.location = (-400, 0)
    dist.distribute_method = "POISSON"

    ico = nodes.new("GeometryNodeMeshIcoSphere")
    ico.location = (-400, -280)
    ico.inputs["Radius"].default_value = 1.0
    ico.inputs["Subdivisions"].default_value = 1

    rand = nodes.new("FunctionNodeRandomValue")
    rand.location = (-200, -200)
    rand.data_type = "FLOAT_VECTOR"
    for s in rand.inputs:
        if s.name == "Min" and s.type == "VECTOR":
            s.default_value = (-3.1416, 0.0, -3.1416)
        if s.name == "Max" and s.type == "VECTOR":
            s.default_value = (3.1416, 0.0, 3.1416)

    iop = nodes.new("GeometryNodeInstanceOnPoints")
    iop.location = (50, 0)

    scale_v = nodes.new("ShaderNodeCombineXYZ")
    scale_v.location = (-150, 120)

    realize = nodes.new("GeometryNodeRealizeInstances")
    realize.location = (350, 0)

    set_smooth = nodes.new("GeometryNodeSetShadeSmooth")
    set_smooth.location = (520, 0)

    links.new(grid.outputs["Mesh"], dist.inputs["Mesh"])
    links.new(n_in.outputs["Density Max"], dist.inputs["Density Max"])
    links.new(n_in.outputs["Distance Min"], dist.inputs["Distance Min"])
    links.new(n_in.outputs["Seed"], dist.inputs["Seed"])
    links.new(dist.outputs["Points"], iop.inputs["Points"])
    links.new(ico.outputs["Mesh"], iop.inputs["Instance"])
    links.new(n_in.outputs["Instance Scale"], scale_v.inputs["X"])
    links.new(n_in.outputs["Instance Scale"], scale_v.inputs["Y"])
    links.new(n_in.outputs["Instance Scale"], scale_v.inputs["Z"])
    links.new(scale_v.outputs["Vector"], iop.inputs["Scale"])
    for s in rand.outputs:
        if s.type == "VECTOR":
            links.new(s, iop.inputs["Rotation"])
            break
    _link_seed(links, n_in.outputs["Seed"], rand)
    links.new(iop.outputs["Instances"], realize.inputs["Geometry"])
    links.new(realize.outputs["Geometry"], set_smooth.inputs["Geometry"])
    links.new(set_smooth.outputs["Geometry"], n_out.inputs["Geometry"])

    obj = _ensure_host(object_name, (0, 0, 0), size=0.5)
    _assign_modifier(
        obj,
        ng,
        {
            "Density Max": density_max,
            "Distance Min": distance_min,
            "Instance Scale": instance_scale,
            "Seed": seed,
        },
    )
    return {"ok": True, "object": obj.name, "tree": ng.name, **_stats(obj), "warnings": []}


def build_terrain_displace(params: Dict[str, Any]) -> Dict[str, Any]:
    grid_size = float(params.get("grid_size", 12.0))
    resolution = int(params.get("resolution", 128))
    noise_scale = float(params.get("noise_scale", 0.35))
    height = float(params.get("height", 1.8))
    object_name = str(params.get("object_name", "GN_Terrain"))

    ng = _new_tree("GN_TPL_Terrain")
    nodes, links = ng.nodes, ng.links

    _socket(ng, "Noise Scale", "INPUT", "NodeSocketFloat", noise_scale)
    _socket(ng, "Height", "INPUT", "NodeSocketFloat", height)
    _socket(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

    n_in = nodes.new("NodeGroupInput")
    n_in.location = (-800, 0)
    n_out = nodes.new("NodeGroupOutput")
    n_out.location = (600, 0)

    grid = nodes.new("GeometryNodeMeshGrid")
    grid.location = (-550, 100)
    grid.inputs["Size X"].default_value = grid_size
    grid.inputs["Size Y"].default_value = grid_size
    grid.inputs["Vertices X"].default_value = resolution
    grid.inputs["Vertices Y"].default_value = resolution

    pos = nodes.new("GeometryNodeInputPosition")
    pos.location = (-550, -160)

    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-350, -80)
    noise.inputs["Detail"].default_value = 8.0
    noise.inputs["Roughness"].default_value = 0.55
    if hasattr(noise, "noise_dimensions"):
        noise.noise_dimensions = "3D"

    mul = nodes.new("ShaderNodeMath")
    mul.location = (-150, -40)
    mul.operation = "MULTIPLY"

    comb = nodes.new("ShaderNodeCombineXYZ")
    comb.location = (50, -40)

    set_pos = nodes.new("GeometryNodeSetPosition")
    set_pos.location = (280, 40)

    smooth = nodes.new("GeometryNodeSetShadeSmooth")
    smooth.location = (460, 40)

    links.new(grid.outputs["Mesh"], set_pos.inputs["Geometry"])
    links.new(pos.outputs["Position"], noise.inputs["Vector"])
    links.new(n_in.outputs["Noise Scale"], noise.inputs["Scale"])
    links.new(noise.outputs["Fac"], mul.inputs[0])
    links.new(n_in.outputs["Height"], mul.inputs[1])
    links.new(mul.outputs["Value"], comb.inputs["Z"])
    links.new(comb.outputs["Vector"], set_pos.inputs["Offset"])
    links.new(set_pos.outputs["Geometry"], smooth.inputs["Geometry"])
    links.new(smooth.outputs["Geometry"], n_out.inputs["Geometry"])

    obj = _ensure_host(object_name, (0, 0, 0), size=0.5)
    _assign_modifier(obj, ng, {"Noise Scale": noise_scale, "Height": height})
    return {"ok": True, "object": obj.name, "tree": ng.name, **_stats(obj), "warnings": []}


def build_facade_extrude(params: Dict[str, Any]) -> Dict[str, Any]:
    width = float(params.get("width", 8.0))
    height = float(params.get("height", 12.0))
    cols = int(params.get("cols", 8))
    rows = int(params.get("rows", 12))
    extrude = float(params.get("extrude", 0.35))
    inset = float(params.get("inset", 0.85))
    object_name = str(params.get("object_name", "GN_Facade"))

    ng = _new_tree("GN_TPL_Facade")
    nodes, links = ng.nodes, ng.links

    _socket(ng, "Extrude", "INPUT", "NodeSocketFloat", extrude)
    _socket(ng, "Inset", "INPUT", "NodeSocketFloat", inset)
    _socket(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

    n_in = nodes.new("NodeGroupInput")
    n_in.location = (-700, 0)
    n_out = nodes.new("NodeGroupOutput")
    n_out.location = (650, 0)

    grid = nodes.new("GeometryNodeMeshGrid")
    grid.location = (-450, 80)
    grid.inputs["Size X"].default_value = width
    grid.inputs["Size Y"].default_value = height
    grid.inputs["Vertices X"].default_value = cols + 1
    grid.inputs["Vertices Y"].default_value = rows + 1

    xform = nodes.new("GeometryNodeTransform")
    xform.location = (-250, 80)
    xform.inputs["Rotation"].default_value = (1.5708, 0.0, 0.0)

    extr = nodes.new("GeometryNodeExtrudeMesh")
    extr.location = (0, 40)
    if hasattr(extr, "mode"):
        extr.mode = "FACES"
    if "Individual" in [s.name for s in extr.inputs]:
        extr.inputs["Individual"].default_value = True

    scale_el = nodes.new("GeometryNodeScaleElements")
    scale_el.location = (250, 40)
    if hasattr(scale_el, "domain"):
        scale_el.domain = "FACE"

    smooth = nodes.new("GeometryNodeSetShadeSmooth")
    smooth.location = (450, 40)
    smooth.inputs["Shade Smooth"].default_value = False

    links.new(grid.outputs["Mesh"], xform.inputs["Geometry"])
    links.new(xform.outputs["Geometry"], extr.inputs["Mesh"])
    links.new(n_in.outputs["Extrude"], extr.inputs["Offset Scale"])
    links.new(extr.outputs["Mesh"], scale_el.inputs["Geometry"])
    if "Top" in [s.name for s in extr.outputs]:
        links.new(extr.outputs["Top"], scale_el.inputs["Selection"])
    links.new(n_in.outputs["Inset"], scale_el.inputs["Scale"])
    links.new(scale_el.outputs["Geometry"], smooth.inputs["Geometry"])
    links.new(smooth.outputs["Geometry"], n_out.inputs["Geometry"])

    obj = _ensure_host(object_name, (0, -6, height / 2.0), size=0.2)
    _assign_modifier(obj, ng, {"Extrude": extrude, "Inset": inset})
    return {"ok": True, "object": obj.name, "tree": ng.name, **_stats(obj), "warnings": []}


def build_curve_railing(params: Dict[str, Any]) -> Dict[str, Any]:
    radius = float(params.get("radius", 3.0))
    rail_radius = float(params.get("rail_radius", 0.04))
    post_count = int(params.get("post_count", 24))
    post_height = float(params.get("post_height", 1.0))
    object_name = str(params.get("object_name", "GN_Railing"))

    ng = _new_tree("GN_TPL_Railing")
    nodes, links = ng.nodes, ng.links

    _socket(ng, "Radius", "INPUT", "NodeSocketFloat", radius)
    _socket(ng, "Rail Radius", "INPUT", "NodeSocketFloat", rail_radius)
    _socket(ng, "Post Count", "INPUT", "NodeSocketInt", post_count)
    _socket(ng, "Post Height", "INPUT", "NodeSocketFloat", post_height)
    _socket(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    _socket(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

    n_in = nodes.new("NodeGroupInput")
    n_in.location = (-900, 0)
    n_out = nodes.new("NodeGroupOutput")
    n_out.location = (750, 0)

    circle = nodes.new("GeometryNodeCurvePrimitiveCircle")
    circle.location = (-650, 160)
    circle.mode = "RADIUS"
    circle.inputs["Resolution"].default_value = 64

    profile = nodes.new("GeometryNodeCurvePrimitiveCircle")
    profile.location = (-650, 0)
    profile.mode = "RADIUS"
    profile.inputs["Resolution"].default_value = 12

    c2m = nodes.new("GeometryNodeCurveToMesh")
    c2m.location = (-400, 120)
    c2m.inputs["Fill Caps"].default_value = True

    comb_z = nodes.new("ShaderNodeCombineXYZ")
    comb_z.location = (-400, 280)
    xform_rail = nodes.new("GeometryNodeTransform")
    xform_rail.location = (-150, 120)

    c2p = nodes.new("GeometryNodeCurveToPoints")
    c2p.location = (-650, -280)
    if hasattr(c2p, "mode"):
        c2p.mode = "COUNT"

    cyl = nodes.new("GeometryNodeMeshCylinder")
    cyl.location = (-450, -480)
    cyl.inputs["Vertices"].default_value = 8
    cyl.inputs["Radius"].default_value = 0.03
    cyl.inputs["Depth"].default_value = 1.0

    xform_cyl = nodes.new("GeometryNodeTransform")
    xform_cyl.location = (-250, -480)

    comb_s = nodes.new("ShaderNodeCombineXYZ")
    comb_s.location = (-450, -620)
    comb_s.inputs["X"].default_value = 1.0
    comb_s.inputs["Y"].default_value = 1.0

    mul_h = nodes.new("ShaderNodeMath")
    mul_h.location = (-650, -700)
    mul_h.operation = "MULTIPLY"
    mul_h.inputs[1].default_value = 0.5

    comb_t = nodes.new("ShaderNodeCombineXYZ")
    comb_t.location = (-450, -720)

    iop = nodes.new("GeometryNodeInstanceOnPoints")
    iop.location = (-50, -300)

    realize = nodes.new("GeometryNodeRealizeInstances")
    realize.location = (200, -300)

    join = nodes.new("GeometryNodeJoinGeometry")
    join.location = (450, 40)

    links.new(n_in.outputs["Radius"], circle.inputs["Radius"])
    links.new(n_in.outputs["Rail Radius"], profile.inputs["Radius"])
    links.new(circle.outputs["Curve"], c2m.inputs["Curve"])
    links.new(profile.outputs["Curve"], c2m.inputs["Profile Curve"])
    links.new(n_in.outputs["Post Height"], comb_z.inputs["Z"])
    links.new(c2m.outputs["Mesh"], xform_rail.inputs["Geometry"])
    links.new(comb_z.outputs["Vector"], xform_rail.inputs["Translation"])

    links.new(circle.outputs["Curve"], c2p.inputs["Curve"])
    for s in c2p.inputs:
        if s.name == "Count":
            links.new(n_in.outputs["Post Count"], s)
            break

    links.new(n_in.outputs["Post Height"], comb_s.inputs["Z"])
    links.new(cyl.outputs["Mesh"], xform_cyl.inputs["Geometry"])
    links.new(comb_s.outputs["Vector"], xform_cyl.inputs["Scale"])
    links.new(n_in.outputs["Post Height"], mul_h.inputs[0])
    links.new(mul_h.outputs["Value"], comb_t.inputs["Z"])
    links.new(comb_t.outputs["Vector"], xform_cyl.inputs["Translation"])

    links.new(c2p.outputs["Points"], iop.inputs["Points"])
    links.new(xform_cyl.outputs["Geometry"], iop.inputs["Instance"])
    links.new(iop.outputs["Instances"], realize.inputs["Geometry"])
    links.new(xform_rail.outputs["Geometry"], join.inputs["Geometry"])
    links.new(realize.outputs["Geometry"], join.inputs["Geometry"])
    links.new(join.outputs["Geometry"], n_out.inputs["Geometry"])

    obj = _ensure_host(object_name, (0, 0, 0), size=0.2)
    _assign_modifier(
        obj,
        ng,
        {
            "Radius": radius,
            "Rail Radius": rail_radius,
            "Post Count": post_count,
            "Post Height": post_height,
        },
    )
    st = _stats(obj)
    warnings = []
    if st.get("evaluated_verts", 0) < 16:
        warnings.append("Low vertex count — railing may have failed to evaluate")
    return {"ok": True, "object": obj.name, "tree": ng.name, **st, "warnings": warnings}
