# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Local object assets and generated-media records for the Library QA replay."""


def install(qa, out):
    qa.eval(f'''import os, colorsys, math
from pathlib import Path
assert os.environ.get("MIXAR_QA") == "1"
assert not drv.main_window().scene.mixie_chat_is_busy
bpy.context.preferences.view.show_tooltips = False
root = Path({str(out / "fixtures")!r})
root.mkdir(parents=True, exist_ok=True)
objects = set()
for i in range(24):
    mesh = bpy.data.meshes.new(f"QA Library Mesh {{i:02d}}")
    mesh.from_pydata([(-1,-1,0), (1,-1,0), (1,1,0), (-1,1,0), (0,0,2)],
                     [], [(0,1,2,3), (0,1,4), (1,2,4), (2,3,4), (3,0,4)])
    obj = bpy.data.objects.new(f"QA Asset {{i:02d}}", mesh)
    obj.asset_mark()
    preview = obj.preview_ensure()
    preview.image_size = (48,48)
    rgb = colorsys.hsv_to_rgb(i/24, .65, .85)
    pixels = []
    for y in range(48):
        for x in range(48):
            radius = ((x-23.5)/22)**2 + ((y-23.5)/22)**2
            light = .3 + .7*math.sqrt(max(0, 1-radius))
            pixels.extend((*[c*light for c in rgb], 1) if radius < 1 else (.08,.08,.08,1))
    preview.image_pixels_float = pixels
    objects.add(obj)
bpy.data.libraries.write(str(root / "assets.blend"), objects, fake_user=True)
for obj in objects:
    bpy.data.objects.remove(obj)
bpy.ops.preferences.asset_library_add(directory=str(root))
bpy.context.preferences.filepaths.asset_libraries[-1].name = "QA Responsive Library"
scene = drv.main_window().scene
for i in range(3):
    image = bpy.data.images.new(f"QA Generated Image {{i}}", width=64, height=64)
    image.generated_color = (0.1 + i*.15, .35, .55, 1)
    image.filepath_raw = str(root / f"image-{{i}}.png")
    image.file_format = "PNG"
    image.save()
    item = scene.mixie_moodboard_images.add()
    item.image = image
    item.generation_prompt = "Local QA fixture: a blue material study with a deliberately long prompt."
    item.mixar_created_at_iso = f"2026-09-{{20+i:02d}}T10:00:00Z"
    item.selected = False
with bpy.context.temp_override(window=drv.main_window()):
    bpy.ops.mixar.agent_bubble_show_window()
wm = bpy.context.window_manager
wm.mixar_generations_library = "QA Responsive Library"
wm.mixar_generations_source = "LIBRARY"
wm.mixar_generations_filter = "ALL"
wm.mixar_bubble_tab = "AGENT"
result = True''')
