"""Validation fixtures GIS urban LOD (pas de Blender)."""

import json
from pathlib import Path

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "experiments"
    / "gis-urban-lod"
    / "fixtures"
    / "blocks_lod1.geojson"
)


def test_blocks_lod1_fixture_contract():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) >= 3
    for feat in data["features"]:
        props = feat["properties"]
        assert "id" in props
        assert "height" in props
        assert float(props["height"]) > 0
        assert feat["geometry"]["type"] == "Polygon"
        ring = feat["geometry"]["coordinates"][0]
        assert len(ring) >= 4
        assert ring[0] == ring[-1]


def test_fixture_heights_unique_ids():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ids = [f["properties"]["id"] for f in data["features"]]
    assert len(ids) == len(set(ids))
