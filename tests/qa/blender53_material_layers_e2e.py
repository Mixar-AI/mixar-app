#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay the harness's full material-layer workflow with the 5.3 file picker.

Uses QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. No backend generation.
The picker needs an explicit filename-edit commit before its Execute click.
"""
import os
from pathlib import Path
import sys

harness = Path(os.environ['QA_HARNESS'])
sys.path[:0] = [str(harness), str(harness / 'scenarios')]
from lib import run_scenario
from release_suite import native
import material_layers_e2e as layers


choose_original = native.choose_file


def choose_file(qa, path, execute=True):
    choose_original(qa, path, execute=False)
    if execute:
        widget = qa.find(area_type='FILE_BROWSER', prop='filename')['widgets'][0]
        # The directory-to-filename handoff activates a text editor. Finish
        # that edit through native keyboard input before pressing Execute.
        qa.press('RET', window=widget['window'])
        if qa.find(area_type='FILE_BROWSER', op='FILE_OT_execute')['total']:
            qa.click(area_type='FILE_BROWSER', op='FILE_OT_execute')


def run(qa):
    assert qa.eval('result=bpy.app.version[:2] == (5,3)')
    qa.cmd('reset_state')
    qa.cmd('wait_login', timeout=60)
    original_native, original_layers = native.choose_file, layers.choose_file
    native.choose_file = layers.choose_file = choose_file
    try:
        return layers.run(qa)
    finally:
        native.choose_file, layers.choose_file = original_native, original_layers


if __name__ == '__main__':
    Path(os.environ['QA_SCENARIO_OUT']).mkdir(parents=True, exist_ok=True)
    run_scenario('blender53_material_layers_e2e', run)
