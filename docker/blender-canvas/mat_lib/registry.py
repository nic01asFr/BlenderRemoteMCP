"""Material preset metadata (no bpy)."""

from __future__ import annotations

from typing import Any, Dict

PRESET_META: Dict[str, Dict[str, Any]] = {
    "concrete": {
        "name": "Concrete",
        "description": "Béton archviz — gris, roughness haute, micro-relief Noise.",
        "tags": ["archviz", "dielectric", "procedural"],
        "parameters": {
            "tint": {
                "type": "array",
                "default": [0.42, 0.42, 0.40, 1.0],
                "description": "Base Color RGBA",
            },
            "roughness": {"type": "number", "default": 0.82},
            "bump_strength": {"type": "number", "default": 0.15},
            "object_name": {"type": "string", "default": ""},
            "material_name": {"type": "string", "default": "MAT_Concrete"},
        },
    },
    "brushed_metal": {
        "name": "Brushed metal",
        "description": "Métal satiné — Metallic 1, roughness moyenne, légère anisotropy.",
        "tags": ["metal", "product"],
        "parameters": {
            "tint": {
                "type": "array",
                "default": [0.72, 0.74, 0.76, 1.0],
                "description": "Base Color RGBA",
            },
            "roughness": {"type": "number", "default": 0.35},
            "anisotropic": {"type": "number", "default": 0.25},
            "object_name": {"type": "string", "default": ""},
            "material_name": {"type": "string", "default": "MAT_BrushedMetal"},
        },
    },
    "glass_clear": {
        "name": "Clear glass",
        "description": "Verre — Transmission Weight 1, low roughness, IOR 1.45.",
        "tags": ["glass", "transmission"],
        "parameters": {
            "tint": {
                "type": "array",
                "default": [1.0, 1.0, 1.0, 1.0],
                "description": "Base Color RGBA",
            },
            "roughness": {"type": "number", "default": 0.02},
            "ior": {"type": "number", "default": 1.45},
            "object_name": {"type": "string", "default": ""},
            "material_name": {"type": "string", "default": "MAT_Glass"},
        },
    },
    "plastic_soft": {
        "name": "Soft plastic",
        "description": "Plastique produit studio — couleur vive, roughness douce, léger coat.",
        "tags": ["plastic", "product", "studio"],
        "parameters": {
            "tint": {
                "type": "array",
                "default": [0.15, 0.45, 0.85, 1.0],
                "description": "Base Color RGBA",
            },
            "roughness": {"type": "number", "default": 0.35},
            "coat_weight": {"type": "number", "default": 0.2},
            "object_name": {"type": "string", "default": ""},
            "material_name": {"type": "string", "default": "MAT_Plastic"},
        },
    },
    "terrain_grass": {
        "name": "Terrain grass",
        "description": "Sol herbe — verts variés via Noise, roughness haute.",
        "tags": ["terrain", "landscape", "procedural"],
        "parameters": {
            "tint_a": {
                "type": "array",
                "default": [0.12, 0.28, 0.08, 1.0],
                "description": "Couleur A",
            },
            "tint_b": {
                "type": "array",
                "default": [0.22, 0.38, 0.12, 1.0],
                "description": "Couleur B",
            },
            "noise_scale": {"type": "number", "default": 8.0},
            "roughness": {"type": "number", "default": 0.88},
            "object_name": {"type": "string", "default": ""},
            "material_name": {"type": "string", "default": "MAT_Grass"},
        },
    },
    "rubber_matte": {
        "name": "Matte rubber",
        "description": "Caoutchouc mat — sombre, roughness très haute.",
        "tags": ["rubber", "product"],
        "parameters": {
            "tint": {
                "type": "array",
                "default": [0.02, 0.02, 0.02, 1.0],
                "description": "Base Color RGBA",
            },
            "roughness": {"type": "number", "default": 0.95},
            "object_name": {"type": "string", "default": ""},
            "material_name": {"type": "string", "default": "MAT_Rubber"},
        },
    },
}

PRESET_IDS = frozenset(PRESET_META.keys())
