# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Two C++ contracts behind attaching an image to the floating Agent Bubble.

Both live in files that have no Python surface, so they are pinned at the
source level — the same technique ``test_agent_bubble_linux_controls.py`` uses
for the window-control stubs.

1. **The chat's drop poll must accept the bubble's spacetype.**
   ``SPACE_AGENT_BUBBLE`` reuses ``mixie_chat_main_region_init`` /
   ``mixie_chat_footer_region_init``, so the bubble's regions already carry the
   chat's dropbox handlers. ``mixie_chat_image_drop_poll`` gated on
   ``spacetype == SPACE_MIXIE_CHAT`` alone and therefore rejected every file
   dropped onto the bubble, with no error anywhere. Every other shared chat
   callback (selection, hit-testing, code copy, feedback, overlays) already
   accepts both spacetypes; this one is part of that contract.

2. **The bubble's force-size must not put backing pixels into ``sizex``.**
   ``wmWindow::sizex``/``sizey`` are LOGICAL POINTS — Blender derives the
   screen rect from them as ``sizex * GHOST_GetNativePixelSize()``, while
   ``ScrVert`` coordinates and ``Mixar_WindowGetContentPixelSize`` are BACKING
   PIXELS. Assigning the backing size straight into ``sizex`` made a 400pt
   (800px) bubble claim an 800pt window, so on Retina the area was laid out
   1600px wide inside an 800px one: the Send button and the header's
   history/rules controls were positioned off-window and the composer field ran
   past the right edge. Attaching an image is the usual trigger, because that
   is what re-runs the force-size.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAGDROP = ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_dragdrop.cc"
BUBBLE = ROOT / "src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc"


def _force_size_body() -> str:
    src = BUBBLE.read_text(encoding="utf-8")
    start = src.index("static void bubble_force_size_and_refresh(")
    end = src.index("\n}\n", start)
    return src[start:end]


class TestChatDropPollAcceptsTheBubble:
    def test_poll_names_both_spacetypes(self):
        src = DRAGDROP.read_text(encoding="utf-8")
        start = src.index("static bool mixie_chat_image_drop_poll(")
        body = src[start:src.index("\n}\n", start)]
        assert "SPACE_MIXIE_CHAT" in body
        assert "SPACE_AGENT_BUBBLE" in body, (
            "the bubble reuses the chat's region init and so carries these "
            "dropboxes; rejecting its spacetype silently drops every file"
        )

    def test_poll_does_not_reject_on_a_bare_spacetype_inequality(self):
        src = DRAGDROP.read_text(encoding="utf-8")
        assert "area->spacetype != SPACE_MIXIE_CHAT" not in src


class TestBubbleForceSizeUnits:
    def test_sizex_is_not_assigned_the_backing_pixel_size(self):
        body = _force_size_body()
        assert not re.search(r"w->sizex\s*=\s*pixel_width\s*;", body), (
            "sizex is logical points; pixel_width is backing pixels"
        )
        assert not re.search(r"w->sizey\s*=\s*pixel_height\s*;", body)

    def test_the_native_pixel_factor_is_taken_into_account(self):
        body = _force_size_body()
        assert "WM_window_native_pixel_x" in body, (
            "the points<->pixels factor has to come from GHOST, not be assumed 1"
        )

    def test_scrverts_stay_in_backing_pixels(self):
        body = _force_size_body()
        # ED_screen_refresh rescales the verts against sizex * fac, so they
        # must be written in the backing-pixel space, never in points.
        for vert in ("v2->vec.y", "v3->vec.x", "v3->vec.y", "v4->vec.x"):
            line = next(ln for ln in body.splitlines() if vert in ln)
            assert "backing_" in line, f"{vert} must be a backing-pixel value"
