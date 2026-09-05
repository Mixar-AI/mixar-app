# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replayable GUI harness scenario. No backend or generation credits are used.

Load this module externally and call run(qa, output_directory), with scenarios.lib.QA.
The app must be an isolated QA instance; the fixture creates its own scene.
"""

from pathlib import Path


def run(qa, output_directory):
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if qa.find(text="Continue", popup=True)["total"]:
        qa.click(text="Continue", popup=True)
    fixture = qa.eval(
        "from mixar.modules.common.render_visibility.qa_scene import build_scene\n"
        "s = build_scene()\n"
        "s.render.image_settings.file_format = 'PNG'\n"
        f"s.render.filepath = {str(output / 'captured.png')!r}\n"
        "s['qa_collection_count'] = len(bpy.data.collections)\n"
        "result = list(s['visibility_qa_expected'])"
    )
    qa.eval("bpy.ops.render.render('INVOKE_DEFAULT', write_still=True, capture_visible_objects=True)")
    qa.wait("not bpy.app.is_job_running('RENDER') and "
            "__import__('json').loads(bpy.context.scene.render.visible_objects_json)['status'] "
            "in ('complete', 'error', 'cancelled')", timeout=60)
    result = qa.eval(
        "from mixar.modules.common.render_visibility.result import read_result\n"
        "s = bpy.context.scene\n"
        "r = read_result(s)\n"
        "actual = {o['name'] for o in r['objects']}\n"
        "assert actual == set(s['visibility_qa_expected']), (actual, list(s['visibility_qa_expected']))\n"
        "assert len(bpy.data.collections) == s['qa_collection_count'], 'Render created a collection'\n"
        "result = r"
    )
    qa.eval(
        "from mixar.modules.common.render_visibility.collect import create_collection\n"
        "s = bpy.context.scene\n"
        "c = create_collection(s, 'QA Rendered Meshes')\n"
        "assert {o.name for o in c.objects} == set(s['visibility_qa_expected'])\n"
        "assert all(len(o.users_collection) >= 2 for o in c.objects)\n"
        "s['qa_result_collection'] = c.name\n"
        f"bpy.ops.wm.save_as_mainfile(filepath={str(output / 'visibility-qa.blend')!r})\n"
        "result = c.name"
    )
    # Dismiss the isolated profile's startup splash, then present the actual result.
    qa.cmd("press", key="ESC")
    qa.eval(
        "window = drv.main_window()\n"
        "areas = sorted([a for a in window.screen.areas if a.type not in {'TOPBAR', 'STATUSBAR'}], "
        "key=lambda a: a.width * a.height, reverse=True)\n"
        "area = areas[0]\n"
        "area.type = 'IMAGE_EDITOR'\n"
        "area.spaces.active.image = bpy.data.images.get('Render Result')\n"
        "region = next(r for r in area.regions if r.type == 'WINDOW')\n"
        "with bpy.context.temp_override(window=window, area=area, region=region):\n"
        "    bpy.ops.image.view_all(fit_view=True)\n"
        "if len(areas) > 1:\n"
        "    areas[1].type = 'OUTLINER'\n"
        "    areas[1].spaces.active.display_mode = 'VIEW_LAYER'\n"
        f"bpy.ops.wm.save_as_mainfile(filepath={str(output / 'visibility-qa.blend')!r})"
    )
    # The new editor's regions must be laid out before the final fit.
    qa.eval(
        "window = drv.main_window()\n"
        "area = next(a for a in window.screen.areas if a.type == 'IMAGE_EDITOR')\n"
        "region = next(r for r in area.regions if r.type == 'WINDOW')\n"
        "with bpy.context.temp_override(window=window, area=area, region=region):\n"
        "    bpy.ops.image.view_all(fit_view=True)"
    )
    if any(w.get("block") == "splash" for w in qa.find(popup=True)["widgets"]):
        qa.click(text="File", but_type="Pulldown")
    qa.snap(str(output / "app.png"))
    return dict(expected=fixture, capture=result, render=str(output / "captured.png"),
                screenshot=str(output / "app.png"))
