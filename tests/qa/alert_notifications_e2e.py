#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Alerts arrive as notifications in the bottom-left lane, never as popups.

Replays the case that used to open two popup menus under the cursor ("Image to
3D batch complete / Succeeded: 4", "Auto Rig complete / Succeeded: 1"):
four Image to 3D jobs and one Auto Rig job run, Image to 3D finishes first,
Auto Rig later. Then raises the other converted alerts (a generation error, a
refused chat send and a plugin-import result) through their real helpers.

Jobs are local fixtures on private QA queues driven through the real
FeatureQueue/_notify path; the catalog label lookup is pinned for the run so
the titles do not depend on a signed-in catalog. No backend calls, no credits.
Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated Dev app,
then review the screenshots alongside the state verdict.
"""
import os
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

SETUP = '''
from mixar.modules.common.job_queue.core import labels, queue_manager as qm
from mixar.modules.common.job_queue.core import enqueue_toast
from mixar.modules.common.job_queue.core.job import Job, JobState
from mixar.modules.common.notifications.store import get_notification_store

class QAInertJob(Job):
    def submit(self, on_success, on_error):
        pass  # stays PENDING until the scenario moves it

ns = bpy.app.driver_namespace
ns['qa_alert_label'] = labels.catalog_feature_label
labels.catalog_feature_label = lambda cap, svc: {
    'qa_image_to_3d': 'Image to 3D', 'qa_auto_rig': 'Auto Rig'}.get(svc, '')
get_notification_store().reset()
enqueue_toast.reset_state()
models = qm.get_queue('qa_alert_image_to_3d')
rig = qm.get_queue('qa_alert_auto_rig')
ns['qa_alert_jobs'] = {
    'models': [QAInertJob(label=f'QA model {i}', service='qa_image_to_3d')
               for i in range(4)],
    'rig': [QAInertJob(label='QA rig', service='qa_auto_rig')],
}
for job in ns['qa_alert_jobs']['models']:
    models.submit(job)
rig.submit(ns['qa_alert_jobs']['rig'][0])
result = True
'''

FINISH = '''
from mixar.modules.common.job_queue.core import queue_manager as qm
from mixar.modules.common.job_queue.core.job import JobState
ns = bpy.app.driver_namespace
for job in ns['qa_alert_jobs'][{group!r}]:
    job.state = JobState.SUCCESS
qm.get_queue({queue!r})._notify()
result = True
'''

TEARDOWN = '''
from mixar.modules.common.job_queue.core import labels, queue_manager as qm
from mixar.modules.common.job_queue.core import enqueue_toast
from mixar.modules.common.notifications.store import get_notification_store
ns = bpy.app.driver_namespace
labels.catalog_feature_label = ns.pop('qa_alert_label')
ns.pop('qa_alert_jobs', None)
for key in ('qa_alert_image_to_3d', 'qa_alert_auto_rig'):
    qm._queues.pop(key, None)
enqueue_toast.reset_state()
get_notification_store().reset()
result = True
'''


def settle(qa):
    qa.eval('def settle():\n    yield 1.1\n    return True\nresult=settle()')


def capture(qa, out, name):
    qa.eval('''
def park():
    win=drv.main_window()
    area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
    drv.move_to(win, area.x+area.width*3//4, area.y+area.height*3//4)
    yield .3
    return True
result=park()
''')
    return qa.snap(str(out / (name + '.png')))


def lane(qa, expected):
    """Every toast is in the notification lane, stacked, with these titles."""
    return qa.eval(f'''
from mixar.modules.common.notifications import toast_renderer as tr
toasts=drv.find(surface='toast')
titles=[t['text'] for t in toasts]
assert sorted(titles)==sorted({expected!r}), titles
t=toasts[0]
area=t['_area']
r=next(r for r in area.regions if r.type=='WINDOW')
cards=tr.toast_layouts_by_region[r.as_pointer()]
with bpy.context.temp_override(window=t['_win'], area=area, region=r):
    left,bottom,right,top,ceiling=r.mixar_agent_panel_bounds()
scale=bpy.context.preferences.system.ui_scale/2
expected=top+16*scale if top>bottom else bottom
assert abs(cards[0]['rect'][1]-expected)<1, (cards[0]['rect'], expected)
for card in cards:
    x,y,w,h=card['rect']
    assert abs(x-left)<1, (card['rect'], left)  # the bottom-left lane
    assert 0<=y and y+h<=ceiling, (card['rect'], ceiling)
for first,second in zip(cards,cards[1:]):
    assert second['rect'][1]>=first['rect'][1]+first['rect'][3]-1  # stacked
bodies={{s['text'] for s in drv.find(surface='toast_body_text')}}
result={{'titles':titles,'bodies':sorted(bodies),'rects':[c['rect'] for c in cards]}}
''')


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(drv.main_window().scene,'mixie_chat_is_busy')", timeout=30)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\nresult=True")
    qa.eval("area=next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')\n"
            "area.spaces.active.shading.background_type='VIEWPORT'\n"
            "area.spaces.active.shading.background_color=(.015,.015,.015)\n"
            "area.tag_redraw()\nresult=True")
    try:
        qa.eval(SETUP)
        settle(qa)
        qa.step('five_jobs_one_sticky_progress_toast', lane, qa,
                ['5 generations in progress'])
        capture(qa, out, 'in-progress')

        qa.eval(FINISH.format(group='models', queue='qa_alert_image_to_3d'))
        settle(qa)
        early = qa.step('image_to_3d_completes_while_rig_runs', lane, qa,
                        ['Generation in progress', 'Image to 3D complete'])
        assert '4 succeeded' in early['bodies'], early
        capture(qa, out, 'image-to-3d-complete')

        qa.eval(FINISH.format(group='rig', queue='qa_alert_auto_rig'))
        settle(qa)
        done = qa.step('auto_rig_completes_and_sticky_clears', lane, qa,
                       ['Image to 3D complete', 'Auto Rig complete'])
        assert '1 succeeded' in done['bodies'], done
        capture(qa, out, 'both-complete')

        qa.eval('''
from types import SimpleNamespace
from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.utils.mixie_space_utils import show_generation_error
from mixar.modules.space_mixie_chat.ui.properties import chat_props
from mixar.modules.plugin_import.ui.operators import plugin_import_ops
get_notification_store().reset()
show_generation_error(SimpleNamespace(), 'Detect Views',
                      'The server could not be reached. Try again in a moment.', '', '')
chat_props._report_send_refused('A reply is still being written.')
plugin_import_ops._notify_summary(SimpleNamespace(
    imported=3, already_present=1, enabled=2, failed=0, enable_failed=1),
    'node_wrangler: missing dependency')
result=True
''')
        settle(qa)
        qa.step('errors_and_refusals_share_the_lane', lane, qa,
                ['Detect Views failed', 'Message not sent', 'Blender Plugin Import'])
        capture(qa, out, 'alerts')
    finally:
        qa.eval(TEARDOWN)
    return {'backend_calls': 0, 'snapshots': str(out), 'early': early, 'done': done}


if __name__ == '__main__':
    # The external launcher returns before the in-app server binds its socket.
    deadline = time.monotonic() + 30
    while True:
        try:
            with socket.create_connection(('127.0.0.1', int(os.environ.get('MIXAR_QA_PORT', '4777'))), timeout=1):
                break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    run_scenario('alert_notifications_e2e', run)
