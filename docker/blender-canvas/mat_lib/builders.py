"""Principled BSDF preset builders (Blender 4.0.2)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import bpy


def _rgba(val, default=(0.8, 0.8, 0.8, 1.0)) -> Tuple[float, float, float, float]:
    if val is None:
        return default
    if isinstance(val, (list, tuple)) and len(val) >= 3:
        r, g, b = float(val[0]), float(val[1]), float(val[2])
        a = float(val[3]) if len(val) > 3 else 1.0
        return (r, g, b, a)
    return default


def _ensure_material(name: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    return mat


def _principled(nt) -> bpy.types.ShaderNode:
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return bsdf


def _set(bsdf, name: str, value) -> None:
    if name in bsdf.inputs:
        bsdf.inputs[name].default_value = value


def _assign(obj_name: str, mat: bpy.types.Material) -> Optional[str]:
    if not obj_name:
        return None
    obj = bpy.data.objects.get(obj_name)
    if obj is None or not getattr(obj, "data", None) or not hasattr(obj.data, "materials"):
        return f"object not found or not material-capable: {obj_name}"
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    return None


def _result(mat: bpy.types.Material, object_name: str, warning: Optional[str] = None) -> Dict[str, Any]:
    out = {
        "ok": True,
        "material": mat.name,
        "object": object_name or None,
        "users": int(mat.users),
        "warnings": [warning] if warning else [],
    }
    return out


def build_concrete(params: Dict[str, Any]) -> Dict[str, Any]:
    name = str(params.get("material_name") or "MAT_Concrete")
    tint = _rgba(params.get("tint"), (0.42, 0.42, 0.40, 1.0))
    roughness = float(params.get("roughness", 0.82))
    bump_strength = float(params.get("bump_strength", 0.15))
    object_name = str(params.get("object_name") or "")

    mat = _ensure_material(name)
    nt = mat.node_tree
    bsdf = _principled(nt)
    _set(bsdf, "Base Color", tint)
    _set(bsdf, "Roughness", roughness)
    _set(bsdf, "Metallic", 0.0)

    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.location = (-500, -80)
    tex.inputs["Scale"].default_value = 12.0
    tex.inputs["Detail"].default_value = 8.0
    tex.inputs["Roughness"].default_value = 0.6

    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (-220, -80)
    bump.inputs["Strength"].default_value = bump_strength
    nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    warn = _assign(object_name, mat)
    return _result(mat, object_name, warn)


def build_brushed_metal(params: Dict[str, Any]) -> Dict[str, Any]:
    name = str(params.get("material_name") or "MAT_BrushedMetal")
    tint = _rgba(params.get("tint"), (0.72, 0.74, 0.76, 1.0))
    roughness = float(params.get("roughness", 0.35))
    anisotropic = float(params.get("anisotropic", 0.25))
    object_name = str(params.get("object_name") or "")

    mat = _ensure_material(name)
    bsdf = _principled(mat.node_tree)
    _set(bsdf, "Base Color", tint)
    _set(bsdf, "Metallic", 1.0)
    _set(bsdf, "Roughness", roughness)
    _set(bsdf, "Anisotropic", anisotropic)
    warn = _assign(object_name, mat)
    return _result(mat, object_name, warn)


def build_glass_clear(params: Dict[str, Any]) -> Dict[str, Any]:
    name = str(params.get("material_name") or "MAT_Glass")
    tint = _rgba(params.get("tint"), (1.0, 1.0, 1.0, 1.0))
    roughness = float(params.get("roughness", 0.02))
    ior = float(params.get("ior", 1.45))
    object_name = str(params.get("object_name") or "")

    mat = _ensure_material(name)
    # Cycles: transmission via Principled. EEVEE may need blend settings.
    mat.blend_method = "HASHED"
    mat.shadow_method = "HASHED"
    bsdf = _principled(mat.node_tree)
    _set(bsdf, "Base Color", tint)
    _set(bsdf, "Roughness", roughness)
    _set(bsdf, "IOR", ior)
    _set(bsdf, "Transmission Weight", 1.0)
    _set(bsdf, "Metallic", 0.0)
    warn = _assign(object_name, mat)
    return _result(mat, object_name, warn)


def build_plastic_soft(params: Dict[str, Any]) -> Dict[str, Any]:
    name = str(params.get("material_name") or "MAT_Plastic")
    tint = _rgba(params.get("tint"), (0.15, 0.45, 0.85, 1.0))
    roughness = float(params.get("roughness", 0.35))
    coat = float(params.get("coat_weight", 0.2))
    object_name = str(params.get("object_name") or "")

    mat = _ensure_material(name)
    bsdf = _principled(mat.node_tree)
    _set(bsdf, "Base Color", tint)
    _set(bsdf, "Roughness", roughness)
    _set(bsdf, "Metallic", 0.0)
    _set(bsdf, "Coat Weight", coat)
    _set(bsdf, "Coat Roughness", 0.2)
    warn = _assign(object_name, mat)
    return _result(mat, object_name, warn)


def build_terrain_grass(params: Dict[str, Any]) -> Dict[str, Any]:
    name = str(params.get("material_name") or "MAT_Grass")
    tint_a = _rgba(params.get("tint_a"), (0.12, 0.28, 0.08, 1.0))
    tint_b = _rgba(params.get("tint_b"), (0.22, 0.38, 0.12, 1.0))
    noise_scale = float(params.get("noise_scale", 8.0))
    roughness = float(params.get("roughness", 0.88))
    object_name = str(params.get("object_name") or "")

    mat = _ensure_material(name)
    nt = mat.node_tree
    bsdf = _principled(nt)
    _set(bsdf, "Roughness", roughness)
    _set(bsdf, "Metallic", 0.0)

    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.location = (-550, 80)
    noise.inputs["Scale"].default_value = noise_scale
    noise.inputs["Detail"].default_value = 6.0

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-320, 80)
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = tint_a
    ramp.color_ramp.elements[1].position = 0.75
    ramp.color_ramp.elements[1].color = tint_b

    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (-200, -120)
    bump.inputs["Strength"].default_value = 0.25

    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    warn = _assign(object_name, mat)
    return _result(mat, object_name, warn)


def build_rubber_matte(params: Dict[str, Any]) -> Dict[str, Any]:
    name = str(params.get("material_name") or "MAT_Rubber")
    tint = _rgba(params.get("tint"), (0.02, 0.02, 0.02, 1.0))
    roughness = float(params.get("roughness", 0.95))
    object_name = str(params.get("object_name") or "")

    mat = _ensure_material(name)
    bsdf = _principled(mat.node_tree)
    _set(bsdf, "Base Color", tint)
    _set(bsdf, "Roughness", roughness)
    _set(bsdf, "Metallic", 0.0)
    _set(bsdf, "Sheen Weight", 0.1)
    warn = _assign(object_name, mat)
    return _result(mat, object_name, warn)


BUILDERS = {
    "concrete": build_concrete,
    "brushed_metal": build_brushed_metal,
    "glass_clear": build_glass_clear,
    "plastic_soft": build_plastic_soft,
    "terrain_grass": build_terrain_grass,
    "rubber_matte": build_rubber_matte,
}
