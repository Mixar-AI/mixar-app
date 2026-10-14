#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tour language packs in the real app: a complete local pack narrates in
that language from its parts; a missing pack plays English with the chosen
language's subtitles.

QA_HARNESS=/path/to/mixar-qa-harness TOUR_PACK_DIR=<repo>/dist/tour-packs/1 \\
    python3 tests/qa/onboarding_tour_lang_e2e.py
Screenshots go to QA_SCENARIO_OUT (default /tmp/onboarding-tour-lang).
"""
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/onboarding-tour-lang'))
PACK_DIR = os.environ['TOUR_PACK_DIR']
EMPTY_DIR = tempfile.mkdtemp(prefix='tour-no-packs-')

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


def start_tour(qa, lang, pack_dir, silent=True, rate=4.0):
    return qa.eval(SETUP + f"""
def start():
    if current() is not None:
        current().stop('cancelled')
        yield .3
    os.environ[tlang.ENV_LANGUAGE] = {lang!r}
    os.environ[tcfg.ENV_PACK_DIR] = {pack_dir!r}
    os.environ.pop(tcfg.ENV_SUBTITLES, None)
    with bpy.context.temp_override(window=win, area=area, region=region):
        assert bpy.ops.mixar.onboarding_tour('INVOKE_DEFAULT', silent={silent!r}, rate={rate!r}) == {{'RUNNING_MODAL'}}
    yield .5
    return True
result = start()
""")


def snapshot(qa, name):
    path = OUT / f'{name}.png'
    qa.snap(str(path))
    return str(path)


def localized(qa):
    start_tour(qa, 'fr', PACK_DIR)
    qa.wait(NOT_LOADING + " and __import__('json').loads(bpy.data.window_managers[0].mixar_tour_state)['narration'] == 'fr'", timeout=10)
    st = json.loads(qa.eval(SETUP + "result = json.dumps(state())"))
    assert st['language'] == 'fr' and st['narration'] == 'fr', st
    assert st['subtitle'] == '', 'subtitles must be off while the French narration plays'
    kinds = qa.eval(SETUP + "s = current(); result = json.dumps([s.video.__class__.__name__, s.clock.__class__.__name__, len(s.video.parts), s.tour.beats[1].enter_ms])")
    video_cls, clock_cls, nparts, enter1 = json.loads(kinds)
    assert video_cls == 'PartsMovie' and nparts == 8, kinds
    assert enter1 != 6610, 'the French beat table must differ from the English one'
    # Let the runner cross the first act boundary (part-0 -> part-1) and draw.
    qa.eval(SETUP + "current().runner._jump('viewport'); current().runner.tick(); result=True")
    qa.wait("__import__('json').loads(bpy.data.window_managers[0].mixar_tour_state)['beat'] == 'viewport'", timeout=10)
    qa.eval("def settle():\n yield .6\n return True\nresult=settle()")
    opened = json.loads(qa.eval(SETUP + "s = current(); result = json.dumps(sorted(s.video._open))"))
    assert 1 in opened, f'part-1 must be open while the viewport beat plays: {opened}'
    shot = snapshot(qa, 'french-viewport')
    # Jump to the last beat: part-7 (the appended logo card) must open.
    qa.eval(SETUP + "current().runner._jump('outro'); current().runner.tick(); result=True")
    qa.eval("def settle():\n yield .8\n return True\nresult=settle()")
    opened = json.loads(qa.eval(SETUP + "s = current(); result = json.dumps(sorted(s.video._open))"))
    assert 7 in opened, f'part-7 must be open on the outro: {opened}'
    shot2 = snapshot(qa, 'french-outro')
    return {'viewport_shot': shot, 'outro_shot': shot2, 'beat1_enter_ms': enter1}


def audio_clock(qa):
    """With sound on, the joined-parts audio handle is the clock."""
    start_tour(qa, 'fr', PACK_DIR, silent=False, rate=1.0)
    qa.eval("def settle():\n yield 1.2\n return True\nresult=settle()")
    info = json.loads(qa.eval(SETUP + "s = current(); result = json.dumps([s.clock.__class__.__name__, s.clock.position_ms(), s.clock.duration_ms])"))
    cls, pos, dur = info
    assert cls == 'PartsClock', info
    assert pos > 500, f'audio clock did not advance: {info}'
    assert dur > 120000, f'joined clock must span all parts: {info}'
    return {'clock': info}


NO_FETCH = SETUP + """
from mixar.modules.onboarding.core.tour import pack_fetch
if not hasattr(pack_fetch, '_qa_real_prefetch'):
    pack_fetch._qa_real_prefetch = pack_fetch.prefetch
pack_fetch.prefetch = lambda code: False          # offline: nothing will arrive
pack_fetch._states.pop('de', None)
result = True
"""
RESTORE_FETCH = SETUP + """
from mixar.modules.onboarding.core.tour import pack_fetch
if hasattr(pack_fetch, '_qa_real_prefetch'):
    pack_fetch.prefetch = pack_fetch._qa_real_prefetch
