# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Installed Linux build smoke test; no network or account is required.

Run with a disposable profile and --background --factory-startup
--python-exit-code 1 --python tests/qa/linux_build_smoke.py.
MIXAR_SMOKE_OUT optionally selects the output directory.
"""

import json
import os
from pathlib import Path
import sys
import tempfile

import bpy
import keyring
import mcp
import truststore


def main():
    assert sys.platform.startswith("linux"), "This smoke test targets Linux"
    assert bpy.app.background, "Run in a disposable background process"
    out = Path(os.environ.get("MIXAR_SMOKE_OUT") or tempfile.mkdtemp(prefix="mixar-smoke-"))
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=False)
    scene = bpy.context.scene
    cube = bpy.data.objects["Cube"]
    material = bpy.data.materials.new("Linux smoke material")
    material.use_nodes = True
    texture = bpy.data.images.new("Linux smoke texture", width=64, height=64)
    texture.generated_color = (0.1, 0.6, 0.2, 1.0)
    texture_path = out / "texture.png"
    texture.save_render(filepath=str(texture_path))
    bpy.data.images.remove(texture)
    texture = bpy.data.images.load(str(texture_path))
    texture.name = "Linux smoke texture"
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = texture
    material.node_tree.nodes.active = node
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
    cube.data.materials.clear()
    cube.data.materials.append(material)
    texture.pack()
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 4
    scene.render.resolution_x = 128
    scene.render.resolution_y = 128
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(out / "render.png")
    blend = out / "linux-smoke.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), thumbnail=False)
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    cube = bpy.data.objects["Cube"]
    assert len(cube.data.polygons) == 6
    assert cube.data.materials[0].name == "Linux smoke material"
    assert tuple(bpy.data.images["Linux smoke texture"].size) == (64, 64)
    assert bpy.data.images["Linux smoke texture"].packed_file is not None
    bpy.ops.render.render(write_still=True)
    assert (out / "render.png").stat().st_size > 100
    verdict = {"version": bpy.app.version_string, "save_reopen": True,
               "packed_texture": True, "cycles_cpu_render": True,
               "runtime_imports": [keyring.__name__, mcp.__name__, truststore.__name__]}
    (out / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print("LINUX_SMOKE_OK", json.dumps(verdict), "artifacts:", out)


if __name__ == "__main__":
    main()
