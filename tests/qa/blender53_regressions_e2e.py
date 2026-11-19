# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free Blender 5.3 compatibility replay against an isolated QA app.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. The replay changes
only the harness's disposable document. Pair it with packed_image_undo_e2e.py
and the harness's startup/UI smoke cases. Screenshots require visual review.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario


API_CHECKS = '''
import os
assert os.environ.get("MIXAR_QA") == "1", "Requires an isolated QA app"
assert bpy.app.version[:2] == (5, 3), bpy.app.version_string
w = drv.main_window()
scene = w.scene
# Reassign binary custom properties, including embedded NULs and an empty value.
# This exercises the retained native ID-property fix, not a Python wrapper.
for value in (b"old", b"a\\x00b\\x00", b"", b"\\x00tail"):
    scene["qa_binary"] = value
    assert scene["qa_binary"] == value, (scene["qa_binary"], value)

# Slot assignment must work on a new armature before a dependency-graph update.
armature = bpy.data.armatures.new("QA 5.3 armature")
obj = bpy.data.objects.new("QA 5.3 fresh rig", armature)
action = bpy.data.actions.new("QA 5.3 action")
slot = action.slots.new(id_type="OBJECT", name=obj.name)
animation = obj.animation_data_create()
animation.action = action
animation.action_slot = slot
assert animation.action_slot == slot

required = {"SpaceMixie", "SpaceAgentBubble", "SpaceMixarLayers",
            "SpaceMixarProperties", "SpaceMixarAssets", "SpaceBaking",
            "SpaceTextureSets", "SpaceProject"}
assert all(hasattr(bpy.types, name) for name in required)
from mixar.modules.paint.ui.properties.named_item_properties import MPaintNamedItem
bpy.types.WindowManager.qa53_named_items = bpy.props.CollectionProperty(type=MPaintNamedItem)
try:
    item = bpy.context.window_manager.qa53_named_items.add()
    item.name = "QA writable search item"
    assert item.name == "QA writable search item"
finally:
    del bpy.types.WindowManager.qa53_named_items
result = {"version": bpy.app.version_string, "blender": list(bpy.app.version),
          "binary": list(scene["qa_binary"]),
          "spaces": sorted(required), "slot": animation.action_slot.name_display}
'''


def check_legacy_filters(qa):
    """Optional files saved by a 5.2 QA process: prefix-hidden/shown.mixar."""
    prefix = os.environ.get("MIXAR_QA_LEGACY_LAYERS")
    if not prefix:
        return {"status": "SKIPPED", "reason": "Set MIXAR_QA_LEGACY_LAYERS to 5.2 fixture prefix"}
    rows = []
    for suffix, expected in (("hidden", False), ("shown", True)):
        path = str(Path(prefix + "-" + suffix + ".mixar").resolve())
        assert Path(path).is_file(), path
        qa.eval(f"bpy.ops.wm.open_mainfile(filepath={path!r})\nresult=True")
        qa.wait("bool(drv.main_window().scene.get('qa_legacy_layers'))", timeout=20)
        row = qa.eval('''
spaces = [a.spaces.active for a in drv.main_window().screen.areas if a.type == "PROPERTIES"]
result = [{"layers": s.show_properties_layers, "compositor": s.show_properties_compositor}
          for s in spaces]
''')
        assert any(item["layers"] is expected and item["compositor"] for item in row), row
        rows.append({"fixture": suffix, "spaces": row})
    qa.cmd("reset_state")
    return {"status": "PASS", "files": rows}


def run(qa):
    out = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/mixar-blender53-qa"))
    out.mkdir(parents=True, exist_ok=True)
    qa.cmd("dismiss_splash")
    qa.cmd("dismiss_chat")
    legacy = qa.step("legacy_filters", check_legacy_filters, qa)
    api = qa.step("native_api", qa.eval, API_CHECKS)
    qa.step("engine_workspace", qa.cmd, "set_mode", mode="engine")
    qa.snap(str(out / "engine.png"))

    # A separate editor is a fixture so the viewport remains available for
    # the user's normal navigation and the subsequent undo replay.
    qa.eval('''
w = drv.main_window()
area = next(a for a in w.screen.areas if a.type == "OUTLINER")
area.type = "PROPERTIES"
space = area.spaces.active
for name in ("show_properties_layers", "show_properties_compositor"):
    assert hasattr(space, name), name
space.show_properties_layers = False
space.show_properties_compositor = True
assert not space.show_properties_layers and space.show_properties_compositor
space.show_properties_layers = True
space.show_properties_compositor = False
assert space.show_properties_layers and not space.show_properties_compositor
space.show_properties_compositor = True
space.context = "COMPOSITOR"
result = True
''')
    qa.press("ESC")
    qa.snap(str(out / "compositor.png"))

    qa.eval('''
w = drv.main_window()
area = next(a for a in w.screen.areas if a.type == "PROPERTIES")
area.type = "PROJECT"
assert area.type == "PROJECT"
result = True
''')
    qa.press("ESC")
    qa.snap(str(out / "project-editor.png"))
    document = str(out / "blender53-roundtrip.mixar")
    qa.eval(f'''
assert bpy.ops.wm.save_as_mainfile(filepath={document!r}, check_existing=False,
                                 thumbnail=False) == {{"FINISHED"}}
result = True
''')
    qa.eval(f'''
assert bpy.ops.wm.open_mainfile(filepath={document!r}) == {{"FINISHED"}}
result = True
''')
    qa.wait("any(a.type == 'PROJECT' for a in drv.main_window().screen.areas)", timeout=20)
    qa.eval('''
assert drv.main_window().scene["qa_binary"] == b"\\x00tail"
assert any(a.type == "PROJECT" for a in drv.main_window().screen.areas)
result = True
''')
    qa.cmd("dismiss_chat")
    qa.snap(str(out / "reopened.png"))
    qa.step("zen_workspace", qa.cmd, "set_mode", mode="zen")
    qa.snap(str(out / "zen.png"))
    (out / "state.json").write_text(json.dumps(api, indent=2))
    return {"api": api, "legacy": legacy, "backend_turns": 0, "document": document}


if __name__ == "__main__":
    run_scenario("blender53_regressions_e2e", run)
