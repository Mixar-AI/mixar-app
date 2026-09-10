# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Agent pill's window must BE the capsule, not a box containing one.

``Mixar_WindowSetCornerRadius`` is one contract with two implementations.
macOS honours it as a Core Animation mask -- ``layer.cornerRadius`` plus
``masksToBounds`` over a non-opaque window -- so everything outside the radius
is genuinely transparent and the resting pill is all the user sees.

Windows has no equivalent for a GL-rendered window. ``GHOST_WindowWin32``
constructs ``GHOST_ContextWGL`` with ``alphaBackground=false``, so the client
area carries no alpha channel and DWM composites it as opaque whatever the
shader writes. The pill paints an opaque near-black bed over its whole region
(deliberately -- it is what stops the capsule blinking when the cached region
buffer is stale), and that bed showed as a hard black rectangle around the
capsule wherever the viewport behind it was not equally dark. A Windows 11
border line traced the same rectangle on top.

So the Win32 half owes two things the naive port did not have: no OS border,
and the radius applied as the window's actual SHAPE. Both are pinned here,
along with the two ways a window region silently goes wrong -- a resize that
leaves a stale region clipping live content, and an entry outliving its HWND.

Source-level, because none of it is reachable from Python.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIN32 = ROOT / "src" / "intern" / "ghost" / "intern" / "GHOST_SystemWin32.cc"
COCOA = ROOT / "src" / "intern" / "ghost" / "intern" / "GHOST_SystemCocoa.mm"
EDITOR = ROOT / "src" / "source" / "blender" / "editors" / "space_agent_bubble"
PILL_DRAW = EDITOR / "agent_ui_draw.cc"
SPACE = EDITOR / "space_agent_bubble.cc"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing overlay source: {path}"
    return path.read_text(encoding="utf-8")


def _fn_body(src: str, signature: str) -> str:
    """The text of one top-level function, from its signature to column-0 '}'."""
    start = src.index(signature)
    end = src.index("\n}\n", start)
    return src[start:end]


@pytest.fixture(scope="module")
def win32() -> str:
    return _read(WIN32)


class TestWin32WindowIsShaped:
    """The radius must reach the window, not just DWM's preference."""

    def test_corner_radius_applies_a_window_region(self, win32: str) -> None:
        body = _fn_body(win32, 'extern "C" void Mixar_WindowSetCornerRadius(')
        assert "s_corner_shapes" in body, (
            "Mixar_WindowSetCornerRadius must record the requested radius so the "
            "region can be rebuilt on later resizes."
        )
        assert "mixar_window_apply_corner_region" in body, (
            "The radius must be applied as the window's shape. Without it the "
            "pill's opaque bed fills the window RECTANGLE and reads as a black "
            "box around the capsule."
        )

    def test_region_is_a_round_rect_owned_by_the_window(self, win32: str) -> None:
        body = _fn_body(win32, "static void mixar_window_apply_corner_region(")
        assert "CreateRoundRectRgn" in body
        assert "SetWindowRgn" in body
        # SetWindowRgn takes ownership; deleting the region after handing it over
        # is a use-after-free that Windows reports as nothing at all.
        assert "DeleteObject" not in body, (
            "SetWindowRgn takes ownership of the HRGN -- it must not be deleted."
        )

    def test_dwm_rounding_is_declined_in_favour_of_our_own(self, win32: str) -> None:
        body = _fn_body(win32, 'extern "C" void Mixar_WindowSetCornerRadius(')
        assert "DWMWCP_DONOTROUND;" in body, (
            "DWM's corner preference only offers its own ~8px radius. On the "
            "pill (28.5px) that drew a near-square outline around a capsule, so "
            "the shape has to be ours alone."
        )

    def test_windows_11_border_is_removed(self, win32: str) -> None:
        helper = _fn_body(win32, "static void mixar_window_remove_dwm_border(")
        assert "0xFFFFFFFE" in helper, "DWMWA_COLOR_NONE"
        assert "34" in helper, "DWMWA_BORDER_COLOR"
        # Every window that loses its frame must also lose the OS border line.
        for signature in (
            'extern "C" void Mixar_WindowSetChromeless(',
            'extern "C" void Mixar_WindowSetBorderless(',
            'extern "C" void Mixar_WindowSetCornerRadius(',
        ):
            assert "mixar_window_remove_dwm_border" in _fn_body(win32, signature), signature


