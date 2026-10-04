# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Restore the island normally and capture a settled native frame."""
import time


def capture_island(qa, path):
    qa.eval("from mixar.modules.onboarding.core.tour import session as tour\n"
            "if tour.current(): tour.current().stop('qa')\nresult = True")
    # Native Stop collapses the island. Hidden windows retain composer targets
    # and cached frames, so finding a target alone does not establish visibility.
    qa.press('M', shift=True)
    deadline = time.monotonic() + 10
    previous, stable_since = None, time.monotonic()
    while time.monotonic() < deadline:
        state = qa.eval("""
windows = [w for w in bpy.context.window_manager.windows
           if any(a.type == 'AGENT_BUBBLE' and any(r.type == 'WINDOW' and r.height > 1
                  for r in a.regions) for a in w.screen.areas)]
result = {'resizing': bpy.context.window_manager.mixar_window_resizing,
          'windows': [(w.as_pointer(), w.width, w.height) for w in windows]}
""")
        if state != previous or state['resizing'] or len(state['windows']) != 1:
            previous, stable_since = state, time.monotonic()
        elif time.monotonic() - stable_since >= .5:
            break
        time.sleep(.1)
    else:
        raise AssertionError(f'Island layout did not settle: {previous}')
    pointer = state['windows'][0][0]
    return qa.eval(f"""
assert not bpy.context.window_manager.mixar_window_resizing
w = next(w for w in bpy.context.window_manager.windows if w.as_pointer() == {pointer})
assert w.mixar_qa_capture_frame(filepath={str(path)!r})
result = {{'captured': True, 'path': {str(path)!r}}}
""")
