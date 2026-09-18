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
    points, from the windowing system's LIVE client bounds
    (``Window.mixar_live_client_rect``, Mixar RNA; top-left origin). None
    when the build lacks it or a window has no native window."""
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
    return (float(wl - hl), float(hb - wb), float(wr - wl), float(wb - wt))


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
    scale = host_rect.width / float(host.width) if host.width else 1.0
    live = _live_offset_and_size(pill_w, host)
    if live is not None:
        dx, dy, pw, ph = live          # points, relative to the host's bottom-left
    else:
        # Stored positions (stale after an OS re-seat or a native glide).
        dx = float(pill_w.x) - float(host.x)
        dy = float(pill_w.y) - float(host.y)
        pw, ph = float(pill_w.width), float(pill_w.height)
    x0, y0 = dx * scale, dy * scale
    w, h = pw * scale, ph * scale
    if spec.get("pill_on_host") == "top":
        return AnchorRect(host_rect.window_ptr, x0, y0 + h - 2.0, x0 + w, y0 + h + 2.0)
    return AnchorRect(host_rect.window_ptr, x0, y0, x0 + w, y0 + h)
