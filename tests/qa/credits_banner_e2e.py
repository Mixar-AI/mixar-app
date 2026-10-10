#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Running out of credits opens the whole-window banner, never a toast.

Replays each trigger and each way out, through the real native banner:

1. the backend ``credit_upgrade`` push (the real ``handle_server_notification``
   path): the banner opens with its art, its six targets and no toast; the
   chat keeps its Upgrade bubble; hover lights the primary button; a click on
   **Upgrade Plan** closes it and reaches the Upgrade destination;
2. a repeat of a push that carries an id does not reopen it;
3. **Refer a Friend**, **Creator Program**, **Use your own API key** and
   **Connect AI apps (MCP)** reach theirs;
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
OPEN_EXPR = "len(drv.find(surface='credits_banner')) == 6"
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
    settle(qa)  # entrance animation (~0.34 s)


def wait_closed(qa):
    """Targets vanish on the choice; the operator lives on for its ~0.16 s
    exit animation, so settle past it before the next open."""
    qa.wait(CLOSED_EXPR, timeout=5)
    settle(qa, 0.4)


def target(qa, text=None, value=None):
    for t in qa.eval(TARGETS):
        if (text is None or t.get('text') == text) and (value is None or t.get('value') == value):
            return t
    raise ScenarioFail(f'no credits_banner target {text or value!r}')


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


def slide(qa, fraction):
    """Use the real thumb and track geometry; leave the destination mocked."""
    return qa.eval(f"""
def go():
    thumb=drv.find_one(surface='credits_banner_slider')
    track=drv.find_one(surface='credits_banner', value='CREATOR')
    r=thumb['rect']; t=track['rect']
    x0=(r[0]+r[2])/2; y=(r[1]+r[3])/2
    end=t[2]-(x0-t[0])
    yield from drv.drag_xy_steps(thumb['_win'], x0, y, x0+(end-x0)*{fraction}, y)
    return True
result=go()
""")


def hold_slider(qa, overshoot=False):
    """Press the thumb and drag it to the end. ``overshoot`` ends the drag the
    way a hand does: past the track's right edge and off its height."""
    return qa.eval(f"""
def hold():
    thumb = drv.find_one(surface='credits_banner_slider')
    track = drv.find_one(surface='credits_banner', value='CREATOR')
    r, t = thumb['rect'], track['rect']
    x0, y = int((r[0] + r[2]) / 2), int((r[1] + r[3]) / 2)
    x1 = int(t[2] - (x0 - t[0]))
    y1 = y
    if {overshoot!r}:
        x1 = int(t[2] + (t[3] - t[1]))
        y1 = int(t[1] - (t[3] - t[1]))
    win = thumb['_win']
    drv.move_to(win, x0, y)
    yield .1
    win.event_simulate(type='LEFTMOUSE', value='PRESS', x=x0, y=y)
    yield .1
    drv.move_to(win, x1, y1)
    yield .15
    return {{'x': x1, 'y': y1}}
result = hold()
""")


def release_slider(qa, point):
    qa.eval(f"""
def release():
    win = drv.find_one(surface='credits_banner_slider')['_win']
    win.event_simulate(type='LEFTMOUSE', value='RELEASE', x={point['x']}, y={point['y']})
    yield .1
    return True
result = release()
""")


def check_slider(qa, out):
    # The track teaches sliding; clicking either the label or knob cannot navigate.
    qa.click(surface='credits_banner', value='CREATOR')
    settle(qa, .25)
    assert len(qa.eval(TARGETS)) == 6
    assert qa.eval("result=drv.find(surface='credits_banner_slider')[0]['text']") == 'Slide to continue'
    snap(qa, out, 'slider_hint', target={'surface': 'credits_banner_card'}, margin=12)
    qa.click(surface='credits_banner_slider')
    assert len(qa.eval(TARGETS)) == 6
    slide(qa, .45)
    settle(qa, .5)
    assert float(qa.eval("result=drv.find(surface='credits_banner_slider')[0]['value']")) == 0
    assert len(qa.eval(TARGETS)) == 6

    # Tab must cancel a held drag; its eventual release cannot open a destination.
    point = hold_slider(qa)
    qa.press('TAB')
    thumb = qa.eval("result=drv.find(surface='credits_banner_slider')[0]")
    assert thumb['detail'] == 'idle', 'Tab left the mouse drag active'
    assert float(thumb['value']) == 0
    release_slider(qa, point)
    assert len(qa.eval(TARGETS)) == 6

    # A full slide opens exactly once, and only on release — even released
    # past the track's end and below it, as a real drag finishes.
    point = hold_slider(qa, overshoot=True)
    assert len(qa.eval(TARGETS)) == 6
    assert qa.eval("result=drv.find(surface='credits_banner_slider')[0]['text']") == 'Release to continue'
    snap(qa, out, 'slider_complete', target={'surface': 'credits_banner_card'}, margin=12)
    release_slider(qa, point)
    wait_closed(qa)


