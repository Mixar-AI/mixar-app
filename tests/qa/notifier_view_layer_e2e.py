# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit notifier lifecycle smoke replay for an isolated running Mac QA app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4788 \
QA_SCENARIO_OUT=/tmp/notifier-qa python3 tests/qa/notifier_view_layer_e2e.py

Uses real scene-card clicks and window/file operators. Never run against a
personal profile: requires MIXAR_QA=1 inside the app. A pass is NOT proof that
the intermittent historical crash is fixed; the native regression separately
compares the original callback lookup with the window-specific implementation.
Review every captured PNG after the state verdict. No model/generation calls.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/notifier-qa')).resolve()


def frame_scene(qa):
    qa.eval("""
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.view3d.view_all(center=False)
""")


def fixture(qa):
    assert qa.eval("import os; result = os.environ.get('MIXAR_QA') == '1'")
    assert not qa.status()['busy']
    qa.eval("""
w = drv.main_window()
for scene in list(bpy.data.scenes):
    if scene != w.scene and scene.name.startswith('QA1878_'):
        bpy.data.scenes.remove(scene)
w.scene.name = 'QA1878_A'
for obj in list(w.scene.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
w.scene.view_layers[0].name = 'QA1878_Layer_A'
with bpy.context.temp_override(window=w):
    bpy.ops.mesh.primitive_cube_add(size=2)
    bpy.context.object.name = 'QA1878_Cube_A'
result = w.scene.name
""")
    if not qa.find(surface='scenes_drawer_new')['total']:
        qa.click(op='VIEW3D_OT_scenes_drawer_toggle')
    qa.wait("bool(drv.find(surface='scenes_drawer_new'))", timeout=10)
    qa.click(surface='scenes_drawer_new')
    qa.wait("drv.main_window().scene.name != 'QA1878_A'", timeout=10)
    qa.eval("""
w = drv.main_window()
w.scene.name = 'QA1878_B'
w.scene.view_layers[0].name = 'QA1878_Layer_B'
with bpy.context.temp_override(window=w):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.5)
    bpy.context.object.name = 'QA1878_Sphere_B'
""")
    frame_scene(qa)


def check_scene(qa, name):
    qa.wait(f"drv.main_window().scene.name == {name!r}", timeout=10)
    suffix = name[-1]
    expected = 'QA1878_Cube_A' if suffix == 'A' else 'QA1878_Sphere_B'
    assert qa.eval(f"""
w = drv.main_window()
result = ({expected!r} in w.scene.objects and
          w.view_layer.name == 'QA1878_Layer_{suffix}' and
          len(w.scene.objects[{expected!r}].data.vertices) > 0)
""")
    assert qa.cmd('ping')['pong']


def switch_scenes(qa):
    for _ in range(3):
        for name in ('QA1878_A', 'QA1878_B'):
            qa.click(surface='scenes_drawer_card', text=name)
            check_scene(qa, name)
    frame_scene(qa)


def window_lifecycle(qa):
    for _ in range(3):
        before = qa.eval('result = [w.as_pointer() for w in bpy.context.window_manager.windows]')
        qa.eval("""
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.wm.window_new_main() == {'FINISHED'}
""")
        qa.wait(f"len(bpy.context.window_manager.windows) == {len(before) + 1}", timeout=15)
        new = qa.eval(f"result = [w.as_pointer() for w in bpy.context.window_manager.windows if w.as_pointer() not in {before!r}]")
        assert len(new) == 1
        for name in ('QA1878_A', 'QA1878_B'):
            qa.eval(f"""
w = next(w for w in bpy.context.window_manager.windows if w.as_pointer() == {new[0]})
w.scene = bpy.data.scenes[{name!r}]
w.scene.frame_set(w.scene.frame_current + 1)
""")
            layer = 'QA1878_Layer_' + name[-1]
            qa.wait(f"any(w.as_pointer() == {new[0]} and w.scene.name == {name!r} and w.view_layer.name == {layer!r} for w in bpy.context.window_manager.windows)", timeout=10)
        qa.eval(f"""
w = next(w for w in bpy.context.window_manager.windows if w.as_pointer() == {new[0]})
with bpy.context.temp_override(window=w):
    assert bpy.ops.wm.window_close() == {{'FINISHED'}}
""")
        # Re-query after closing; never dereference retained window RNA.
        qa.wait(f"len(bpy.context.window_manager.windows) == {len(before)}", timeout=10)
        assert qa.cmd('ping')['pong']


def reload_file(qa):
    path = str(OUT / 'notifier-lifecycle.mixar')
    qa.eval(f"""
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.wm.save_as_mainfile(filepath={path!r}, check_existing=False) == {{'FINISHED'}}
""")
    for load_ui in (True, False, True):
        qa.eval(f"""
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.wm.open_mainfile(filepath={path!r}, load_ui={load_ui!r}) == {{'FINISHED'}}
""")
        qa.wait("'QA1878_A' in bpy.data.scenes and 'QA1878_B' in bpy.data.scenes", timeout=20)
        assert qa.eval("result = 'QA1878_Cube_A' in bpy.data.scenes['QA1878_A'].objects and 'QA1878_Sphere_B' in bpy.data.scenes['QA1878_B'].objects")
        assert qa.cmd('ping')['pong']


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    qa = QA()
    verdict = {'passed': False, 'scope': 'lifecycle smoke; historical crash trigger unknown'}
    try:
        qa.step('isolated two-scene fixture', fixture, qa)
        qa.snap(str(OUT / '01-scenes.png'))
        qa.step('six real scene-card switches with distinct view layers', switch_scenes, qa)
        qa.snap(str(OUT / '02-switched.png'))
        qa.step('three main-window create/switch/close cycles', window_lifecycle, qa)
        qa.snap(str(OUT / '03-window-closed.png'))
        qa.step('three saved-file reloads with and without UI', reload_file, qa)
        frame_scene(qa)
        qa.snap(str(OUT / '04-reloaded.png'))
        verdict['passed'] = True
        verdict['app'] = qa.cmd('ping')
    finally:
        verdict['steps'] = qa.log
        verdict['screenshots'] = [p.name for p in sorted(OUT.glob('*.png'))]
        (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
