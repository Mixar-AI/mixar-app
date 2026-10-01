# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Copy to an isolated QA profile's scripts/startup before GUI launch.

Records the property before timers/deferred UI run and on the first actual
Quick Setup draw. Use with unified_onboarding_language_e2e.py; writes to
MIXAR_QA_OUT/early-language-registration.json. No real profile changes.
"""

import json
import os
from pathlib import Path


def register():
    if os.environ.get("MIXAR_QA") != "1":
        return
    import bpy
    import bootstrap
    from mixar.bootstrap import splash_quick_setup
    from mixar.modules.onboarding.core.tour import language

    path = Path(os.environ["MIXAR_QA_OUT"]) / "early-language-registration.json"
    state = dict(deferred_ui_complete=bootstrap._ui_loading_complete,
                 language_registered=hasattr(bpy.types.WindowManager, "mixar_tour_language"),
                 language_count=len(language.CODES))
    assert state["language_registered"] and not state["deferred_ui_complete"], state
    path.write_text(json.dumps(state, indent=2))
    original = splash_quick_setup.WM_MT_splash_quick_setup.draw

    def draw(self, context):
        if "first_draw_has_language" not in state:
            state["first_draw_has_language"] = hasattr(context.window_manager, "mixar_tour_language")
            path.write_text(json.dumps(state, indent=2))
        original(self, context)

    splash_quick_setup.WM_MT_splash_quick_setup.draw = draw


def unregister():
    pass
