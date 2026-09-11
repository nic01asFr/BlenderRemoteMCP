"""Baseline LOD1: GeoJSON footprints + height → bmesh extrude + mat_lib.

Runnable inside BlenderRemoteMCP execute_python (assign result=...).
Fixture equivalent: docs/experiments/gis-urban-lod/fixtures/blocks_lod1.geojson

This script is the smoke baseline BEFORE promoting to gn_lib.urban_lod1_extrude.
"""

from __future__ import annotations

# When executed via MCP, bpy/mat_lib are available in namespace or importable.
import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

if "/app" not in sys.path:
    sys.path.insert(0, "/app")
import mat_lib  # noqa: E402

USE_TO_PRESET = {
    "residential": "concrete",
    "office": "brushed_metal",
    "mixed": "concrete",
    "commercial": "plastic_soft",
}


def load_feature_collection(path: str | None = None, embedded: dict | None = None) -> dict:
    if embedded is not None:
        return embedded
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    raise ValueError("path or embedded FeatureCollection required")


def extrude_polygon(coords_xy, height: float, name: str):
    ring = coords_xy[:-1] if coords_xy[0] == coords_xy[-1] else coords_xy
    mesh = bpy.data.meshes.new(name + "_mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    verts = [bm.verts.new((float(x), float(y), 0.0)) for x, y in ring]
    bm.verts.ensure_lookup_table()
    face = bm.faces.new(verts)
    ret = bmesh.ops.extrude_discrete_faces(bm, faces=[face])
    extruded = ret["faces"]
    bmesh.ops.translate(
        bm,
        verts=list({v for f in extruded for v in f.verts}),
        vec=(0.0, 0.0, float(height)),
    )
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return obj


def build_lod1(fc: dict, clear_prefix: str = "LOD1_") -> dict:
    for obj in list(bpy.data.objects):
        if obj.name.startswith(clear_prefix):
            bpy.data.objects.remove(obj, do_unlink=True)

    built = []
    for feat in fc["features"]:
        props = feat["properties"]
        geom = feat["geometry"]
        if geom["type"] != "Polygon":
            continue
        ring = geom["coordinates"][0]
        bid = str(props["id"])
        h = float(props["height"])
        obj = extrude_polygon(ring, h, f"{clear_prefix}{bid}")
        obj["lod_id"] = bid
        obj["lod_height"] = h
        obj["lod_use"] = props.get("use", "")
        obj["lod_roof"] = props.get("roof", "")
        preset = USE_TO_PRESET.get(props.get("use"), "concrete")
        mat_res = mat_lib.apply(
            preset, object_name=obj.name, params={"material_name": f"MAT_LOD_{bid}"}
        )
        zs = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        zmin, zmax = min(v.z for v in zs), max(v.z for v in zs)
        built.append(
            {
                "id": bid,
                "object": obj.name,
                "height_attr": h,
                "height_bbox": round(zmax - zmin, 3),
                "preset": preset,
                "mat_ok": bool(mat_res.get("ok")),
                "verts": len(obj.data.vertices),
            }
        )

    if f"{clear_prefix}Ground" in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[f"{clear_prefix}Ground"], do_unlink=True)
    bpy.ops.mesh.primitive_plane_add(size=80, location=(31, 16, -0.01))
    gnd = bpy.context.active_object
    gnd.name = f"{clear_prefix}Ground"
    mat_lib.apply(
        "terrain_grass",
        object_name=gnd.name,
        params={"material_name": "MAT_LOD_Ground"},
    )

    cam = bpy.data.objects.get("Camera")
    if cam:
        target = Vector((31, 14, 6))
        cam.location = (85, -70, 55)
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        if cam.data:
            cam.data.lens = 35
            cam.data.clip_end = 500
        bpy.context.scene.camera = cam

    bpy.context.view_layer.update()
    ok_heights = all(abs(b["height_bbox"] - b["height_attr"]) < 0.05 for b in built)
    return {
        "ok": True,
        "method": "bmesh_extrude_baseline",
        "buildings": len(built),
        "heights_match": ok_heights,
        "built": built,
    }


# MCP entry: embed fixture so no filesystem dependency in pod
_EMBEDDED = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"id": "B1", "height": 12.0, "roof": "flat", "use": "residential"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [18, 0], [18, 10], [0, 10], [0, 0]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"id": "B2", "height": 18.5, "roof": "flat", "use": "office"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[22, 0], [40, 0], [40, 14], [22, 14], [22, 0]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"id": "B3", "height": 9.0, "roof": "gable", "use": "residential"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[5, 16], [25, 16], [25, 28], [5, 28], [5, 16]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"id": "B4", "height": 24.0, "roof": "flat", "use": "mixed"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[30, 18], [48, 18], [48, 32], [36, 32], [36, 26], [30, 26], [30, 18]]
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {"id": "B5", "height": 6.0, "roof": "flat", "use": "commercial"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[50, 0], [62, 0], [62, 8], [50, 8], [50, 0]]],
            },
        },
    ],
}

if __name__ == "__main__" or "bpy" in dir():
    # When pasted into execute_python without __main__, caller should call build_lod1.
    pass
