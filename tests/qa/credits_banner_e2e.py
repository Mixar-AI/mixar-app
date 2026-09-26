#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Running out of credits opens the whole-window banner, never a toast.

Replays each trigger and each way out, through the real native banner:

1. the backend ``credit_upgrade`` push (the real ``handle_server_notification``
   path): the banner opens with its art, its four targets and no toast; the
   chat keeps its Upgrade bubble; hover lights the primary button; a click on
   **Upgrade Plan** closes it and reaches the Upgrade destination;
2. a repeat of a push that carries an id does not reopen it;
3. **Refer a Friend** and **Apply to Creator Program** reach theirs;
4. a click inside the card that is not a button keeps it open; Esc closes it;
   a click on the dimmed backdrop closes it;
5. a job that fails out of credits opens the banner and pushes no error toast;
   a second request inside the burst cooldown does not reopen it.

Destinations are recorded instead of opening a browser (the module-level
``DESTINATIONS`` map is swapped for the run). No backend calls, no credits.
Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated Dev app,
then review the screenshots alongside the state verdict.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

SETUP = '''
import sys
from mixar.modules.common.notifications import credits_banner as cb
from mixar.modules.common.notifications.store import get_notification_store
ops = next(m for n, m in sys.modules.items() if n.endswith('credits_banner_ops'))
ns = bpy.app.driver_namespace
ns['qa_cb_dest'] = dict(ops.DESTINATIONS)
ns['qa_cb_hits'] = []
for key in list(ops.DESTINATIONS):
    ops.DESTINATIONS[key] = (lambda k=key: ns['qa_cb_hits'].append(k))
cb.reset_state()
get_notification_store().reset()
result = True
'''

TEARDOWN = '''
import sys
from mixar.modules.common.notifications import credits_banner as cb
ops = next(m for n, m in sys.modules.items() if n.endswith('credits_banner_ops'))
ns = bpy.app.driver_namespace
ops.DESTINATIONS.update(ns.pop('qa_cb_dest', {}))
ns.pop('qa_cb_hits', None)
cb.reset_state()
result = True
'''

PUSH = '''
from mixar.modules.space_mixie_chat.core.connection_manager import handle_server_notification
handle_server_notification({'type': 'credit_upgrade', 'id': %r,
                            'title': "You're out of credits",
                            'action_url': 'https://example.test/plan'})
result = True
'''

MANUAL = '''
bpy.ops.mixar.show_credits_banner()
result = True
'''

JOB_FAILS = '''
from mixar.modules.common.notifications import credits_banner as cb
from mixar.modules.common.job_queue.core import queue_manager as qm
from mixar.modules.common.job_queue.core.error_helpers import OUT_OF_CREDITS_MESSAGE
from mixar.modules.common.job_queue.core.job import Job, JobState

class QAInertJob(Job):
    def submit(self, on_success, on_error):
        pass

cb.reset_state()
queue = qm.get_queue('qa_credits_banner')
job = QAInertJob(label='QA out of credits', service='qa_credits')
queue.submit(job)
job.state = JobState.FAILED
job.user_message = OUT_OF_CREDITS_MESSAGE
queue._notify()
result = True
'''

JOB_CLEANUP = '''
from mixar.modules.common.job_queue.core import queue_manager as qm
qm._queues.pop('qa_credits_banner', None)
result = True
'''

TARGETS = "result = [t for t in drv.find(surface='credits_banner')]"
OPEN_EXPR = "len(drv.find(surface='credits_banner')) == 4"
CLOSED_EXPR = "len(drv.find(surface='credits_banner')) == 0"
HITS = "result = list(bpy.app.driver_namespace['qa_cb_hits'])"
TOASTS = ("from mixar.modules.common.notifications.store import get_notification_store\n"
          "result = [(n.type.value if hasattr(n.type, 'value') else str(n.type), n.title)"
          " for n in get_notification_store().get_visible()]")


def settle(qa, seconds=0.8):
    qa.eval(f'def settle():\n    yield {seconds}\n    return True\nresult=settle()')


def snap(qa, out, name, **kw):
    return qa.cmd('snap', path=str(out / (name + '.png')), **kw)


def open_banner(qa, how, label):
    qa.step(f'{label}_trigger', qa.eval, how)
    qa.step(f'{label}_open', qa.wait, OPEN_EXPR, timeout=10)
    settle(qa)  # entrance animation (~0.34 s) plus the button stagger


def wait_closed(qa):
    """Targets vanish on the choice; the operator lives on for its ~0.16 s
    exit animation, so settle past it before the next open."""
    qa.wait(CLOSED_EXPR, timeout=5)
    settle(qa, 0.4)


def target(qa, text):
    for t in qa.eval(TARGETS):
        if t.get('text') == text:
            return t
    raise ScenarioFail(f'no credits_banner target {text!r}')


def hover(qa, rect):
    x = (rect[0] + rect[2]) // 2
    y = (rect[1] + rect[3]) // 2
    qa.eval(f'''
def go():
    drv.move_to(drv.main_window(), {x}, {y})
    yield .5
    return True
result = go()
''')


def expect_hits(qa, expected, label):
    hits = qa.eval(HITS)
    if hits != expected:
        raise ScenarioFail(f'{label}: destinations {hits!r}, expected {expected!r}')


