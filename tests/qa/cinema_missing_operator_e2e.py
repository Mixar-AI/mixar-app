# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Cinema strip drawn while its Python operators are unregistered; no backend or credits.

Replays the 4.4.0 macOS crash (`RNA_boolean_set` <- `cinema_draw_top_strip`):
the strip writes the eyedropper chip's `clear` through
`button_operator_ptr_ensure()`, which returned null while
`MIXAR_OT_director_pick_track_target` was not registered yet. The scenario
enters Cinema Mode, gives the shot a track target (so the chip writes
`clear=True`, the prod path), unregisters that operator and, as a second
Mixar call site, `MIXAR_OT_director_pick_camera` (the My Cameras rows write
`camera_name` with `RNA_string_set` the same way), then forces redraws.

- Unfixed build (v4.4.0 and earlier): the app crashes in `RNA_boolean_set` on
  the first redraw; the `redraws_without_operators` step loses its connection.
- Fixed build: the app survives, both chips draw greyed with no operator, and
  once the classes are registered again they carry their operators and a real
  click on the eyedropper chip clears the tracking (proof that `clear=True`
  reached the operator through the rebuilt properties).

Needs the designed Cinema surface (a window tall enough for it, as
`director_cinema_surface_e2e`). The classes are registered again in `finally`,
whatever failed. Inspect the saved PNGs as well as the verdict.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4836 \
  QA_SCENARIO_OUT=/tmp/cinema-missing-op python3 tests/qa/cinema_missing_operator_e2e.py
"""
import os
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

TRACK = 'MIXAR_OT_director_pick_track_target'
CAMERA = 'MIXAR_OT_director_pick_camera'
NAMES = (TRACK, CAMERA)
# Chips are the `But` under each published target rect (a button whose
# operator is missing has no `op` to find it by). These literal tooltips from
# view3d_director_cinema_top.cc / _cameras.cc only break a tie.
TRACK_TIP = 'Stop tracking the picked object'
CAMERA_TIP = 'Direct this camera'
SAVED = 'qa_missing_op_saved'
TARGET = 'qa_missing_op_target'
SHOT = ('(lambda d: d.shots[d.active_shot_index] if len(d.shots) else None)'
        '(drv.main_window().scene.mixar_director)')

SETUP = f'''
scene = drv.main_window().scene
shot = {SHOT}
assert shot is not None and shot.camera is not None, 'Cinema Mode adopted no shot'
target = next((o for o in scene.objects if o.type == 'MESH'), None)
if target is None:
    target = bpy.data.objects.new('QA Track Target', bpy.data.meshes.new('QA Track Target'))
    scene.collection.objects.link(target)
    bpy.app.driver_namespace[{TARGET!r}] = target.name
shot.track_target = target
assert shot.camera.constraints.get('Mixar Director Track') is not None
result = {{'shot': shot.name, 'camera': shot.camera.name, 'target': target.name}}
'''

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

UNTRACK = f'''
ns = bpy.app.driver_namespace
shot = {SHOT}
if shot is not None:
    shot.track_target = None
made = ns.pop({TARGET!r}, None)
if made and bpy.data.objects.get(made) is not None:
    bpy.data.objects.remove(bpy.data.objects[made], do_unlink=True)
result = True
'''


def _redraw(iterations):
    """Draw the whole main window N times now, then tag it for the event loop too."""
    return f'''
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=win, area=area, region=region):
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations={iterations})
for a in win.screen.areas:
    a.tag_redraw()
result = bpy.app.version_string
'''


CHIPS = f'''
widgets = drv.find(area_type='VIEW_3D', region_type='WINDOW')
def chip(surface, tip):
    """The plain `But` under each published target rect; the tooltip only
    breaks a tie (it is the one thing an operator-less button keeps)."""
    rects = [w['rect'] for w in widgets if w.get('surface') == surface]
    hits, by_tip = [], 0
    for r in rects:
        inside = [w for w in widgets if w.get('type') == 'But'
                  and r[0] <= w['center'][0] <= r[2] and r[1] <= w['center'][1] <= r[3]]
        if len(inside) != 1:
            inside = [w for w in inside if w.get('tip') == tip]
            by_tip += 1
        hits += [{{'op': w.get('op'), 'enabled': w['enabled']}} for w in inside]
    return {{'targets': len(rects), 'buttons': hits, 'tip_fallbacks': by_tip}}
shot = {SHOT}
result = {{'track': chip('director_track', {TRACK_TIP!r}),
          'camera': chip('director_camera', {CAMERA_TIP!r}),
          'tracking': shot is not None and shot.track_target is not None,
          'registered': {{n: getattr(bpy.types, n, None) is not None for n in {NAMES!r}}}}}
'''


def _chips(qa, op_expected):
    """Both chips drawn, each button carrying `op_expected` (None = no operator)."""
    state = qa.eval(CHIPS)
    for key, name in (('track', TRACK), ('camera', CAMERA)):
        buttons = state[key]['buttons']
        if not buttons or len(buttons) != state[key]['targets']:
            raise ScenarioFail(f'{key} chip not drawn: {state}')
        want = name if op_expected else None
        if any(b['op'] != want or b['enabled'] != bool(op_expected) for b in buttons):
            raise ScenarioFail(f'{key} chip: expected op={want} enabled={bool(op_expected)}: {state}')
    return state


def _wait_chips(qa, op_expected, timeout=8.0):
    """`_chips` once the event loop has redrawn the strip into that state."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return _chips(qa, op_expected)
        except ScenarioFail:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.25)


