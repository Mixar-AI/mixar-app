#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A dubbed language downloaded from the real CDN, the way a user gets it:
an empty pack cache, French picked, the manifest and every part fetched
from cdn.mixar.app by the app's own downloader, the tour narrating in
French. cdn.mixar.app answers urllib's default user agent with a 403
(Cloudflare 1010), which silently left every dub on English + subtitles.

QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/onboarding_tour_cdn_e2e.py
The app reads tour-packs/<TOUR_PACK_VERSION>/manifest.json. To test packs
whose manifest is not uploaded yet, point it at the staged one (its part
URLs must already be on the CDN):
    TOUR_MANIFEST_URL=file://<repo>/dist/tour-packs/manifest.json
Screenshots go to QA_SCENARIO_OUT (default /tmp/onboarding-tour-cdn).
"""
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/onboarding-tour-cdn'))
CACHE_DIR = tempfile.mkdtemp(prefix='tour-cdn-cache-')
MANIFEST_URL = os.environ.get('TOUR_MANIFEST_URL', '')
LANG = os.environ.get('TOUR_LANG', 'fr')

SETUP = """
import os, json
from mixar.modules.onboarding.core.tour.session import current
from mixar.modules.onboarding.core.tour import config as tcfg
from mixar.modules.onboarding.core.tour import language as tlang
from mixar.modules.onboarding.core.tour import pack_fetch
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
def state():
    return json.loads(bpy.data.window_managers[0].mixar_tour_state or '{}')
"""
STATE = "__import__('json').loads(bpy.data.window_managers[0].mixar_tour_state or '{}')"


def snapshot(qa, name):
    path = OUT / f'{name}.png'
    qa.snap(str(path))
    return str(path)


def narrates_from_cdn(qa):
    qa.eval(SETUP + f"""
def start():
    if current() is not None:
        current().stop('cancelled')
        yield .3
    os.environ[tlang.ENV_LANGUAGE] = {LANG!r}
    os.environ[tcfg.ENV_PACK_DIR] = {CACHE_DIR!r}
    if {MANIFEST_URL!r}:
        os.environ[tcfg.ENV_PACKS_MANIFEST_URL] = {MANIFEST_URL!r}
    os.environ.pop(tcfg.ENV_SUBTITLES, None)
    with bpy.context.temp_override(window=win, area=area, region=region):
        assert bpy.ops.mixar.onboarding_tour('INVOKE_DEFAULT', silent=True, rate=1.0) == {{'RUNNING_MODAL'}}
    yield .5
    return True
result = start()
""")
    # The loading card waits up to PACK_WAIT_S for the timing table and the
    # first part; a blocked fetch falls back to English at once.
    qa.wait(f"{STATE}.get('status') == 'running' and {STATE}.get('narration')", timeout=20)
    st = json.loads(qa.eval(SETUP + f"""
result = json.dumps({{'tour': state(), 'fetch': pack_fetch.state({LANG!r}),
                      'manifest_url': pack_fetch.manifest_url()}})"""))
    assert st['tour']['narration'] == LANG, f'fell back instead of narrating {LANG}: {st}'
    return {'started': st, 'start_shot': snapshot(qa, f'{LANG}-from-cdn')}


def whole_pack_lands(qa):
    qa.wait("__import__('mixar.modules.onboarding.core.tour.pack_fetch', fromlist=['state'])"
            f".state({LANG!r}).get('status') == 'ready'", timeout=180)
    # Each file sits beside a .ok sidecar written once its sha256 matched.
    files = sorted(p.name for p in (Path(CACHE_DIR) / LANG).iterdir() if p.suffix != '.ok')
    assert files == [f'part-{k}.mp4' for k in range(8)] + ['timing.json'], files
    return {'cached': files}


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        out = {}
        out.update(qa.step('narrates_from_cdn', narrates_from_cdn, qa))
        out.update(qa.step('whole_pack_lands', whole_pack_lands, qa))
        return out
    finally:
        qa.eval(SETUP + "\nif current() is not None: current().stop('cancelled')\n"
                "for k in (tlang.ENV_LANGUAGE, tcfg.ENV_PACK_DIR, tcfg.ENV_PACKS_MANIFEST_URL):\n"
                "    os.environ.pop(k, None)\n"
                "result=True")


if __name__ == '__main__':
    run_scenario('onboarding_tour_cdn', run)
