# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Profile card and UV Transform panel drawn while their Python operators are unregistered.

Replays the Windows prod crash (`RNA_string_set` <- `add_usage` <- topbar.py
`layout.mixar_profile_card()`): before `MIXAR_OT_open_billing` registered,
`Layout::op()` returned a null pointer and the card wrote `target` through it.
The UV editor's Transform panel does the same with `MIXAR_OT_mirror`
(`RNA_enum_set_identifier` on `axis`). The scenario unregisters both, opens
the profile card and redraws the UV editor (Engine mode, UV Editing, Edit
Mode, Mixar UV mode, Transform tool), then registers them again.

The card's Credits section and CTA need a signed-in account with usage.
The usage poller is paused first (its in-flight fetch drained), then a guest
session is pinned to a synthetic signed-in state with credits. Paused, the
poller cannot call `/subscriptions/status` with the guest token (403) and
overwrite the pinned figures with 0 / "couldn't refresh" mid-assertion. No
credits are spent; the poller restarts in `finally`.

- Unfixed build (v4.4.0, blastoff before this branch): the app crashes in
  `RNA_string_set` opening the card; `open_card_without_billing` loses its
  connection.
- PR #1984's first commit (null-check only): the card opens but paints an
  accent pill reading "MIXAR_OT_open_billing"; `card_has_no_cta` fails.
  With #1980 alone the UV step crashes in `RNA_enum_set_identifier`.
- Fixed build: the card shows its Credits section with no CTA and no idname
  label; the Transform panel draws two greyed "MIXAR_OT_mirror" labels; the
  app survives. Once registered again the card shows an enabled "Buy Credits"
  and the panel its X / Y Axis buttons.

The classes, account fields, workspace and QA mesh are restored in `finally`,
whatever failed. Inspect the saved PNGs as well as the verdict.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4836 \
  QA_SCENARIO_OUT=/tmp/layout-missing-op python3 tests/qa/layout_missing_operator_e2e.py
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

BILLING = 'MIXAR_OT_open_billing'
MIRROR = 'MIXAR_OT_mirror'
NAMES = (BILLING, MIRROR)
SAVED = 'qa_layout_missing_op_saved'
ACCOUNT = 'qa_layout_missing_op_account'
UV_STATE = 'qa_layout_missing_op_uv'
MESH = 'QA Missing Op UV'
CARD_READY = "bool(drv.find(op='MIXAR_BYOK_OT_open_dialog', popup=True))"

# Saved BEFORE unregistering, so cleanup can always put them back.
UNREGISTER = f'''
ns = bpy.app.driver_namespace
saved = ns.setdefault({SAVED!r}, {{}})
for name in {NAMES!r}:
    cls = getattr(bpy.types, name, None)
    assert cls is not None, name + ' was not registered to begin with'
    saved[name] = cls
    bpy.utils.unregister_class(cls)
result = {{n: getattr(bpy.types, n, None) is None for n in {NAMES!r}}}
'''

REGISTER = f'''
ns = bpy.app.driver_namespace
saved = ns.get({SAVED!r}, {{}})
restored, errors = [], []
for name, cls in list(saved.items()):
    try:
        if getattr(bpy.types, name, None) is None:
            bpy.utils.register_class(cls)
            restored.append(name)
        del saved[name]
    except Exception as exc:
        errors.append(name + ': ' + repr(exc))
if not saved:
    ns.pop({SAVED!r}, None)
result = {{'restored': restored, 'errors': errors,
          'registered': {{n: getattr(bpy.types, n, None) is not None for n in {NAMES!r}}}}}
'''

# The card draws Credits and its CTA only for a signed-in account whose usage
# arrived. A guest instance is pinned to that state for the scenario.
FIELDS = ('mixie_chat_is_logged_in', 'mixie_chat_is_guest', 'mixar_account_name',
          'mixar_usage_ready', 'mixar_usage_can_top_up', 'mixar_usage_credits_remaining')
POLLER = "__import__('mixar.modules.common.usage.core.poller', fromlist=['x'])"
PAUSE_POLLER = f'''
poller = {POLLER}
ns = bpy.app.driver_namespace
ns.setdefault({ACCOUNT!r} + '_poller', poller._timer_registered)
poller.stop()
result = poller._fetch_in_flight
'''

PIN_ACCOUNT = f'''
wm = bpy.context.window_manager
ns = bpy.app.driver_namespace
assert not {POLLER}._timer_registered, 'usage poller still running'
ns.setdefault({ACCOUNT!r}, {{n: getattr(wm, n) for n in {FIELDS!r}}})
real = wm.mixie_chat_is_logged_in and not wm.mixie_chat_is_guest
if not real:
    wm.mixie_chat_is_guest = False
    wm.mixie_chat_is_logged_in = True
    wm.mixar_account_name = 'QA Billing'
wm.mixar_usage_ready = True
wm.mixar_usage_can_top_up = True
wm.mixar_usage_credits_remaining = max(wm.mixar_usage_credits_remaining, 1234)
for a in drv.main_window().screen.areas:
    a.tag_redraw()
from mixar.modules.common.utils import topbar_layout
result = {{'real_account': real,
          'label': topbar_layout.account_label(wm, drv.main_window().scene.mixie_chat_user_id, 'Guest')}}
'''

