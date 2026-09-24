# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — cross-window anchor geometry.

The Agent island is its own OS window (and, minimised, a second pill
window). Whole-window anchors and the pill's footprint in MAIN-window
pixels live here, split out of ``anchors.py`` for size. Imports from
``anchors`` are deferred to avoid the circular import.
"""

from typing import Optional


def _window_is_shown(window) -> bool:
    from .anchors import _areas  # noqa: F401 — used below
    """A minimised island keeps a hidden full-size window beside its pill;
    the one the user can see is the one whose WINDOW region is laid out
    (the pill is HEADER-only) — or, for a pill-only state, the pill."""
    try:
        for area in _areas(window):
            for region in area.regions:
                if region.type == "WINDOW" and region.width > 1 and region.height > 1:
                    return True
    except Exception:  # noqa: BLE001
        return False
    return False


def resolve_window_area_spec(spec: dict) -> Optional["AnchorRect"]:
    from .anchors import BUBBLE_AREA, _window_pixels, _windows_for_area, window_rect
    hosts = _windows_for_area(spec["window_area"])
    if not hosts:
        return None
    if spec["window_area"] == BUBBLE_AREA and len(hosts) > 1:
        shown = [w for w in hosts if _window_is_shown(w)]
        # Expanded island wins; otherwise the smallest window is the pill.
        hosts = shown or sorted(hosts, key=_window_pixels)
    return window_rect(hosts[0])


def _live_offset_and_size(window, host):
    """(dx, dy, w, h) of ``window`` relative to ``host``'s bottom-left, in
    HOST-WINDOW PIXELS, from the windowing system's LIVE geometry. None
    when the build lacks it or a window has no native window.

    The native calls report in their own unit (macOS points; Windows
    DPI-scaled logical units for ``mixar_content_rect_in``, pixels for the
    GHOST bounds), so each result is scaled by the host measured with the
    SAME call against ``window_rect(host)`` — never ``host.width``, which is
    points on macOS but pixels on Windows."""
    from .anchors import window_rect
    host_px = window_rect(host).width
    # Preferred: the child's content rect in the host's client coordinates,
    # measured natively (exact across window styles; GHOST client bounds
    # subtract a per-style title-bar height and do not share an origin).
    fn = getattr(window, "mixar_content_rect_in", None)
    if fn is not None:
        try:
            x, y, w, h = fn(host)
            host_w = host.mixar_content_rect_in(host)[2]
            if w > 0 and h > 0 and host_w > 0:
                s = host_px / float(host_w)
                return (x * s, y * s, w * s, h * s)
        except Exception:  # noqa: BLE001
            pass
    fn = getattr(window, "mixar_live_client_rect", None)
    hfn = getattr(host, "mixar_live_client_rect", None)
    if fn is None or hfn is None:
        return None
    try:
        wl, wt, wr, wb = fn()
        hl, ht, hr, hb = hfn()
    except Exception:  # noqa: BLE001
        return None
    if wr <= wl or wb <= wt or hr <= hl or hb <= ht:
        return None
    s = host_px / float(hr - hl)
    return ((wl - hl) * s, (hb - wb) * s, (wr - wl) * s, (wb - wt) * s)


def resolve_pill_on_host(spec: dict, snapshot) -> Optional["AnchorRect"]:
    """The resting pill's rect in MAIN-window pixels. The pill is its own OS
    window whose painter runs in a draw_overlay pass after every Python
    handler, so nothing can be drawn over it; overlays for it are drawn in
    the main window around its footprint instead. ``"top"`` returns a thin
    strip along its top edge (a cursor target that stays visible)."""
    from .anchors import (AnchorRect, _Snapshot, main_window, normalize_ptr,
                          window_by_ptr, window_rect)
    snap = snapshot if snapshot is not None else _Snapshot()
    pill_w = None
    for widget in snap.widgets:
        if isinstance(widget, dict) and widget.get("surface") == "pill_cat":
            pill_w = window_by_ptr(normalize_ptr(widget.get("w")))
            break
    host = main_window()
    if pill_w is None or host is None:
        return None
    host_rect = window_rect(host)
    live = _live_offset_and_size(pill_w, host)
    if live is not None:
        x0, y0, w, h = live            # host pixels, relative to its bottom-left
    else:
        # Stored positions (stale after an OS re-seat or a native glide).
        scale = host_rect.width / float(host.width) if host.width else 1.0
        x0 = (float(pill_w.x) - float(host.x)) * scale
        y0 = (float(pill_w.y) - float(host.y)) * scale
        w, h = float(pill_w.width) * scale, float(pill_w.height) * scale
    if spec.get("pill_on_host") == "top":
        return AnchorRect(host_rect.window_ptr, x0, y0 + h - 2.0, x0 + w, y0 + h + 2.0)
    return AnchorRect(host_rect.window_ptr, x0, y0, x0 + w, y0 + h)
