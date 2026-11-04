# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Cases for the three defects the PR #1839 review found (change record 3.11-3.13):
a Render leaked per agent preview, orphan chat layouts written into checkpoints,
and toasts that ignore clicks after a file load. All three fail on a build
without the fixes. No credits are spent."""

from __future__ import annotations

import json
import time
import uuid

from common import call_from_timer
from cases_render import _SCENE

_ROOT = '''
from mixar.modules.space_mixie_chat.core import checkpoint_store as store, turn_checkpoints as cp
store.checkpoints_root = lambda: {root!r}
cp.checkpoints_root = store.checkpoints_root
result = True
'''

_SURVEY = '''
import bpy
shown = {w.screen.name for w in bpy.context.window_manager.windows}
result = {"orphans": sorted(s.name for s in bpy.data.screens
                            if any(a.type == 'AGENT_BUBBLE' for a in s.areas) and s.name not in shown),
          "layouts": sum(len(ws.screens) for ws in bpy.data.workspaces)}
'''

#: Blender's own allocator total (guarded alloc), from the status bar. RSS cannot
#: show this leak: the allocator often hands the next copy the freed Scene's
#: address, and a Render keyed by that address is then reused instead of leaked.
_MEM = '''
import bpy, re
bpy.context.preferences.view.show_statusbar_memory = True
text = bpy.context.window.screen.statusbar_info()
m = re.search(r"([\\d.,]+)\\s*(KiB|MiB|GiB)", text)
result = float(m.group(1).replace(",", "")) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[m.group(2)] if m else None
'''


def _inspection(qa) -> None:
    key = uuid.uuid4().hex
    params = json.dumps({'width': 1600, 'height': 1200, 'shading': 'material', 'view': 'hero'})
    call_from_timer(qa, f"bpy.ops.mixie_chat.agent_preview_render(job_key={key!r}, "
                        f"inspection_json={params!r}, max_faces=65000000)", delay=0.0)
    time.sleep(0.8)
    qa.wait("not bpy.app.is_job_running('RENDER')", timeout=120)
    qa.wait(f"__import__('mixar.modules.space_mixie_chat.core.preview_render', fromlist=['x'])"
            f".poll({key!r})['status'] != 'running'", timeout=30)


def preview_render_memory(c):
    """3.11: an agent preview must not leave its Render behind. A 1600x1200 job
    left ~59 MiB in Blender's allocator before the fix. A new scene is made after
    each job so the next copy cannot reuse the freed one's address (as in a real
    session, where other allocations take it)."""
    qa = c.qa
    qa.eval(_SCENE)
    time.sleep(3)
    _inspection(qa)                      # warm-up: kernels, first allocations
    time.sleep(1.0)
    before = qa.eval(_MEM)
    assert before, "status bar shows no memory figure"
    jobs = 6
    for i in range(jobs):
        _inspection(qa)
        qa.eval(f"import bpy\nbpy.data.scenes.new('qa pad {i}')\nresult = True")
    time.sleep(1.0)
    after = qa.eval(_MEM)
    per_job = round((after - before) / jobs, 1)
    internal = qa.eval("from mixar.modules.space_mixie_chat.constants import is_internal_scene\n"
                       "result = [s.name for s in bpy.data.scenes if is_internal_scene(s)]")
    c.numbers.update(blender_mem_before_mib=before, blender_mem_after_mib=after, growth_per_job_mib=per_job)
    assert not internal, f"private render scenes left behind: {internal}"
    assert per_job < 5, f"Blender memory grows {per_job} MiB per agent render (a leaked 1600x1200 Render is ~59 MiB)"


def _snapshot_and_load(qa, root: str) -> None:
    """Take a turn checkpoint with the island open, then read it back the way
    ``turn_checkpoints.restore`` does (close the bubble windows, then
    ``wm.recover_auto_save``), without its timeline bookkeeping."""
    qa.eval(_ROOT.format(root=root))
    rec = qa.eval('''
import bpy
from mixar.modules.space_mixie_chat.core import turn_checkpoints as cp
rec = cp.capture(bpy.context.window.scene, 'qa review checkpoint')
result = (rec or {}).get('id') if isinstance(rec, dict) else getattr(rec, 'id', None)
''')
    assert rec, "checkpoint capture wrote nothing"
    path = qa.eval(f"import glob\nresult = sorted(glob.glob({root!r} + '/**/{rec}.mixar', recursive=True))")
    assert path, "checkpoint file not found"
    qa.eval("drv._qa_read = None\nresult = True")
    call_from_timer(qa, "from mixar.modules.space_mixie_chat.core import turn_checkpoints as cp\n"
                        "cp._close_bubble_windows()\n"
                        f"drv._qa_read = sorted(bpy.ops.wm.recover_auto_save(filepath={path[0]!r}))", delay=0.05)
    qa.wait("drv._qa_read is not None", timeout=60)
    assert qa.eval("result = drv._qa_read") == ["FINISHED"], "the checkpoint did not load"
    time.sleep(2.0)
    qa.eval(_ROOT.format(root=root))


def checkpoint_restore_no_orphan_layouts(c):
    """3.12: checkpoints taken with the island open must not write the island's
    layouts: each load used to leave two orphan chat screens (and layouts) behind."""
    qa = c.qa
    qa.open_chat()
    qa.wait("drv.island_state()['mode'] == 'island'", timeout=15)
    time.sleep(1)
    start = qa.eval(_SURVEY)
    orphans, layouts = [], []
    for _ in range(2):
        _snapshot_and_load(qa, str(c.out / "checkpoints"))
        qa.open_chat()
        qa.wait("drv.island_state()['mode'] in ('island', 'pill')", timeout=20)
        time.sleep(1)
        now = qa.eval(_SURVEY)
        orphans.append(len(now["orphans"]))
        layouts.append(now["layouts"])
    c.numbers.update(orphan_chat_screens_after_each_load=orphans, layouts_start=start["layouts"],
                     layouts_after_each_load=layouts)
    assert orphans == [0, 0], f"orphan chat screens after loads: {orphans} (before the fix: 2 more per load)"
    assert layouts == [start["layouts"]] * 2, f"layouts grew: {start['layouts']} -> {layouts}"


def toast_survives_file_load(c):
    """3.13: a sticky toast still on screen after a file load must keep its timer,
    its visibility flag and its clickable close button."""
    qa = c.qa
    nid = qa.eval('''
from mixar.modules.common.notifications import get_notification_store
result = get_notification_store().push('info', 'QA sticky toast', body='survives a file load', ttl_ms=0)
''')
    time.sleep(1.0)
    _snapshot_and_load(qa, str(c.out / "checkpoints"))
    time.sleep(1.0)
    state = qa.eval(f'''
import bpy
from mixar.modules.common.notifications import get_notification_store
from mixar.modules.common.notifications import toast_timer
result = {{"visible": [str(i.id) for i in get_notification_store().get_visible()],
          "flag": bpy.context.window_manager.get('mixar_toasts_visible'),
          "timer": bpy.app.timers.is_registered(toast_timer._toast_tick)}}
''')
    c.numbers["after_load"] = state
    assert str(nid) in state["visible"], "the sticky toast was lost by the load"
    assert state["flag"] == 1, f"visibility flag after the load: {state['flag']!r} (clicks would fall through)"
    assert state["timer"], "toast timer not running after the load"
    qa.wait("bool(drv.find(surface='toast_close'))", timeout=10)
    qa.click(surface="toast_close")
    time.sleep(1.0)
    left = qa.eval(f"from mixar.modules.common.notifications import get_notification_store\n"
                   f"result = [str(i.id) for i in get_notification_store().get_visible()]")
    assert str(nid) not in left, "clicking the toast's close button did nothing after the load"
