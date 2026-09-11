"""gn_lib registry (no Blender required)."""

import sys
from pathlib import Path

# Allow importing docker/blender-canvas/gn_lib in tests
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "blender-canvas"))

from gn_lib.registry import TEMPLATE_IDS, TEMPLATE_META  # noqa: E402
from gn_lib import list_templates  # noqa: E402


def test_templates_registered():
    assert "scatter_poisson" in TEMPLATE_IDS
    assert "terrain_displace" in TEMPLATE_IDS
    assert "facade_extrude" in TEMPLATE_IDS
    assert "curve_railing" in TEMPLATE_IDS
    for tid, meta in TEMPLATE_META.items():
        assert meta.get("name")
        assert "parameters" in meta


def test_list_templates_shape():
    items = list_templates()
    assert len(items) == 4
    assert {i["id"] for i in items} == set(TEMPLATE_IDS)
