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

The island asks the same question one level up: its window can be given a
translucent background, and only then do the beds it paints per region have
anything to reveal. That contract is pinned here too, beside the pill's,
because it is the same question put to a different window.

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


class TestIslandWindowTranslucency:
    """The island window asks for the platform's translucent background.

    Where the pill is shaped by DWM honouring its client alpha, the island is
    one window painting several regions, so its route out is the kit's
    ``mixar_glass_window_apply_translucency`` -- a WINDOW background request,
    not a blur, and a defined no-op returning false off macOS/Windows. The
    return value is the whole point of calling it rather than an ``#ifdef``:
    it says whether the platform acted.

    The beds then decide what to do with that. They keep covering every pixel
    of every region -- the stale-buffer guarantee the pill's bed exists for is
    the same one -- and only their ALPHA moves: zero where the platform gave
    the window something to show through, one where it did not. So the card
    reads as glass over the desktop on macOS and Windows, the design surfaces
    that live inside it stay the near-black they are meant to be, and on Linux
    nothing changes at all.
    """

    def test_the_request_goes_through_the_kit(self) -> None:
        body = _fn_body(_read(SPACE), "static void agent_bubble_try_glass_translucency(")
        assert "ui::mixar_glass_window_apply_translucency(ghostwin, true)" in body, (
            "The island asks via the kit. Reaching for Mixar_WindowSetBlurBehind "
            "directly would drag the platform guard into this file and lose the "
            "Linux no-op the kit exists to provide."
        )
        assert "#if" not in body, (
            "The header promises callers need no #ifdef of their own precisely "
            "so this call is unconditional on every platform."
        )
        assert "g_bubble_glass_translucency =" in body, (
            "The answer has to be recorded: the beds paint every frame and must "
            "not each re-enter GHOST to ask again."
        )

    def test_the_flag_defaults_to_opaque_beds(self) -> None:
        assert "static bool g_bubble_glass_translucency = false;" in _read(SPACE), (
            "False is the honest default: nothing has asked yet, and on a "
            "platform with no compositor for this window's alpha nothing ever "
            "will -- so the beds stay opaque and the window region keeps "
            "shaping the island."
        )

    def test_the_beds_read_the_flag_and_nothing_else(self) -> None:
        src = _read(SPACE)
        # One definition, one use -- the region backdrop.
        assert src.count("agent_bubble_island_bed_is_transparent") == 2, (
            "Only the region backdrop may key off the window's translucency. "
            "The panel fill, the transcript's bg override and the footer are "
            "design surfaces -- the near-black the card is drawn around -- and "
            "letting them follow would empty the island out instead of "
            "revealing the desktop behind it."
        )

    def test_the_bed_still_paints_every_pixel_of_its_region(self) -> None:
        """The bed was never allowed to become "don't paint it".

        Alpha 0 hides it; skipping the fill would not. The region buffer is
        freed on perceived resizes and only repainted on the next tagged
        redraw, and painting the whole rect every frame is what stops a
        composite in that gap showing the bare backdrop.
        """
        body = _fn_body(_read(SPACE), "static void agent_bubble_fill_region_backdrop(")
        assert "float(BLI_rcti_size_x(&region->winrct) + 1)" in body
        assert "float(BLI_rcti_size_y(&region->winrct) + 1)" in body
        assert "ui::draw_roundbox_4fv(&r, true, 0.0f, backdrop);" in body
        assert "return" not in body, (
            "There is no skip path: whatever the alpha works out to, the bed "
            "still reaches its fill."
        )
        assert "GPU_BLEND_NONE" in body, (
            "BLEND_NONE is what writes the alpha straight through rather than "
            "blending over stale content."
        )

    def test_the_bed_alpha_follows_the_window(self) -> None:
        body = _fn_body(_read(SPACE), "static void agent_bubble_fill_region_backdrop(")
        assert "agent_bubble_island_bed_is_transparent() ? 0.0f : 1.0f" in body, (
            "The bed is opaque unless the platform actually acted -- a "
            "hard-coded alpha either discards the translucency or stops the "
            "island compositing as opaque where it must."
        )
        assert "const float backdrop[4] = {0.0f, 0.0f, 0.0f, bed_a};" in body

    def test_both_island_styling_sites_ask_for_it(self) -> None:
        """Repair and open are separate paths; neither may be the only one.

        The repair path re-styles any window the dedup reuses, the open path a
        fresh one. Asking in only one of them leaves the other window opaque.
        """
        src = _read(SPACE)
        call = "agent_bubble_try_glass_translucency(win->runtime->ghostwin);"
        parts = src.split(call)
        assert len(parts) == 3, (
            f"both island styling sites must call it, found {len(parts) - 1}"
        )
        radius = "Mixar_WindowSetCornerRadius(win->runtime->ghostwin, AGENT_BUBBLE_CORNER_RADIUS);"
        for before in parts[:2]:
            assert radius in before[-500:], (
                "The request must follow the corner radius: on macOS rounding "
                "the window is what makes it non-opaque."
            )