RESTORE_ACCOUNT = f'''
wm = bpy.context.window_manager
saved = bpy.app.driver_namespace.pop({ACCOUNT!r}, None) or {{}}
for name in {FIELDS!r}:
    if name in saved and getattr(wm, name) != saved[name]:
        setattr(wm, name, saved[name])
if bpy.app.driver_namespace.pop({ACCOUNT!r} + '_poller', False):
    {POLLER}.start()
for a in drv.main_window().screen.areas:
    a.tag_redraw()
result = sorted(saved)
'''

UV_SETUP = f'''
w = drv.main_window()
s = w.scene
bpy.app.driver_namespace.setdefault({UV_STATE!r}, {{'mode': drv.ui_mode(), 'workspace': w.workspace.name}})
m = bpy.data.meshes.new({MESH!r})
m.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
m.update()
m.uv_layers.new(name='UVMap')
o = bpy.data.objects.new({MESH!r}, m)
s.collection.objects.link(o)
for other in w.view_layer.objects:
    other.select_set(False)
o.select_set(True)
w.view_layer.objects.active = o
result = o.name
'''

UV_TOOL = '''
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'IMAGE_EDITOR')
if a.spaces.active.mode != 'MIXAR_UV':
    a.spaces.active.mode = 'MIXAR_UV'
r = next(r for r in a.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.wm.tool_set_by_id(name='builtin.transform', space_type='IMAGE_EDITOR')
a.tag_redraw()
result = w.workspace.tools.from_space_image_mode('MIXAR_UV', create=False).idname
'''

UV_CLEANUP = f'''
o = bpy.data.objects.get({MESH!r})
if o is not None:
    if o.mode != 'OBJECT':
        w = drv.main_window()
        a = next(a for a in w.screen.areas if a.type in ('VIEW_3D', 'IMAGE_EDITOR'))
        with bpy.context.temp_override(window=w, area=a, active_object=o, object=o):
            bpy.ops.object.mode_set(mode='OBJECT')
    me = o.data
    bpy.data.objects.remove(o, do_unlink=True)
    if me.users == 0:
        bpy.data.meshes.remove(me)
result = True
'''


def _redraw(area_type, iterations):
    """Draw the whole main window N times now, then tag it for the event loop too."""
    return f'''
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == {area_type!r})
region = next(r for r in area.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=win, area=area, region=region):
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations={iterations})
for a in win.screen.areas:
    a.tag_redraw()
result = bpy.app.version_string
'''


def _close(qa):
    for _ in range(3):
        if not qa.find(popup=True)['total']:
            return
        qa.press('ESC')
    if qa.find(popup=True)['total']:
        raise ScenarioFail('a popup stayed open')


def _open_card(qa, label):
    """Click the account pill (the right-most top-bar popover) and wait for the card."""
    _close(qa)
    pills = qa.find(area_type='TOPBAR', but_type='Popover', popup=False, limit=50)['widgets']
    if not pills:
        raise ScenarioFail('no top-bar popover to open the profile card')
    pill = next((w for w in pills if label and w.get('text') == label), None) \
        or max(pills, key=lambda w: w['rect'][2])
    qa.cmd('click_xy', x=pill['center'][0], y=pill['center'][1], window=pill['window'])
    qa.wait(CARD_READY, timeout=6)


def _card(qa):
    widgets = qa.cmd('dump', popup=True, limit=200)['widgets']
    return {'billing': [{'text': w.get('text'), 'enabled': w.get('enabled')}
                        for w in widgets if w.get('op') == BILLING],
            'idname_labels': [w.get('text') for w in widgets if 'open_billing' in (w.get('text') or '')],
            'credits_section': any((w.get('text') or '') == 'Credits' for w in widgets)}


def _card_has_no_cta(qa):
    card = _card(qa)
    if not card['credits_section']:
        raise ScenarioFail(f'the card did not draw its usage section: {card}')
    if card['billing'] or card['idname_labels']:
        raise ScenarioFail(f'CTA drawn without its operator: {card}')
    return card


def _card_has_cta(qa):
    card = _card(qa)
    if len(card['billing']) != 1 or not card['billing'][0]['enabled'] or card['idname_labels']:
        raise ScenarioFail(f'Buy Credits missing after re-registration: {card}')
    return card


def _mirror(qa):
    return {'buttons': qa.find(area_type='IMAGE_EDITOR', op=MIRROR, popup=False)['total'],
            'idname_labels': qa.find(area_type='IMAGE_EDITOR', text=MIRROR, popup=False)['total']}


