#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real splash selection -> UI + narration + timed fallback, no paid jobs.

Run only against an isolated harness profile:
QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
    python3 tests/qa/unified_onboarding_language_e2e.py

The French case downloads the shipped public pack if needed. The other
cases use English + local subtitles. QA_SCENARIO_OUT holds screenshots.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp/mixar-unified-language"))
SETUP = """
import os, json
from pathlib import Path
from mixar.modules.onboarding.core.tour import language, pack_fetch
from mixar.modules.onboarding.core.tour.session import current
from mixar.modules.common.i18n import ui_locale
from mixar.modules.common.i18n.core import runtime
from mixar.config.config import get_config
assert os.environ.get('MIXAR_QA') == '1', 'Requires an isolated QA profile'
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
def state():
    return json.loads(bpy.data.window_managers[0].mixar_tour_state or '{}')
"""


def settle(qa, seconds=.3):
    qa.eval(f"def settle():\n yield {seconds}\n return True\nresult=settle()")


def snap(qa, name):
    path = OUT / f"{name}.png"
    qa.snap(str(path))
    return str(path)


def open_setup(qa):
    qa.press("ESC")
    qa.eval(SETUP + """
if current() is not None:
    current().stop('cancelled')
# C++ chooses Quick Setup only while the isolated profile has no prefs.
path = Path(bpy.utils.user_resource('CONFIG')) / 'mixar_userpref.blend'
if path.exists():
    path.replace(path.with_suffix('.language-qa-backup'))
with bpy.context.temp_override(window=win, area=area, region=region):
    bpy.ops.wm.splash('INVOKE_DEFAULT')
result = True
""")
    qa.wait("bool(drv.find(prop='mixar_tour_language'))", timeout=5)


def choose(qa, code, locale):
    open_setup(qa)
    label = qa.eval(SETUP + f"result=language.get({code!r}).label")
    qa.cmd("choose", widget={"prop": "mixar_tour_language"}, item=label)
    actual = qa.eval(SETUP + """
result = dict(tour=language.current(), ui=bpy.context.preferences.view.language,
              catalog=runtime.active_catalog(), request=ui_locale(),
              stored=get_config().get(language.CONFIG_KEY))
""")
    assert actual == dict(tour=code, ui=locale, catalog=locale,
                          request=locale, stored=code), actual
    settle(qa)
    splash = snap(qa, f"splash-{code}")
    qa.click(op="WM_OT_save_userpref")
    qa.wait("not bool(drv.find(prop='mixar_tour_language'))", timeout=5)
    # Continue saves preferences and replaces Quick Setup with the mode
    # splash. Leave that surface too before starting the tour.
    qa.click(op="MIXAR_OT_set_ui_mode_ai")
    qa.wait("not bpy.context.window_manager.mixar_splash_open", timeout=5)
    return splash


def start_tour(qa):
    return qa.eval(SETUP + """
with bpy.context.temp_override(window=win, area=area, region=region):
    assert bpy.ops.mixar.onboarding_tour('INVOKE_DEFAULT', silent=True) == {'RUNNING_MODAL'}
result = state()
""")


def hold_at(qa, beat, ms):
    qa.eval(SETUP + f"""
tour = current()
tour.runner.set_user_paused(False)
tour.runner._jump({beat!r})
tour.clock.seek_ms({ms})
tour.runner.tick()
tour.runner.set_user_paused(True)
tour._publish(force=True)
result = True
""")
    settle(qa, .7)
    return qa.eval(SETUP + "result=state()")


def subtitles_only(qa, code, locale):
    splash = choose(qa, code, locale)
    initial = start_tour(qa)
    assert initial["status"] != "loading", initial
    assert initial["language"] == code and initial["narration"] == "en", initial
    st = hold_at(qa, "viewport", 8500)
    assert st["subtitle"], st
    first = snap(qa, f"english-{code}-subtitle")
    # A gate pause and the following cue use movie time, not elapsed wall time.
    st = hold_at(qa, "viewport-try", 17660)
    assert not st["subtitle"], st
    st = hold_at(qa, "shortcuts", 19000)
    assert st["subtitle"], st
    second = snap(qa, f"english-{code}-after-pause")
    qa.eval(SETUP + "current().stop('cancelled'); result=True")
    return {"splash": splash, "subtitle": first, "after_pause": second}


def french(qa):
    splash = choose(qa, "fr", "fr_FR")
    qa.wait("__import__('mixar.modules.onboarding.core.tour.pack_fetch', "
            "fromlist=['state']).state('fr').get('status') in ('ready','failed')", timeout=120)
    download = qa.eval(SETUP + "result=pack_fetch.state('fr')")
    assert download["status"] == "ready", download
    initial = start_tour(qa)
    assert initial["language"] == initial["narration"] == "fr", initial
    assert initial["subtitle"] == "", initial
    settle(qa, 1)
    shot = snap(qa, "french-narration")
    qa.eval(SETUP + "current().stop('cancelled'); result=True")
    return {"splash": splash, "tour": shot, "pack": download}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    result = {}
    try:
        result["hindi"] = qa.step("hindi_ui_english_video_and_timed_subtitles",
                                   subtitles_only, qa, "hi_IN", "hi_IN")
        result["persian"] = qa.step("persian_ui_and_readable_rtl_subtitles",
                                     subtitles_only, qa, "fa_IR", "fa_IR")
        result["french"] = qa.step("french_ui_and_dubbed_video", french, qa)
        return result
    finally:
        qa.eval(SETUP + """
if current() is not None:
    current().stop('cancelled')
os.environ.pop(language.ENV_LANGUAGE, None)
result=True
""")


if __name__ == "__main__":
    run_scenario("unified_onboarding_language", run)
