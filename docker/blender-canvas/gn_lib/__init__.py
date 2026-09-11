"""Geometry Nodes template library for BlenderRemoteMCP (Blender 4.0)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .registry import TEMPLATE_META, TEMPLATE_IDS


def list_templates() -> List[Dict[str, Any]]:
    return [{"id": tid, **meta} for tid, meta in TEMPLATE_META.items()]


def _defaults(template_id: str) -> Dict[str, Any]:
    meta = TEMPLATE_META[template_id]
    params = {}
    for key, spec in (meta.get("parameters") or {}).items():
        if isinstance(spec, dict) and "default" in spec:
            params[key] = spec["default"]
    return params


def run(
    template_id: str,
    params: Optional[Dict[str, Any]] = None,
    object_name: Optional[str] = None,
) -> Dict[str, Any]:
    if template_id not in TEMPLATE_IDS:
        return {
            "ok": False,
            "error": f"Unknown template: {template_id}",
            "available": list(TEMPLATE_IDS),
        }
    resolved = _defaults(template_id)
    if params:
        resolved.update(params)
    if object_name:
        resolved["object_name"] = object_name
    try:
        from . import builders

        builders_map = {
            "scatter_poisson": builders.build_scatter_poisson,
            "terrain_displace": builders.build_terrain_displace,
            "facade_extrude": builders.build_facade_extrude,
            "curve_railing": builders.build_curve_railing,
        }
        data = builders_map[template_id](resolved)
        data.setdefault("ok", True)
        data["template"] = template_id
        return data
    except Exception as e:
        return {
            "ok": False,
            "template": template_id,
            "error": f"{type(e).__name__}: {e}",
        }
