# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Additional real-render checks for the fixture; called by qa_e2e, outside Blender."""
from pathlib import Path


def run(qa, output_directory):
    output = Path(output_directory)
    code = (
        "import json\n"
        "from mixar.modules.common.render_visibility.result import read_result\n"
        "s = bpy.context.scene\n"
        "expected = set(s['visibility_qa_expected'])\n"
        "collection_count = len(bpy.data.collections)\n"
        f"s.render.filepath = {str(output / 'disabled.png')!r}\n"
        "assert bpy.ops.render.render(write_still=True) == {'FINISHED'}\n"
        "assert json.loads(s.render.visible_objects_json)['status'] == 'disabled'\n"
        "assert bpy.ops.render.render(capture_visible_objects=True) == {'FINISHED'}\n"
        "assert {o['name'] for o in read_result(s)['objects']} == expected\n"
        "meshes = [o for o in s.objects if o.type == 'MESH']\n"
        "hidden = {o: o.hide_render for o in meshes}\n"
        "try:\n"
        "    for o in meshes: o.hide_render = True\n"
        "    bpy.ops.render.render(capture_visible_objects=True)\n"
        "    assert read_result(s)['objects'] == []\n"
        "finally:\n"
        "    for o, state in hidden.items(): o.hide_render = state\n"
        "wall = next(o for o in s.objects if o.name.startswith('QA_TransparentWall'))\n"
        "mat = wall.data.materials[0]\n"
        "method = mat.surface_render_method\n"
        "try:\n"
        "    mat.surface_render_method = 'BLENDED'\n"
        "    bpy.ops.render.render(capture_visible_objects=True)\n"
        "    failed = json.loads(s.render.visible_objects_json)\n"
        "    assert failed['status'] == 'error' and failed['objects'] == [], failed\n"
        "finally:\n"
        "    mat.surface_render_method = method\n"
        "blocker = next(o for o in s.objects if o.name.startswith('QA_Blocker'))\n"
        "original_x = blocker.location.x\n"
        "try:\n"
        "    blocker.location.x = 20\n"
        "    bpy.ops.render.render(capture_visible_objects=True)\n"
        "    exposed = {o['name'] for o in read_result(s)['objects']}\n"
        "    unblocked = {o.name for o in s.objects if o.name.startswith(('QA_HiddenInside', 'QA_HiddenBehind'))}\n"
        "    assert exposed == (expected - {blocker.name}) | unblocked, exposed\n"
        "finally:\n"
        "    blocker.location.x = original_x\n"
        f"s.render.filepath = {str(output / 'captured.png')!r}\n"
        "bpy.ops.render.render(write_still=True, capture_visible_objects=True)\n"
        "assert {o['name'] for o in read_result(s)['objects']} == expected\n"
        "assert len(bpy.data.collections) == collection_count\n"
        "result = {'blocking_render': True, 'capture_disabled': True, 'empty_capture': True, "
        "'blended_rejected': True, 'occluder_moved': True}"
    )
    result = qa.cmd("eval", code=code, _sock_timeout=60)
    from PIL import Image
    with Image.open(output / "captured.png") as captured, Image.open(output / "disabled.png") as disabled:
        assert captured.convert("RGBA").tobytes() == disabled.convert("RGBA").tobytes()
    result["image_pixels_unchanged"] = True
    return result
