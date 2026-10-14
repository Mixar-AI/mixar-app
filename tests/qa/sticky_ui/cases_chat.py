# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Chat-island cases: checkpoint on Send (3.1), no viewport redraws during a
turn (3.3, 3.5), mode-switch and outside-click behaviour (3.10).

Numbers refer to docs/development/sticky-ui-performance.md (private). A fake
busy state stands in for an agent turn: no credits are spent.
"""

from __future__ import annotations

import time

from common import PLATFORM, call_from_timer
from window_stack import StackRecorder, describe

FAKE_TURN = '''
import bpy
from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.core.session import get_session_manager
s = bpy.context.window.scene
sm = get_session_manager()
if {busy!r}:
    # Through the session manager with a run open: a bare BUSY flag with no
    # open run is reset to IDLE within a second by the stale-state recovery.
    s.mixie_chat_mode = 'AGENT'
    sm.set_run(s, 'qa-sticky-ui-fake-run', True)
    sm.set_state(s, SessionState.BUSY)
else:
    sm.set_state(s, SessionState.IDLE)
    sm.set_run(s, '', False)
result = (s.mixie_chat_state, s.mixie_chat_active_turn_mode)
'''


def _wait_connected(qa):
    """Login is followed by the agent WebSocket handshake, which moves every
    scene through CONNECTING to IDLE; a fake turn set before it is overwritten."""
    qa.wait("__import__('mixar.modules.space_mixie_chat.core.connection_manager', fromlist=['x'])"
            ".get_connection_manager().is_connected and bpy.context.window.scene.mixie_chat_state == 'IDLE'",
            timeout=60)
    time.sleep(1.0)


def _start_fake_turn(qa):
    _wait_connected(qa)
    state = qa.eval(FAKE_TURN.format(busy=True))
    assert tuple(state) == ("BUSY", "AGENT"), f"fake turn did not start: {state}"
    time.sleep(1.0)
    held = qa.eval("result = bpy.context.window.scene.mixie_chat_state")
    assert held == "BUSY", f"fake turn did not hold (state {held!r})"


def _open_island(qa):
    qa.open_chat()
    qa.wait("drv.island_state()['mode'] == 'island'", timeout=15)
    time.sleep(1.0)  # let the open animation settle


def checkpoint_send_keeps_island(c):
    """3.1: a turn checkpoint is fast and does not close the chat windows."""
    qa = c.qa
    _open_island(qa)
    result = qa.eval(f'''
import bpy, time
from mixar.modules.space_mixie_chat.core import checkpoint_store as store, turn_checkpoints as cp
root = {str(c.out / "checkpoints")!r}
store.checkpoints_root = lambda: root
cp.checkpoints_root = store.checkpoints_root
for area in bpy.context.window.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.shading.type = 'MATERIAL'   # the shading that made the thumbnail an EEVEE render
wm = bpy.context.window_manager
before = sorted(w.as_pointer() for w in wm.windows)
t = time.perf_counter()
rec = cp.capture(bpy.context.window.scene, 'qa sticky-ui checkpoint')
seconds = time.perf_counter() - t
result = {{'seconds': round(seconds, 3), 'record': bool(rec),
          'windows_kept': sorted(w.as_pointer() for w in wm.windows) == before}}
''')
    time.sleep(1.0)
    mode = qa.island_state()["mode"]
    c.numbers.update(capture_s=result["seconds"], island_after=mode)
    assert result["record"], "no checkpoint was written"
    assert result["windows_kept"], "a chat window was closed or recreated by the checkpoint save"
    assert mode == "island", f"chat is {mode!r} after the checkpoint, expected 'island'"
    assert result["seconds"] < 3.0, f"checkpoint took {result['seconds']} s (fixed build: ~0.3 s)"


def turn_no_viewport_redraws(c):
    """3.3 + 3.5: during a turn the viewport is not re-rendered for the chat
    tick or the halo; the native halo is active."""
    qa = c.qa
    qa.eval('''
import bpy
drv._v3d_draws = 0
def _qa_count_draw():
    drv._v3d_draws += 1
drv._v3d_handle = bpy.types.SpaceView3D.draw_handler_add(_qa_count_draw, (), 'WINDOW', 'POST_PIXEL')
result = True
''')
    _start_fake_turn(qa)
    time.sleep(0.5)
    qa.eval("drv._v3d_draws = 0; result = True")
    time.sleep(3.0)
    state = qa.eval('''
import bpy
wm = bpy.context.window_manager
result = {'draws': drv._v3d_draws, 'halo_active': bool(wm.get('mixar_agent_halo_active', 0)),
          'native_halo': hasattr(bpy.ops.mixar, 'agent_halo_redraw')}
bpy.types.SpaceView3D.draw_handler_remove(drv._v3d_handle, 'WINDOW')
''')
    qa.eval(FAKE_TURN.format(busy=False))
    c.numbers.update(viewport_draws_in_3s=state["draws"], halo_active=state["halo_active"])
    assert state["native_halo"], "native halo operator missing (falls back to full redraws)"
    assert state["halo_active"], "halo not active during the fake turn"
    assert state["draws"] <= 6, f"{state['draws']} viewport redraws in 3 s of a turn (before the fix: ~90)"


def _require_frames(rec, frames, step):
    """A supported reader that saw nothing is an environment problem, never a pass."""
    if rec.supported and not frames:
        raise AssertionError(f"{step}: the window-stack reader saw no on-screen windows of the app "
                             "(screen locked, display asleep, or the app on another desktop?). "
                             "Rerun with the app visible.")


def _require_host(host, ids, t):
    """The main window leaving the screen means the whole app did (a desktop
    switch, a locked screen): an environment event, not the island's doing."""
    if host not in ids:
        raise AssertionError(f"the app's main window left the screen at {t:.2f} s (desktop switch or "
                             "screen lock during the run?). Rerun without touching the machine.")