class TestWin32RegionStaysCorrect:
    """A window region is a snapshot of a size. Both ways it goes stale."""

    def test_region_is_rebuilt_on_every_resize(self, win32: str) -> None:
        body = _fn_body(win32, "static LRESULT CALLBACK mixar_min_size_subclass_proc(")
        assert "WM_WINDOWPOSCHANGED" in body and "mixar_window_apply_corner_region" in body, (
            "Mixar_WindowForceSize is called from paths that do not follow with "
            "another SetCornerRadius (the island's own sizing, the Scribble "
            "pad). Without a rebuild on resize, a stale region clips live "
            "content and there is no error anywhere."
        )

    def test_rebuild_is_a_no_op_when_the_size_is_unchanged(self, win32: str) -> None:
        body = _fn_body(win32, "static void mixar_window_apply_corner_region(")
        assert "applied_w" in body and "applied_h" in body, (
            "SetWindowRgn redraws, which can produce another WM_WINDOWPOSCHANGED "
            "-- the size guard is what stops that being a loop."
        )

    def test_shape_is_forgotten_with_its_window(self, win32: str) -> None:
        body = _fn_body(win32, "static LRESULT CALLBACK mixar_min_size_subclass_proc(")
        destroy = body[body.index("WM_NCDESTROY") :]
        assert "s_corner_shapes.erase(hwnd)" in destroy, (
            "HWNDs are reused; a stale entry would shape an unrelated window."
        )


class TestWin32PerPixelAlpha:
    """Where DWM will composite the client alpha, that IS the shape.

    A window region is binary coverage: the 28.5px capsule it rasterises has
    the hard staircase of any un-anti-aliased circle. Asking DWM to honour the
    alpha channel gives the capsule's own feathered edge instead -- but only
    where the pixel format GHOST actually got carries alpha bits, which nothing
    requested and which therefore has to be READ rather than assumed.
    """

    def test_alpha_is_probed_not_assumed(self, win32: str) -> None:
        probe = _fn_body(win32, 'extern "C" bool Mixar_WindowHasAlphaChannel(')
        assert "DescribePixelFormat" in probe and "cAlphaBits" in probe, (
            "GHOST_WindowWin32 constructs GHOST_ContextWGL with "
            "alphaBackground=false, so this must read the format that was "
            "chosen, not the one that was asked for."
        )
        enable = _fn_body(win32, 'extern "C" void Mixar_WindowSetPerPixelAlpha(')
        assert "Mixar_WindowHasAlphaChannel" in enable, (
            "Enabling without the channel leaves the corners composited opaque "
            "-- the black box, back again, with no region to fall back on."
        )

    def test_region_stands_down_for_alpha_windows(self, win32: str) -> None:
        body = _fn_body(win32, "static void mixar_window_apply_corner_region(")
        head = body[: body.index("s_corner_shapes.find")]
        assert "s_per_pixel_alpha_windows" in head and "SetWindowRgn(hwnd, NULL" in head, (
            "The region must be cleared BEFORE any shape is applied: region "
            "coverage would clip away exactly the anti-aliased edge that "
            "per-pixel alpha exists to produce."
        )

    def test_the_two_are_mutually_exclusive_by_construction(self, win32: str) -> None:
        enable = _fn_body(win32, 'extern "C" void Mixar_WindowSetPerPixelAlpha(')
        assert "mixar_window_apply_corner_region" in enable, (
            "Toggling alpha has to re-run the shape decision, or a region set "
            "earlier in the window's life keeps clipping."
        )


class TestCrossPlatformContract:
    """The same call means the same thing on both platforms."""

    def test_macos_still_masks_to_the_radius(self) -> None:
        body = _fn_body(_read(COCOA), 'extern "C" void Mixar_WindowSetCornerRadius(')
        assert "masksToBounds" in body and "cornerRadius" in body
        assert "clearColor" in body, (
            "The mask only reads as a shape because the window is non-opaque."
        )

    def test_the_pill_still_paints_every_pixel_of_its_bed(self) -> None:
        """Neither fix was allowed to be "stop painting the bed".

        The bed exists because the pill's cached region buffer is freed on
        perceived resizes and only repainted on the next tagged redraw; in that
        gap a composite blitted nothing and the pill flashed the bare backdrop.
        Shaping the window hides the bed and per-pixel alpha makes it invisible
        -- neither stops it covering the region, and BLEND_NONE is what writes
        the alpha straight through rather than blending over stale content.
        """
        for src, fn in (
            (_read(PILL_DRAW), "void agent_ui_draw_status_pill("),
            (_read(SPACE), "void agent_bubble_header_region_draw("),
        ):
            body = _fn_body(src, fn)
            assert "agent_bubble_pill_bed_is_transparent()" in body, fn
            assert "GPU_BLEND_NONE" in body, fn
            assert "0.02f" in body, fn

    def test_alpha_is_only_reached_for_on_windows(self) -> None:
        """macOS already has an anti-aliased mask; this is a Win32 workaround."""
        body = _fn_body(_read(SPACE), "static void agent_bubble_pill_try_per_pixel_alpha(")
        assert "#ifdef _WIN32" in body
