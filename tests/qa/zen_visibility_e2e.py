# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Zero-credit visibility regression replay against an isolated QA app.

QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/zen_visibility_e2e.py
Set QA_VISIBILITY_BASELINE=1 to record the unfixed native/Python disagreement.
Fixtures replace only the active Media model's local parameter group; the
catalog is restored in finally. No generation is submitted.
"""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import QA

IMPORT = "from mixar.modules.common.generation_params.core import engine; "

SEED = '''
from mixar.modules.common.generation_params.core import engine
wm = bpy.context.window_manager
tab = drv.main_window().scene.mixie_moodboard_sidebar.tab_imagegen
key = (tab.mode, tab.model)
attr = engine._registered[key]
old_cls = engine._classes[key]
delattr(bpy.types.WindowManager, attr)
bpy.utils.unregister_class(old_cls)
parameters = {
    'choice': {'type': 'string', 'label': 'Choice', 'enum': ['01', '1', '🎨'], 'default': '01'},
    'number': {'type': 'integer', 'label': 'Numeric match', 'default': 3,
               'visible_if': {'choice': '1'}},
    'unicode': {'type': 'integer', 'label': 'Unicode match', 'default': 4,
                'visible_if': {'choice': '🎨'}},
    'fraction': {'type': 'number', 'label': 'Fraction', 'default': 1.234567},
    'precise': {'type': 'integer', 'label': 'Exact float', 'default': 5,
                'visible_if': {'fraction': 1.2345670461654663}},
}
cls, schema = engine._build_group(*key, parameters)
bpy.utils.register_class(cls)
setattr(bpy.types.WindowManager, attr, bpy.props.PointerProperty(type=cls))
engine._classes[key] = cls
engine._schemas[key] = schema
getattr(wm, attr).p_choice = '01'
getattr(wm, attr).p_fraction = 1.234567
wm.mixar_bubble_media_kind = 'IMAGE'
wm.mixar_bubble_tab = 'MEDIA'
bpy.ops.mixar.agent_bubble_open_window()
result = list(key)
'''


def run(qa):
    out = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/zen-visibility"))
    out.mkdir(parents=True, exist_ok=True)
    results = []
    qa.eval("bpy.context.window_manager.mixar_bubble_tab='AGENT'; result=True")
    time.sleep(0.3)
    key = qa.eval(SEED)
    qa.eval("[a.tag_redraw() for w in bpy.context.window_manager.windows for a in w.screen.areas]; result=True")
    try:
        for name, choice in (("numeric", "01"), ("unicode", "🎨")):
            if choice != "01":
                qa.cmd("choose", widget={"op": "WM_OT_context_menu_enum", "text": "01",
                                          "area_type": "AGENT_BUBBLE"}, item=choice)
            qa.wait(f"__import__('mixar.modules.common.generation_params.core.engine', "
                    f"fromlist=['get_param_group']).get_param_group(*{key!r}).p_choice == {choice!r}", timeout=10)
            qa.wait("len(drv.find(op='MIXAR_OT_pane_generation_settings')) == 1", timeout=10)
            time.sleep(0.3)  # Introspection precedes the native popup/window paint.
            qa.cmd("snap", path=str(out / f"{name}-strip.png"),
                   target={"op": "MIXAR_OT_pane_generation_settings"}, margin=1800)
            strip = qa.find(area_type="AGENT_BUBBLE")["widgets"]
            props = {w.get("prop") for w in strip}
            collected = qa.eval(IMPORT + f"result=engine.collect_params(*{key!r})")
            settings = qa.click(op="MIXAR_OT_pane_generation_settings")
            qa.wait("len(drv.find(popup=True, text='Generation Settings')) == 1", timeout=10)
            popup = {w.get("prop") for w in qa.find(popup=True)["widgets"]}
            time.sleep(0.3)
            qa.cmd("snap", path=str(out / f"{name}-settings.png"),
                   target={"popup": True, "text": "Generation Settings"}, margin=500)
            for param in ("number", "unicode", "precise"):
                expected = param in collected
                results.append({"case": name, "param": param, "expected": expected,
                                "strip": f"p_{param}" in props,
                                "settings": f"p_{param}" in popup})
            qa.press("ESC", window=settings["window"])
            qa.wait("not drv.find(popup=True)", timeout=10)
        verdict = {"paid_requests": 0, "cases": results}
        (out / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
        print(json.dumps(verdict, indent=2))
        if not os.environ.get("QA_VISIBILITY_BASELINE"):
            assert all(r["expected"] == r["strip"] == r["settings"] for r in results), results
    finally:
        for popup in qa.find(popup=True)["widgets"][:1]:
            qa.press("ESC", window=popup["window"])
        qa.wait("not drv.find(popup=True)", timeout=10)
        qa.eval("bpy.context.window_manager.mixar_bubble_tab='AGENT'; result=True")
        time.sleep(0.3)
        qa.eval(IMPORT + "engine.rebuild_from_catalog(); result=True")


if __name__ == "__main__":
    run(QA())
