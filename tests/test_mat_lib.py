"""mat_lib registry (no Blender required)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docker" / "blender-canvas"))

from mat_lib.registry import PRESET_IDS, PRESET_META  # noqa: E402
from mat_lib import list_presets  # noqa: E402


def test_presets_registered():
    assert len(PRESET_IDS) == 6
    for pid in (
        "concrete",
        "brushed_metal",
        "glass_clear",
        "plastic_soft",
        "terrain_grass",
        "rubber_matte",
    ):
        assert pid in PRESET_IDS
        assert PRESET_META[pid].get("name")


def test_list_presets_shape():
    items = list_presets()
    assert len(items) == 6
    assert {i["id"] for i in items} == set(PRESET_IDS)