result = True
"""
NOT_LOADING = "__import__('json').loads(bpy.data.window_managers[0].mixar_tour_state).get('status') not in ('loading', 'idle')"


def fallback(qa):
    """Offline (no download can start): English with German subtitles at once."""
    qa.eval(NO_FETCH)
    try:
        start_tour(qa, 'de', EMPTY_DIR)
        qa.wait(NOT_LOADING + " and __import__('json').loads(bpy.data.window_managers[0].mixar_tour_state)['narration'] == 'en'", timeout=10)
    finally:
        qa.eval(RESTORE_FETCH)
    st = json.loads(qa.eval(SETUP + "result = json.dumps(state())"))
    assert st['language'] == 'de' and st['narration'] == 'en', st
    qa.eval(SETUP + "current().runner._jump('viewport'); current().clock.seek_ms(8500); current().runner.tick(); current().runner.set_user_paused(True); result=True")
    qa.eval("def settle():\n yield .5\n return True\nresult=settle()")
    st = json.loads(qa.eval(SETUP + "result = json.dumps(state())"))
    assert st['subtitle'], f'German subtitle expected over the English video at 8.5 s: {st}'
    shot = snapshot(qa, 'english-german-subtitles')
    return {'subtitle': st['subtitle'], 'shot': shot}


def _slow_pack_dir(parts):
    """A pack folder holding the manifest, French timing and only ``parts``."""
    import shutil
    d = tempfile.mkdtemp(prefix='tour-slow-pack-')
    src = Path(PACK_DIR)
    shutil.copy(src / 'manifest.json', d)
    (Path(d) / 'fr').mkdir()
    shutil.copy(src / 'fr' / 'timing.json', Path(d) / 'fr')
    for k in parts:
        shutil.copy(src / 'fr' / f'part-{k}.mp4', Path(d) / 'fr')
    return d


def progressive(qa):
    """Parts 0–1 present: the tour plays French and HOLDS at act 3 until
    part 2 lands, then continues."""
    import shutil
    d = _slow_pack_dir((0, 1))
    start_tour(qa, 'fr', d)
    qa.wait(NOT_LOADING + " and __import__('json').loads(bpy.data.window_managers[0].mixar_tour_state)['narration'] == 'fr'", timeout=10)
    qa.eval(SETUP + "current().runner._jump('scenes'); current().runner.tick(); result=True")
    qa.eval("def settle():\n yield .8\n return True\nresult=settle()")
    info = json.loads(qa.eval(SETUP + "s = current(); result = json.dumps([bool(s.clock.waiting), s.clock.position_ms(), s.tour.beats[8].enter_ms, state()['beat']])"))
    waiting, pos, scenes_enter, beat = info
    assert waiting and pos == scenes_enter - 1, f'clock must hold one ms before the missing part: {info}'
    shot = snapshot(qa, 'french-holding-for-part')
    for k in range(2, 8):
        shutil.copy(Path(PACK_DIR) / 'fr' / f'part-{k}.mp4', Path(d) / 'fr')
    qa.wait("not __import__('mixar.modules.onboarding.core.tour.session', fromlist=['current']).current().clock.waiting", timeout=10)
    qa.wait("__import__('json').loads(bpy.data.window_managers[0].mixar_tour_state)['beat'] == 'scenes'", timeout=10)
    return {'hold_shot': shot, 'held_at_ms': pos}


def loading_card(qa):
    """No part yet but a download in flight: a loading card for the wait
    budget, then English with subtitles."""
    d = tempfile.mkdtemp(prefix='tour-empty-pack-')
    qa.eval(SETUP + """
from mixar.modules.onboarding.core.tour import pack_fetch
pack_fetch._qa_saved = (pack_fetch.prefetch, tcfg.PACK_WAIT_S)
pack_fetch.prefetch = lambda code: True
pack_fetch._states['de'] = {'status': 'downloading', 'file': 'part-0.mp4', 'done': 1, 'total': 9}
tcfg.PACK_WAIT_S = 4.0
result = True
""")
    try:
        start_tour(qa, 'de', d)
        qa.wait("__import__('json').loads(bpy.data.window_managers[0].mixar_tour_state).get('status') == 'loading'", timeout=5)
        qa.eval("def settle():\n yield .5\n return True\nresult=settle()")
        shot = snapshot(qa, 'loading-card')
        qa.wait("__import__('json').loads(bpy.data.window_managers[0].mixar_tour_state).get('narration') == 'en' and __import__('json').loads(bpy.data.window_managers[0].mixar_tour_state).get('status') != 'loading'", timeout=12)
        st = json.loads(qa.eval(SETUP + "result = json.dumps(state())"))
        assert st['language'] == 'de' and st['narration'] == 'en', st
        return {'loading_shot': shot}
    finally:
        qa.eval(SETUP + """
from mixar.modules.onboarding.core.tour import pack_fetch
pack_fetch.prefetch, tcfg.PACK_WAIT_S = pack_fetch._qa_saved
pack_fetch._states.pop('de', None)
result = True
""")


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        out = {}
        out.update(qa.step('localized_pack', localized, qa))
        out.update(qa.step('audio_clock', audio_clock, qa))
        out.update(qa.step('english_fallback_with_subtitles', fallback, qa))
        out.update(qa.step('progressive_pack_holds_for_missing_part', progressive, qa))
        out.update(qa.step('loading_card_then_english', loading_card, qa))
        return out
    finally:
        qa.eval(SETUP + "\nif current() is not None: current().stop('cancelled')\nos.environ.pop(tlang.ENV_LANGUAGE, None); os.environ.pop(tcfg.ENV_PACK_DIR, None)\nresult=True")


if __name__ == '__main__':
    run_scenario('onboarding_tour_lang', run)