def no_credit_toasts(qa, label):
    toasts = qa.eval(TOASTS)
    credit = [t for t in toasts
              if t[0] == 'credit_upgrade' or 'credit' in (t[1] or '').lower()
              or 'QA out of credits' == t[1]]
    if credit:
        raise ScenarioFail(f'{label}: credit toasts still pushed: {credit!r}')


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT') or
               Path(__file__).resolve().parents[2] / 'out' /
               ('credits_banner-' + time.strftime('%Y%m%d-%H%M%S')))
    out.mkdir(parents=True, exist_ok=True)
    qa.step('layout_ready', qa.wait,
            "'VIEW_3D' in {a.type for a in drv.main_window().screen.areas}", timeout=30)
    # UI auto-discovery loads operators in time-budgeted batches after boot.
    qa.step('ops_ready', qa.wait,
            "any(n.endswith('credits_banner_ops') for n in __import__('sys').modules)",
            timeout=60)
    qa.step('setup', qa.eval, SETUP)
    snaps = {}
    try:
        snaps['before'] = snap(qa, out, '00_before')

        # 1. Backend push → banner, no toast; chat keeps its bubble.
        open_banner(qa, PUSH % 'qa-push-1', 'push')
        card = qa.eval("result = drv.find(surface='credits_banner_card')")
        if not card or card[0].get('text') != 'art':
            raise ScenarioFail(f'banner art not drawn: {card!r}')
        no_credit_toasts(qa, 'push')
        chat = qa.eval("result = any(m.bubble_id.startswith('credit-upgrade-') for m in "
                       "bpy.context.scene.mixie_chat_messages)")
        if not chat:
            raise ScenarioFail('push: chat Upgrade bubble missing')
        snaps['open'] = snap(qa, out, '01_open')
        snaps['annotated'] = snap(qa, out, '02_annotated',
                                  annotate={'surface': 'credits_banner'})
        upgrade = target(qa, 'Upgrade Plan')
        hover(qa, upgrade['rect'])
        if not target(qa, 'Upgrade Plan').get('sel'):
            raise ScenarioFail('hover did not light Upgrade Plan')
        snaps['hover_upgrade'] = snap(qa, out, '03_hover_upgrade')
        creator = target(qa, 'Apply to Creator Program')
        hover(qa, creator['rect'])
        snaps['hover_creator'] = snap(qa, out, '04_hover_creator')
        qa.step('click_upgrade', qa.click, surface='credits_banner', text='Upgrade Plan')
        qa.step('upgrade_closed', wait_closed, qa)
        expect_hits(qa, ['UPGRADE'], 'upgrade')

        # 2. Sync replay of the same push id: no reopen (cooldown reset first).
        qa.eval('from mixar.modules.common.notifications import credits_banner as cb\n'
                'cb._last_activity = 0.0\nresult = True')
        qa.eval(PUSH % 'qa-push-1')
        settle(qa, 1.0)
        if qa.eval(TARGETS):
            raise ScenarioFail('sync replay reopened the banner')

        # 3. Secondary destinations.
        open_banner(qa, MANUAL, 'refer')
        qa.step('click_refer', qa.click, surface='credits_banner', text='Refer a Friend')
        qa.step('refer_closed', wait_closed, qa)
        open_banner(qa, MANUAL, 'creator')
        qa.step('click_creator', qa.click, surface='credits_banner',
                text='Apply to Creator Program')
        qa.step('creator_closed', wait_closed, qa)
        expect_hits(qa, ['UPGRADE', 'REFER', 'CREATOR'], 'secondary')

        # 4. Ways out, and a click that is not one.
        open_banner(qa, MANUAL, 'inside')
        card_rect = qa.eval("result = drv.find(surface='credits_banner_card')[0]['rect']")
        cx = (card_rect[0] + card_rect[2]) // 2
        cy = int(card_rect[1] + (card_rect[3] - card_rect[1]) * 0.6)
        qa.cmd('click_xy', x=cx, y=cy)
        settle(qa, 0.5)
        if not qa.eval(TARGETS):
            raise ScenarioFail('a click on the art closed the banner')
        qa.press('ESC')
        qa.step('esc_closed', wait_closed, qa)
        open_banner(qa, MANUAL, 'backdrop')
        qa.cmd('click_xy', x=max(8, int(card_rect[0]) // 2), y=int(card_rect[1]) // 2 + 8)
        qa.step('backdrop_closed', wait_closed, qa)
        expect_hits(qa, ['UPGRADE', 'REFER', 'CREATOR'], 'dismissals')

        # 5. Job failure → banner, no error toast; burst cooldown holds.
        qa.eval('from mixar.modules.common.notifications.store import '
                'get_notification_store\nget_notification_store().reset()\nresult=True')
        open_banner(qa, JOB_FAILS, 'job')
        no_credit_toasts(qa, 'job')
        snaps['job'] = snap(qa, out, '05_job_failure')
        qa.press('ESC')
        qa.step('job_closed', wait_closed, qa)
        qa.eval('from mixar.modules.common.notifications import credits_banner as cb\n'
                'cb.request_credits_banner("job")\nresult = True')
        settle(qa, 1.0)
        if qa.eval(TARGETS):
            raise ScenarioFail('burst cooldown did not hold after a close')
        snaps['after'] = snap(qa, out, '06_after')
    finally:
        qa.eval(JOB_CLEANUP)
        qa.eval(TEARDOWN)
    return {'snaps': snaps}


if __name__ == '__main__':
    run_scenario('credits_banner_e2e', run)
