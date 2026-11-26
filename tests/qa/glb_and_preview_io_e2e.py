#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Replay in an isolated Mixar QA instance with these Python modules installed."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario


def run(qa):
    out = Path(os.environ["QA_SCENARIO_OUT"]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.step("export, scrub and reimport a mesh", qa.eval, f"""
import os
assert os.environ.get("MIXAR_QA") == "1"
from mixar.modules.common.gltf_import import import_gltf
from mixar.modules.space_mixie_chat.core.export_extras_filter import strip_private_extras
from mixar.modules.space_mixie_chat.core.export_verify import read_glb_json
path = {str(out / "round-trip.glb")!r}
with bpy.context.temp_override(window=drv.main_window()):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2)
    original = bpy.context.object
    original.name = "QA GLB round trip"
    original["mixar_qa_private"] = "private"
    original["qa_public"] = "retained"
    faces = len(original.data.polygons)
    assert bpy.ops.export_scene.gltf(filepath=path, use_selection=True, export_extras=True) == {{"FINISHED"}}
    assert strip_private_extras(path, "glb") > 0
    extras = next(n["extras"] for n in read_glb_json(path)["nodes"] if n.get("name") == original.name)
    assert extras["qa_public"] == "retained" and "mixar_qa_private" not in extras
    bpy.data.objects.remove(original, do_unlink=True)
    scenes = len(bpy.data.scenes)
    assert import_gltf(path) == {{"FINISHED"}}
    obj = bpy.data.objects["QA GLB round trip"]
    assert len(bpy.data.scenes) == scenes and len(obj.data.polygons) == faces, (scenes, len(bpy.data.scenes), faces, len(obj.data.polygons))
    assert obj["qa_public"] == "retained" and "mixar_qa_private" not in obj
result = faces
""")
    qa.step("compare live dirty-image pixels", qa.eval, """
from mixar.modules.common.render_worker import snapshot
from tempfile import TemporaryDirectory
img = bpy.data.images.new("QA snapshot pixels", 64, 64)
try:
    with TemporaryDirectory() as directory:
        _, keys = snapshot._write_images([img], directory)
        assert snapshot._images_match([img], keys)
        img.pixels[0] = 1.0 - img.pixels[0]
        assert not snapshot._images_match([img], keys)
finally:
    bpy.data.images.remove(img)
result = True
""")
    qa.snap(str(out / "round-trip.png"))


if __name__ == "__main__":
    run_scenario("glb_and_preview_io", run)
