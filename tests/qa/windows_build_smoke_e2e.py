#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit smoke test for an installed build after switching branches.

Launch an isolated QA app, then set QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT before running this file. Requires a clean isolated QA scene.
Inspect the screenshots as well as the state verdict.
"""

import json

from moodboard_drawer_e2e import (
    OUT, drop, geometry, png, point, require, run_scenario, select, snap,
    target, toggle, verify_viewport,
)
from moodboard_drawer_resize_links_e2e import canvas, resize


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),
            'Use an isolated QA app')
    qa.step('ready', qa.wait,
            "hasattr(bpy.context.window_manager, 'mixar_moodboard_drawer_width')",
            timeout=30)
    require(qa.eval("result=not drv.main_window().scene.mixie_moodboard_images"),
            'Use a clean QA scene')
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    if geometry(qa)['amount'] > .98:
        toggle(qa, 0)
    before = geometry(qa)
    qa.step('closed_grip', target, qa, 'moodboard_drawer_grip')
    qa.step('open_drawer', toggle, qa, 1)
    qa.step('drawn_panel', target, qa, 'moodboard_drawer_panel')
    qa.step('open_pixels', snap, qa, '01_open')
    qa.step('resize_drawer', resize, qa, 620)
    chosen = canvas(qa)['chosen']
    qa.step('close_drawer', toggle, qa, 0)
    qa.step('reopen_drawer', toggle, qa, 1)
    require(abs(canvas(qa)['chosen'] - chosen) < .01,
            'Reopening lost the user-selected width')
    fixture = png(OUT / 'reference.png', (70, 145, 210), width=192, height=128)
    node = qa.step('drop_reference', drop, qa, fixture,
                   **point(target(qa, 'moodboard_drawer_panel'), .55, .45))
    qa.step('select_reference', select, qa, node)
    qa.step('reference_pixels', snap, qa, '02_reference', True)
    qa.step('viewport_unchanged', verify_viewport, qa, before)
    result = {'backend_submissions': 0, 'chosen_width': chosen,
              'reference': node, 'viewport_unchanged': True}
    (OUT / 'state-evidence.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    run_scenario('windows_build_smoke_e2e', run)