def check_layouts_and_keyboard(qa, out):
    saved=qa.eval('result=[bpy.context.preferences.view.ui_scale,bpy.context.preferences.view.use_reduce_motion]')
    try:
        for scale in (.8, 1.0, 1.25):
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
            open_banner(qa,MANUAL,f'scale_{scale}')
            qa.eval("""
card=drv.find_one(surface='credits_banner_card')['rect']
targets=drv.find(surface='credits_banner')
assert all(card[0]<=t['rect'][0]<t['rect'][2]<=card[2] and card[1]<=t['rect'][1]<t['rect'][3]<=card[3] for t in targets)
result=True
""")
            if scale != 1.0:  # The initial capture already covers the default scale.
                snap(qa,out,f'scale_{scale}',target={'surface':'credits_banner_card'},margin=12)
            qa.press('ESC')
            wait_closed(qa)
        qa.eval('bpy.context.preferences.view.use_reduce_motion=True; result=True')
        open_banner(qa,MANUAL,'keyboard')
        for _ in range(3):
            qa.press('TAB')
        qa.press('RET')
        assert len(qa.eval(TARGETS)) == 6  # Cannot skip the deliberate confirmation.
        for _ in range(5):
            qa.press('RIGHT_ARROW')
        assert float(qa.eval("result=drv.find(surface='credits_banner_slider')[0]['value']")) >= .95
        # Returning to the mouse clears completed keyboard progress.
        qa.click(surface='credits_banner', value='CREATOR')
        assert float(qa.eval("result=drv.find(surface='credits_banner_slider')[0]['value']")) == 0
        assert len(qa.eval(TARGETS)) == 6
        for _ in range(3):
            qa.press('TAB')
        for _ in range(5):
            qa.press('RIGHT_ARROW')
        qa.press('RET')
        wait_closed(qa)
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved[0]}; bpy.context.preferences.view.use_reduce_motion={saved[1]}; result=True')


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT') or
               Path('/tmp') / ('credits_banner-' + time.strftime('%Y%m%d-%H%M%S')))
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
        # By action: the label is "Upgrade Plan", or "Subscribe" on a planless account.
        upgrade = target(qa, value='UPGRADE')
        if upgrade.get('text') not in ('Upgrade Plan', 'Subscribe'):
            raise ScenarioFail(f"unexpected upgrade label {upgrade.get('text')!r}")
        hover(qa, upgrade['rect'])
        if not target(qa, value='UPGRADE').get('sel'):
            raise ScenarioFail('hover did not light the upgrade button')
        snaps['hover_upgrade'] = snap(qa, out, '03_hover_upgrade')
        qa.step('click_upgrade', qa.click, surface='credits_banner', value='UPGRADE')
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
        qa.step('creator_slider',check_slider,qa,out)
        open_banner(qa, MANUAL, 'byok')
        qa.step('click_byok', qa.click, surface='credits_banner', text='Use your own API key')
        qa.step('byok_closed', wait_closed, qa)
        open_banner(qa, MANUAL, 'mcp')
        qa.step('click_mcp', qa.click, surface='credits_banner', text='Connect AI apps (MCP)')
        qa.step('mcp_closed', wait_closed, qa)
        expect_hits(qa, ['UPGRADE', 'REFER', 'CREATOR', 'BYOK', 'MCP'], 'secondary')

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
        expect_hits(qa, ['UPGRADE', 'REFER', 'CREATOR', 'BYOK', 'MCP'], 'dismissals')

        # 5. Job failure → banner, no error toast; burst cooldown holds.
        qa.eval('from mixar.modules.common.notifications.store import '
                'get_notification_store\nget_notification_store().reset()\nresult=True')
        open_banner(qa, JOB_FAILS, 'job')
        no_credit_toasts(qa, 'job')
        qa.press('ESC')
        qa.step('job_closed', wait_closed, qa)
        qa.eval('from mixar.modules.common.notifications import credits_banner as cb\n'
                'cb.request_credits_banner("job")\nresult = True')
        settle(qa, 1.0)
        if qa.eval(TARGETS):
            raise ScenarioFail('burst cooldown did not hold after a close')
        qa.step('layouts_and_keyboard',check_layouts_and_keyboard,qa,out)
        expect_hits(qa, ['UPGRADE', 'REFER', 'CREATOR', 'BYOK', 'MCP', 'CREATOR'], 'keyboard')
        open_banner(qa, MANUAL, 'reverse_focus')
        qa.press('TAB', shift=True)
        qa.press('RET')
        wait_closed(qa)
        expect_hits(qa, ['UPGRADE', 'REFER', 'CREATOR', 'BYOK', 'MCP', 'CREATOR'], 'reverse_focus_dismisses')
    finally:
        qa.eval(JOB_CLEANUP)
        qa.eval(TEARDOWN)
    return {'snaps': snaps}


if __name__ == '__main__':
    run_scenario('credits_banner_e2e', run)
