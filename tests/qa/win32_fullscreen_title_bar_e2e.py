# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows: leaving full screen gives the main window its title bar back.

No backend, no credits. Windows only.

Window > Toggle Window Fullscreen strips ``WS_CAPTION`` in
``GHOST_WindowWin32::setState``. Upstream re-adds it on every state change;
the Mixar overlay stopped doing that (chromeless Agent Bubble / pill windows
must stay caption-free), so after toggling full screen off the main window had
no title bar: no move, minimize, maximize or close. The overlay now restores
the caption to exactly the windows full screen took it from.

Cases, each driven through ``wm.window_fullscreen_toggle`` on the main window:
- from_normal: normal -> full screen (no caption, covers the monitor) ->
  normal (caption back, not maximized);
- from_maximized: maximized -> full screen -> maximized (caption back,
  maximized again, as upstream's ``normal_state_`` intends);
- twice: two more round trips end with the caption still present;
- every Mixar window with ``WS_EX_TOOLWINDOW`` (island, pill) stays
  caption-free throughout;
- the same app process (pid) answers before and after.

State comes from the real Win32 styles (``GetWindowLongPtrW``); vision is a
desktop capture of the main window's top strip before and after, where the
title bar with its minimize / maximize / close buttons must be visible.

Replay: QA_HARNESS=../mixar-qa-harness MIXAR_QA_PORT=<port>
QA_SCENARIO_OUT=<dir> python tests/qa/win32_fullscreen_title_bar_e2e.py
"""
import json
import os
from pathlib import Path
import sys
import time

_HARNESS = os.environ.get('QA_HARNESS') or str(Path(__file__).resolve().parents[3] / 'mixar-qa-harness')
sys.path.insert(0, str(Path(_HARNESS) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

SCENARIO = 'win32_fullscreen_title_bar'

# Runs inside the app: the process's GHOST windows and their Win32 styles.
PROBE = r'''
import ctypes, os
from ctypes import wintypes
assert os.environ.get('MIXAR_QA') == '1'
user32 = ctypes.windll.user32
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION, WS_POPUP, WS_MAXIMIZE = 0x00C00000, 0x80000000, 0x01000000
WS_EX_TOOLWINDOW = 0x00000080
pid = os.getpid()
windows = []
@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def _each(hwnd, _):
    owner = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    if owner.value != pid or not user32.IsWindowVisible(hwnd):
        return True
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, cls, 64)
    if cls.value != 'GHOST_WindowClass':
        return True
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE) & 0xFFFFFFFF
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    windows.append({
        'hwnd': int(hwnd or 0),
        'caption': (style & WS_CAPTION) == WS_CAPTION,
        'popup': bool(style & WS_POPUP),
        'maximized': bool(user32.IsZoomed(hwnd)),
        'tool': bool(ex & WS_EX_TOOLWINDOW),
        'rect': [rect.left, rect.top, rect.right, rect.bottom],
    })
    return True
user32.EnumWindows(_each, 0)
mains = [w for w in windows if not w['tool']]
main = max(mains, key=lambda w: (w['rect'][2] - w['rect'][0]) * (w['rect'][3] - w['rect'][1]))
monitor = [0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)]
result = {'pid': pid, 'main': main, 'tools': [w for w in windows if w['tool']],
          'screen': monitor, 'build_hash': bpy.app.build_hash.decode()}
'''

TOGGLE = '''
with bpy.context.temp_override(window=drv.main_window()):
    bpy.ops.wm.window_fullscreen_toggle()
result = True
'''


def _show(cmd):
    """ShowWindow on the main window from inside the app (SW_* constant)."""
    return PROBE + f'\nctypes.windll.user32.ShowWindow(main["hwnd"], {cmd})\nresult = True\n'


SW_MAXIMIZE, SW_RESTORE = 3, 9


def _probe(qa):
    return qa.eval(PROBE)


def _wait_main(qa, predicate, what, timeout=10.0):
    deadline = time.monotonic() + timeout
    state = _probe(qa)
    while not predicate(state['main']):
        if time.monotonic() > deadline:
            raise ScenarioFail(f'{what}: main window stayed {state["main"]}')
        time.sleep(0.2)
        state = _probe(qa)
    return state


def _tools_caption_free(state):
    bad = [w for w in state['tools'] if w['caption']]
    if bad:
        raise ScenarioFail(f'chromeless window gained a caption: {bad}')


def _covers_screen(main, screen):
    left, top, right, bottom = main['rect']
    return left <= screen[0] and top <= screen[1] and right >= screen[2] and bottom >= screen[3]


def _capture_title_strip(out, name, main):
    """Desktop capture of the window's top strip, where the title bar lives.

    The app reports physical pixels, so this process must be per-monitor DPI
    aware or the grab box is scaled; and the capture waits out DWM's
    restore/maximize animation, which is still running when the style flips.
    """
    if not out:
        return None
    try:
        import ctypes
        from PIL import ImageGrab
    except ImportError:
        return None
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:
        pass  # already set for this process
    time.sleep(0.8)
    left, top, right, _bottom = main['rect']
    path = Path(out) / f'{name}.png'
    ImageGrab.grab(bbox=(max(left, 0), max(top, 0), right, max(top, 0) + 80),
                   all_screens=True).save(path)
    return str(path)


def _round_trip(qa, label, expect_maximized, out):
    qa.step(f'{label}_enter_fullscreen', qa.eval, TOGGLE)
    full = qa.step(f'{label}_is_fullscreen', _wait_main, qa,
                   lambda m: not m['caption'], f'{label} enter full screen')
    if not _covers_screen(full['main'], full['screen']):
        raise ScenarioFail(f'{label}: full screen does not cover the monitor: {full}')
    _tools_caption_free(full)
    qa.step(f'{label}_leave_fullscreen', qa.eval, TOGGLE)
    back = qa.step(f'{label}_caption_restored', _wait_main, qa,
                   lambda m: m['caption'] and m['maximized'] == expect_maximized,
                   f'{label} leave full screen')
    _tools_caption_free(back)
    shot = _capture_title_strip(out, f'{label}_after', back['main'])
    return {'fullscreen': full['main'], 'after': back['main'], 'title_strip': shot}


def scenario(qa):
    if os.name != 'nt':
        raise ScenarioFail('Windows-only scenario')
    out = os.environ.get('QA_SCENARIO_OUT')
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
    evidence = {}
    before = evidence['before'] = qa.step('probe_before', _probe, qa)
    if not before['main']['caption']:
        raise ScenarioFail(f'main window starts without a title bar: {before["main"]}')
    _tools_caption_free(before)
    evidence['before_strip'] = _capture_title_strip(out, 'before', before['main'])

    qa.step('restore_normal', qa.eval, _show(SW_RESTORE))
    _wait_main(qa, lambda m: not m['maximized'] and m['caption'], 'restore to normal')
    evidence['from_normal'] = _round_trip(qa, 'from_normal', False, out)

    qa.step('maximize', qa.eval, _show(SW_MAXIMIZE))
    _wait_main(qa, lambda m: m['maximized'] and m['caption'], 'maximize')
    evidence['from_maximized'] = _round_trip(qa, 'from_maximized', True, out)

    evidence['twice'] = [_round_trip(qa, f'twice_{i}', True, out) for i in (1, 2)]

    after = evidence['after'] = qa.step('probe_after', _probe, qa)
    if after['pid'] != before['pid']:
        raise ScenarioFail(f'app process changed: {before["pid"]} -> {after["pid"]}')
    if out:
        (Path(out) / f'{SCENARIO}.json').write_text(json.dumps(evidence, indent=2))
    return {'pid': before['pid'], 'build_hash': before['build_hash'],
            'title_strips': [evidence['before_strip'],
                             evidence['from_normal']['title_strip'],
                             evidence['from_maximized']['title_strip']]}


def run(qa):
    return scenario(qa)


if __name__ == '__main__':
    run_scenario(SCENARIO, run)
