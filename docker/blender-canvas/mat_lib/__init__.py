"""Material preset library for BlenderRemoteMCP (Blender 4.0)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .registry import PRESET_IDS, PRESET_META


def list_presets() -> List[Dict[str, Any]]:
    return [{"id": pid, **meta} for pid, meta in PRESET_META.items()]


def _defaults(preset_id: str) -> Dict[str, Any]:
    meta = PRESET_META[preset_id]
    params = {}
    for key, spec in (meta.get("parameters") or {}).items():
        if isinstance(spec, dict) and "default" in spec:
            params[key] = spec["default"]
    return params


def apply(
    preset_id: str,
    object_name: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if preset_id not in PRESET_IDS:
        return {
            "ok": False,
            "error": f"Unknown preset: {preset_id}",
            "available": sorted(PRESET_IDS),
        }
    resolved = _defaults(preset_id)
    if params:
        resolved.update(params)
    if object_name:
        resolved["object_name"] = object_name
    try:
        from .builders import BUILDERS

        data = BUILDERS[preset_id](resolved)
        data.setdefault("ok", True)
        data["preset"] = preset_id
        return data
    except Exception as e:
        return {
            "ok": False,
            "preset": preset_id,
            "error": f"{type(e).__name__}: {e}",
        }


# Alias for symmetry with gn_lib.run
run = apply
