#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The bundled English take in the real app: the 4:3 founder video plays in
a 4:3 card (420x315 framed, 300x225 over the UI), a gated pause holds in
the silence after its line and the outro ends on the presenter with the
replay note.

QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/onboarding_tour_4x3_e2e.py
Screenshots go to QA_SCENARIO_OUT (default /tmp/onboarding-tour-4x3).
"""
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/onboarding-tour-4x3'))
EMPTY_DIR = tempfile.mkdtemp(prefix='tour-no-packs-')
TAKE_MS = 149200

SETUP = """
import os, json
from mixar.modules.onboarding.core.tour.session import current
from mixar.modules.onboarding.core.tour import config as tcfg
from mixar.modules.onboarding.core.tour import language as tlang
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
def state():
    return json.loads(bpy.data.window_managers[0].mixar_tour_state or '{}')
"""
STATE = "__import__('json').loads(bpy.data.window_managers[0].mixar_tour_state or '{}')"


def settle(qa, seconds):
    qa.eval(f"def settle():\n yield {seconds}\n return True\nresult=settle()")


def snapshot(qa, name):
    path = OUT / f'{name}.png'
    qa.snap(str(path))
    return str(path)


def card(qa):
    """[video w, video h, beat, ui scale] of the card as drawn this tick."""
    return json.loads(qa.eval(SETUP + """
s = current(); v = s._card_layout.video
result = json.dumps([v[2] - v[0], v[3] - v[1], state()['beat'], s._ui_scale])"""))


def assert_card(size, variant):
    """4:3 at 3/4 of the 16:9 card's width: hero 420x315, half 300x225."""
    vw, vh, beat, scale = size
    want_w = {'hero': 420, 'half': 300}[variant] * scale
    assert abs(vw / vh - 4 / 3) < 0.01, size
    assert abs(vw - want_w) <= 1, f'{variant} card should be {want_w:.0f} px wide: {size}'


def english_take(qa):
    qa.eval(SETUP + f"""
def start():
    if current() is not None:
        current().stop('cancelled')
        yield .3
    os.environ[tlang.ENV_LANGUAGE] = 'en'
    os.environ[tcfg.ENV_PACK_DIR] = {EMPTY_DIR!r}
    os.environ.pop(tcfg.ENV_SUBTITLES, None)
    with bpy.context.temp_override(window=win, area=area, region=region):
        assert bpy.ops.mixar.onboarding_tour('INVOKE_DEFAULT', silent=True, rate=1.0) == {{'RUNNING_MODAL'}}
    yield .5
    return True
result = start()
""")
    qa.wait(f"{STATE}.get('narration') == 'en' and {STATE}.get('status') == 'running'", timeout=10)
    info = json.loads(qa.eval(SETUP + """
s = current()
result = json.dumps([s.video.width, s.video.height, s.clock.duration_ms, s.tour.beats[1].enter_ms])"""))
    w, h, dur, enter1 = info
    assert (w, h) == (960, 720), f'the bundled take must be 960x720: {info}'
    assert abs(dur - TAKE_MS) <= 150, f'clock must span the 2:29.2 take: {info}'
    assert enter1 == 6090, f'the English table must be the re-timed one: {info}'
    settle(qa, 1.2)
    size = card(qa)
    assert size[2] == 'intro', size
    assert_card(size, 'hero')
    return {'take': info, 'intro_card': size, 'intro_shot': snapshot(qa, 'intro-hero')}


def half_card(qa):
    qa.eval(SETUP + "current().runner._jump('island-tabs'); current().runner.tick(); result=True")
    qa.wait(f"{STATE}['beat'] == 'island-tabs'", timeout=10)
    settle(qa, 2.5)                # the card glides to its new place
    size = card(qa)
    assert_card(size, 'half')
    return {'half_card': size, 'island_tabs_shot': snapshot(qa, 'island-tabs-half')}


def gate_holds_in_silence(qa):
    """engine-prompt has the shortest pause of the take (840 ms to the next
    breath-free onset): play into it and the tour must hold there."""
    clip_end = json.loads(qa.eval(SETUP + """
b = next(b for b in current().tour.beats if b.id == 'engine-prompt')
result = json.dumps(b.clip_end_ms)"""))
    qa.eval(SETUP + f"""
current().runner._jump('engine-prompt'); current().clock.seek_ms({clip_end - 1500})
current().runner.tick(); result=True""")
    qa.wait(f"{STATE}.get('status') == 'gated'", timeout=6)
    st = json.loads(qa.eval(SETUP + "result = json.dumps(state())"))
    assert st['beat'] == 'engine-prompt' and st['gate'] == 'ui_mode:PRO', st
    # The runner stops on the first tick at or past the clip end (30 Hz),
    # well before the next line's onset 380 ms later.
    assert clip_end - 120 <= st['ms'] <= clip_end + 50, f'held at {st["ms"]}, clip end {clip_end}'
    settle(qa, 0.6)
    shot = snapshot(qa, 'engine-gate')
    # Nobody clicks Engine: the auto action flips it after the timeout.
    qa.wait(f"{STATE}['beat'] == 'engine-mode'", timeout=14)
    return {'gate_held_ms': st['ms'], 'engine_gate_shot': shot}


def outro_ends_on_presenter(qa):
    qa.eval(SETUP + "current().runner._jump('outro'); current().clock.seek_ms(148300); "
            "current().runner.tick(); result=True")
    qa.wait(f"{STATE}['beat'] == 'outro'", timeout=10)
    settle(qa, 0.4)
    shot = snapshot(qa, 'outro-replay-note')
    qa.wait(f"{STATE}.get('completed') or not {STATE}.get('running')", timeout=10)
    st = json.loads(qa.eval(SETUP + "result = json.dumps(state())"))
    assert st.get('completed'), st
    return {'outro_shot': shot}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        out = {}
        out.update(qa.step('english_4x3_take', english_take, qa))
        out.update(qa.step('half_card_is_4x3', half_card, qa))
        out.update(qa.step('gate_holds_in_silence', gate_holds_in_silence, qa))
        out.update(qa.step('outro_ends_on_presenter', outro_ends_on_presenter, qa))
        return out
    finally:
        qa.eval(SETUP + "\nif current() is not None: current().stop('cancelled')\n"
                "os.environ.pop(tlang.ENV_LANGUAGE, None); os.environ.pop(tcfg.ENV_PACK_DIR, None)\n"
                "result=True")


if __name__ == '__main__':
    run_scenario('onboarding_tour_4x3', run)
