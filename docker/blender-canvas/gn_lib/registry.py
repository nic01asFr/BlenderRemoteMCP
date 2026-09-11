"""Template metadata (no bpy — unit-testable)."""

from __future__ import annotations

from typing import Any, Dict

TEMPLATE_META: Dict[str, Dict[str, Any]] = {
    "scatter_poisson": {
        "name": "Scatter Poisson (instances)",
        "description": (
            "Distribution Poisson sur grille, instances IcoSphere, "
            "rotation aléatoire, RealizeInstances — look vegetation/debris."
        ),
        "tags": ["scatter", "instances", "poisson"],
        "parameters": {
            "density_max": {"type": "number", "default": 40.0},
            "distance_min": {"type": "number", "default": 0.25},
            "instance_scale": {"type": "number", "default": 0.12},
            "grid_size": {"type": "number", "default": 6.0},
            "seed": {"type": "integer", "default": 1},
            "object_name": {"type": "string", "default": "GN_Scatter"},
        },
    },
    "terrain_displace": {
        "name": "Terrain noise displace",
        "description": (
            "MeshGrid haute densité + Noise → Set Position Z + shade smooth. "
            "Terrain procédural de base."
        ),
        "tags": ["terrain", "noise", "landscape"],
        "parameters": {
            "grid_size": {"type": "number", "default": 12.0},
            "resolution": {"type": "integer", "default": 128},
            "noise_scale": {"type": "number", "default": 0.35},
            "height": {"type": "number", "default": 1.8},
            "object_name": {"type": "string", "default": "GN_Terrain"},
        },
    },
    "facade_extrude": {
        "name": "Facade panel extrude",
        "description": (
            "Grille → ExtrudeMesh individual + Scale Elements — "
            "panneaux type façade / city block."
        ),
        "tags": ["archviz", "facade", "extrude"],
        "parameters": {
            "width": {"type": "number", "default": 8.0},
            "height": {"type": "number", "default": 12.0},
            "cols": {"type": "integer", "default": 8},
            "rows": {"type": "integer", "default": 12},
            "extrude": {"type": "number", "default": 0.35},
            "inset": {"type": "number", "default": 0.85},
            "object_name": {"type": "string", "default": "GN_Facade"},
        },
    },
    "curve_railing": {
        "name": "Curve railing / balustrade",
        "description": (
            "Courbe circulaire + profil + poteaux Instance on Points — "
            "garde-corps paramétrique."
        ),
        "tags": ["curve", "railing", "archviz"],
        "parameters": {
            "radius": {"type": "number", "default": 3.0},
            "rail_radius": {"type": "number", "default": 0.04},
            "post_count": {"type": "integer", "default": 24},
            "post_height": {"type": "number", "default": 1.0},
            "object_name": {"type": "string", "default": "GN_Railing"},
        },
    },
}

TEMPLATE_IDS = frozenset(TEMPLATE_META.keys())