def _stack_ids(frame):
    """Host = largest window; island = next largest; pill = the rest."""
    wins = sorted(frame, key=lambda w: w.w * w.h, reverse=True)
    return wins[0].id, (wins[1].id if len(wins) > 1 else None)


def mode_switch_keeps_island(c):
    """3.10: an Engine click mid-turn keeps the chat open and on top; a viewport
    click still collapses it, without the main window covering it first."""
    qa = c.qa
    _open_island(qa)
    _start_fake_turn(qa)
    rec = StackRecorder(c.app.pid, c.out)
    rec.start(3.5)
    time.sleep(0.3)
    qa.click(text="Engine", area_type="TOPBAR")
    modes = []
    t0 = time.time()
    while time.time() - t0 < 2.0:
        modes.append(qa.island_state()["mode"])
        time.sleep(0.15)
    workspace = qa.eval("result = bpy.context.window_manager.windows[0].workspace.name")
    frames = rec.frames()
    (c.out / "A_engine_click_windows.txt").write_text(describe(frames) or rec.reason)
    c.numbers.update(engine_click_modes=sorted(set(modes)), workspace=workspace)
    assert workspace != "Zen Mode", "the Engine click did not switch modes"
    assert set(modes) == {"island"}, f"chat left the island state after the Engine click: {modes}"
    _require_frames(rec, frames, "Engine click")
    if rec.supported:
        host, island = _stack_ids(frames[0][1])
        for t, wins in frames:
            ids = [w.id for w in wins]
            _require_host(host, ids, t)
            assert island in ids, f"island window gone at {t:.2f} s"
            assert ids.index(island) < ids.index(host), f"main window above the island at {t:.2f} s"
            assert next(w for w in wins if w.id == island).alpha >= 0.9, f"island faded at {t:.2f} s"
    else:
        c.numbers["window_stack"] = f"not checked: {rec.reason}"

    # Part B: an ordinary outside click still collapses the chat, visibly.
    rec = StackRecorder(c.app.pid, c.out)
    rec.start(3.0)
    time.sleep(0.3)
    xy = qa.eval("w=drv.main_window(); a=next(a for a in w.screen.areas if a.type=='VIEW_3D'); "
                 "r=next(r for r in a.regions if r.type=='WINDOW'); result=(r.x+120, r.y+r.height-160)")
    qa.cmd("click_xy", x=xy[0], y=xy[1])
    qa.wait("drv.island_state()['mode'] == 'pill'", timeout=5)
    frames = rec.frames()
    (c.out / "B_viewport_click_windows.txt").write_text(describe(frames) or rec.reason)
    qa.eval(FAKE_TURN.format(busy=False))
    _require_frames(rec, frames, "viewport click")
    if not rec.supported:
        return
    host, island = _stack_ids(frames[0][1])
    for t, wins in frames:
        _require_host(host, [w.id for w in wins], t)
    last = frames[-1][1]
    assert island not in [w.id for w in last if w.alpha > 0.05], "island still visible after the collapse"
    assert any(w.id != host and w.alpha >= 0.9 for w in last), "pill not visible after the collapse"
    if PLATFORM == "macos":
        # The fade must play in front of the main window (it used to play behind it).
        fading = [(t, wins) for t, wins in frames
                  if any(w.id == island and 0.05 < w.alpha < 0.95 for w in wins)]
        assert fading, "no island fade observed"
        for t, wins in fading:
            ids = [w.id for w in wins]
            assert ids.index(island) < ids.index(host), f"main window covered the fading island at {t:.2f} s"
        c.numbers["fade_frames_in_front"] = len(fading)