def _workspace(qa, name):
    # Not `qa.step(..., qa.cmd, 'workspace', name=...)`: step() owns `name`.
    return qa.cmd('workspace', name=name)


def _restore_workspace(qa):
    state = qa.eval(f'result = bpy.app.driver_namespace.pop({UV_STATE!r}, None)')
    if not state:
        return
    if state['mode'] == 'engine':
        if qa.eval('result = drv.main_window().workspace.name') != state['workspace']:
            _workspace(qa, state['workspace'])
    else:
        qa.cmd('set_mode', mode=state['mode'])


def _pause_poller(qa):
    """Stop the usage poller and let a fetch already in flight land first."""
    qa.eval(PAUSE_POLLER)
    qa.wait(f'not {POLLER}._fetch_in_flight', timeout=15)
    time.sleep(0.5)  # its write-back is a 0 s one-shot timer


def _snap(qa, out, label):
    path = str(out / f'layout-missing-operator-{label}.png')
    qa.snap(path)
    return path


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/layout-missing-op')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.step('dismiss_splash', qa.dismiss_splash)
    restore, snaps, report = None, [], {}
    try:
        qa.step('pause_usage_poller', _pause_poller, qa)
        account = qa.step('pin_signed_in_usage', qa.eval, PIN_ACCOUNT)
        qa.step('open_card_registered', _open_card, qa, account['label'])
        report['card_before'] = qa.step('card_has_cta', _card_has_cta, qa)
        _close(qa)

        qa.step('uv_mesh', qa.eval, UV_SETUP)
        qa.step('engine_mode', qa.cmd, 'set_mode', mode='engine')
        qa.step('uv_workspace', _workspace, qa, 'UV Editing')
        qa.wait(f"bpy.data.objects[{MESH!r}].mode == 'EDIT'", timeout=10)
        tool = qa.step('transform_tool', qa.eval, UV_TOOL)
        if tool != 'builtin.transform':
            raise ScenarioFail(f'Transform tool not active: {tool}')
        qa.step('mirror_buttons_drawn', qa.wait,
                f"len(drv.find(area_type='IMAGE_EDITOR', op={MIRROR!r})) == 2", timeout=8)
        snaps.append(_snap(qa, out, 'registered'))

        qa.step('unregister_operators', qa.eval, UNREGISTER)
        # The unfixed build crashes building this popover (null OperatorProperties).
        qa.step('open_card_without_billing', _open_card, qa, account['label'])
        report['card_missing'] = qa.step('card_has_no_cta', _card_has_no_cta, qa)
        snaps.append(qa.step('snap_card_missing', _snap, qa, out, 'card-missing'))
        _close(qa)
        # Without the UI_OPERATOR_ERROR_RET fix this draw crashes in RNA_enum_set_identifier.
        qa.step('uv_redraws_without_mirror', qa.eval, _redraw('IMAGE_EDITOR', 8))
        qa.step('mirror_greyed', qa.wait,
                f"not drv.find(area_type='IMAGE_EDITOR', op={MIRROR!r}) and "
                f"len(drv.find(area_type='IMAGE_EDITOR', text={MIRROR!r})) == 2", timeout=8)
        report['uv_missing'] = _mirror(qa)
        snaps.append(qa.step('snap_uv_missing', _snap, qa, out, 'uv-missing'))

        restore = qa.step('register_operators', qa.eval, REGISTER)
        if restore['errors'] or not all(restore['registered'].values()):
            raise ScenarioFail(f're-registration failed: {restore}')
        qa.step('uv_redraws_with_mirror', qa.eval, _redraw('IMAGE_EDITOR', 2))
        qa.step('mirror_buttons_back', qa.wait,
                f"len(drv.find(area_type='IMAGE_EDITOR', op={MIRROR!r})) == 2", timeout=8)
        report['uv_restored'] = _mirror(qa)
        qa.step('open_card_restored', _open_card, qa, account['label'])
        report['card_restored'] = qa.step('card_has_cta_again', _card_has_cta, qa)
        snaps.append(qa.step('snap_card_restored', _snap, qa, out, 'card-restored'))
    finally:
        if restore is None or restore['errors']:
            # Never leave the session without its operators, whatever failed.
            try:
                restore = qa.eval(REGISTER)
            except Exception as exc:  # the app is gone (the unfixed build)
                restore = {'errors': [repr(exc)]}
            print(f'[scenario] cleanup re-registration: {restore}', flush=True)
        for label, fn in (('close', lambda: _close(qa)),
                          ('workspace', lambda: _restore_workspace(qa)),
                          ('uv_mesh', lambda: qa.eval(UV_CLEANUP)),
                          ('account', lambda: qa.eval(RESTORE_ACCOUNT))):
            try:
                fn()
            except Exception as exc:
                print(f'[scenario] cleanup {label} failed: {exc!r}', flush=True)
    return {**report, 'restore': restore, 'snaps': snaps, 'credits_spent': 0}


if __name__ == '__main__':
    run_scenario('layout_missing_operator_e2e', run)