def _snap(qa, out, label):
    path = str(out / f'cinema-missing-operator-{label}.png')
    qa.snap(path)
    return path


def _enter_cinema(qa):
    qa.wait("len(drv.find(op='MIXAR_OT_director_enter')) >= 1", timeout=20)
    if not qa.eval('result = drv.main_window().scene.mixar_director.is_directing'):
        qa.click(op='MIXAR_OT_director_enter')
    qa.wait('drv.main_window().scene.mixar_director.is_directing', timeout=12)
    # Entering adopts the scene camera (or makes one from the view). If a
    # reused instance still came up without a directed camera, add one from
    # the surface's own entry point.
    if not qa.eval(f'result = ({SHOT}) is not None and ({SHOT}).camera is not None'):
        qa.wait("len(drv.find(surface='director_add_camera')) == 1", timeout=12)
        qa.click(surface='director_add_camera')
        qa.wait(f'({SHOT}) is not None and ({SHOT}).camera is not None', timeout=12)
    # Only the designed (wide) surface draws the top strip's eyedropper chip.
    qa.wait("len(drv.find(surface='director_track')) == 1 and "
            "len(drv.find(surface='director_camera')) >= 1", timeout=12)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/cinema-missing-op')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.step('wait_login', qa.cmd, 'wait_login', timeout=90)
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('enter_cinema', _enter_cinema, qa)
    restore = None
    try:
        setup = qa.step('track_target', qa.eval, SETUP)
        qa.step('chip_clears_tracking', qa.wait,
                f"len(drv.find(surface='director_track', value='clear')) == 1 and "
                f"len(drv.find(op={TRACK!r}, enabled=True, area_type='VIEW_3D')) == 1", timeout=8)
        before = qa.step('chips_with_operators', _chips, qa, True)
        snaps = [_snap(qa, out, 'registered')]
        qa.step('unregister_operators', qa.eval, UNREGISTER)
        # The unfixed build crashes inside this draw (null OperatorProperties).
        qa.step('redraws_without_operators', qa.eval, _redraw(8))
        qa.step('chips_redrawn_without_operators', _wait_chips, qa, False)
        qa.step('more_redraws_without_operators', qa.eval, _redraw(8))
        missing = qa.step('chips_greyed_without_operator', _chips, qa, False)
        if not missing['tracking']:
            raise ScenarioFail(f'tracking changed while the operator was missing: {missing}')
        snaps.append(qa.step('snap_missing', _snap, qa, out, 'missing'))

        restore = qa.step('register_operators', qa.eval, REGISTER)
        if restore['errors'] or not all(restore['registered'].values()):
            raise ScenarioFail(f're-registration failed: {restore}')
        qa.step('redraws_with_operators', qa.eval, _redraw(2))
        qa.step('chip_has_operator_again', _wait_chips, qa, True)
        after = qa.step('chips_with_operators_again', _chips, qa, True)
        snaps.append(qa.step('snap_restored', _snap, qa, out, 'restored'))
        # The chip writes clear=True through the rebuilt properties: a click
        # must clear the tracking, not start the modal eyedropper.
        qa.step('click_chip', qa.click, op=TRACK)
        qa.step('tracking_cleared', qa.wait,
                f"{SHOT}.track_target is None and "
                f"{SHOT}.camera.constraints.get('Mixar Director Track') is None", timeout=8)
    finally:
        if restore is None or restore['errors']:
            # Never leave the session without its operators, whatever failed.
            try:
                restore = qa.eval(REGISTER)
            except Exception as exc:  # the app is gone (the unfixed build)
                restore = {'errors': [repr(exc)]}
            print(f'[scenario] cleanup re-registration: {restore}', flush=True)
        try:
            qa.eval(UNTRACK)
        except Exception as exc:
            print(f'[scenario] cleanup untrack failed: {exc!r}', flush=True)
    return {'setup': setup, 'before': before, 'missing': missing, 'after': after,
            'restore': restore, 'snaps': snaps}


if __name__ == '__main__':
    run_scenario('cinema_missing_operator_e2e', run)
