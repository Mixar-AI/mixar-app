# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — anchor resolution.

Turns a semantic anchor spec (see the ``A_*`` constants in ``beats.py``)
into a rectangle in WINDOW pixel coordinates (bottom-left origin) of one
specific window, using the app's own geometry:

* ``wm.mixar_qa_ui_dump`` — the QA widget dump (``interface_qa_inspect.cc``,
  exposed by ``rna_wm_mixar.cc``). Every widget carries ``w`` / ``a`` / ``r``
  (window / area / region pointers), ``at`` / ``rt`` (space / region type
  ints), ``type``, ``text``, optional ``tip`` / ``op`` / ``prop`` /
  ``prop_owner`` / ``panel`` / ``block`` / ``popup`` / ``surface`` /
  ``value``, ``rect`` ``[xmin, ymin, xmax, ymax]``, ``enabled`` and ``sel``.
* RNA — ``window.screen.areas[*].regions[*]`` with ``x``/``y``/``width``/
  ``height`` in window pixels.

Spec grammar (``resolve``):

* ``{"area": T, "region": R}`` with no dump keys → that region's rect
  (main window preferred; the bubble window for ``AGENT_BUBBLE``).
* ``{"window_area": T}`` → the whole window that hosts an area of type T.
* any of ``op`` / ``prop`` / ``tip`` / ``text`` / ``surface`` / ``panel`` /
  ``value`` / ``type`` → a widget whose fields all equal the spec's;
  ``area`` narrows to widgets living in an area of that type; popups are
  skipped unless ``"popup": True``; the largest match wins.

COST: the dump serializes the ENTIRE UI of every window, so ``resolve``
must be called at most a few times per second. Callers on the modal tick
go through ``AnchorCache`` (one dump per TTL, shared by every spec) —
never call ``resolve`` per overlay per frame.

Main thread only. Nothing here raises: a spec that is not on screen
resolves to ``None``.
"""

import json
import time
from dataclasses import dataclass
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger

_logger = get_logger(__name__)

BUBBLE_AREA = "AGENT_BUBBLE"
DEFAULT_REGION = "WINDOW"

# Dump fields a spec may pin. Names match interface_qa_inspect.cc exactly.
DUMP_MATCH_KEYS = ("op", "prop", "tip", "text", "surface", "panel", "value", "type")


@dataclass(frozen=True)
class AnchorRect:
    window_ptr: int
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    @property
    def center(self) -> tuple:
        return ((self.xmin + self.xmax) * 0.5, (self.ymin + self.ymax) * 0.5)

    def contains(self, x, y) -> bool:
        return self.xmin <= x <= self.xmax and self.ymin <= y <= self.ymax

    def padded(self, px) -> "AnchorRect":
        return AnchorRect(self.window_ptr, self.xmin - px, self.ymin - px,
                          self.xmax + px, self.ymax + px)


def normalize_ptr(value) -> Optional[int]:
    """Pointers arrive as JSON ints, decimal strings or ``0x`` strings."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            base = 16 if text.lower().startswith("0x") else 10
            ptr = int(text, base)
        except ValueError:
            return None
        return ptr if ptr >= 0 else None
    return None


# ---------------------------------------------------------------------------
# App access. Small, so tests monkeypatch them instead of ``bpy``.
# ---------------------------------------------------------------------------

def _window_manager():
    try:
        return bpy.context.window_manager
    except Exception:  # noqa: BLE001 — context may be unavailable
        return None


def _windows() -> list:
    wm = _window_manager()
    if wm is None:
        return []
    try:
        return list(wm.windows)
    except Exception:  # noqa: BLE001
        return []


def _read_dump() -> str:
    """One serialization of the whole UI — expensive, see the module doc."""
    wm = _window_manager()
    if wm is None:
        return ""
    try:
        return str(getattr(wm, "mixar_qa_ui_dump", "") or "")
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour anchors: dump read failed: %s", exc)
        return ""


def _area_types_by_ptr() -> dict:
    """``area.as_pointer() → area.type`` over every window, built once per
    resolve so the dump's ``a`` field can be filtered by area type."""
    out = {}
    for window in _windows():
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        try:
            for area in screen.areas:
                out[area.as_pointer()] = area.type
            # The top bar and status bar are window-level global areas.
            for area in getattr(window, "global_areas", ()) or ():
                out[area.as_pointer()] = area.type
        except Exception:  # noqa: BLE001
            continue
    return out


def _parse_widgets(text: str) -> list:
    if not text:
        return []
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        _logger.warning("tour anchors: dump is not JSON: %s", exc)
        return []
    widgets = data.get("widgets") if isinstance(data, dict) else None
    return widgets if isinstance(widgets, list) else []


# ---------------------------------------------------------------------------
# Windows and regions (RNA).
# ---------------------------------------------------------------------------

def _window_ptr(window) -> Optional[int]:
    try:
        return normalize_ptr(window.as_pointer())
    except Exception:  # noqa: BLE001
        return None


def _areas(window) -> list:
    screen = getattr(window, "screen", None)
    if screen is None:
        return []
    try:
        return list(screen.areas)
    except Exception:  # noqa: BLE001
        return []


def _has_area(window, area_type: str) -> bool:
    return any(getattr(a, "type", None) == area_type for a in _areas(window))


def _window_pixels(window) -> int:
    try:
        return int(window.width) * int(window.height)
    except Exception:  # noqa: BLE001
        return 0


def window_by_ptr(ptr):
    want = normalize_ptr(ptr)
    if want is None:
        return None
    for window in _windows():
        if _window_ptr(window) == want:
            return window
    return None


def main_window():
    """The largest window whose screen has no ``AGENT_BUBBLE`` area."""
    best, best_px = None, -1
    for window in _windows():
        if _has_area(window, BUBBLE_AREA):
            continue
        px = _window_pixels(window)
        if px > best_px:
            best, best_px = window, px
    return best


def _find_region(area, region_type: str):
    try:
        for region in area.regions:
            if region.type == region_type:
                return region
    except Exception:  # noqa: BLE001
        pass
    return None


def host_region():
    """(window, area, region): the main window's VIEW_3D WINDOW region, else
    the largest WINDOW region of any non-bubble area."""
    main = main_window()
    if main is not None:
        for area in _areas(main):
            if area.type == "VIEW_3D":
                region = _find_region(area, DEFAULT_REGION)
                if region is not None:
                    return main, area, region
    best, best_px = (None, None, None), -1
    for window in _windows():
        for area in _areas(window):
            if area.type == BUBBLE_AREA:
                continue
            region = _find_region(area, DEFAULT_REGION)
            if region is None:
                continue
            px = int(region.width) * int(region.height)
            if px > best_px:
                best, best_px = (window, area, region), px
    return best


def region_rect(window, region) -> AnchorRect:
    ptr = _window_ptr(window) or 0
    x, y = float(region.x), float(region.y)
    return AnchorRect(ptr, x, y, x + float(region.width), y + float(region.height))


def window_rect(window) -> AnchorRect:
    """Union of every region rect of every area — INCLUDING the global
    areas (topbar, statusbar; Mixar's ``Window.global_areas`` RNA), which
    ``screen.areas`` omits — or the window size if none."""
    ptr = _window_ptr(window) or 0
    rects = []
    areas = list(_areas(window))
    try:
        areas.extend(getattr(window, "global_areas", None) or [])
    except Exception:  # noqa: BLE001
        pass
    for area in areas:
        try:
            rects.extend(region_rect(window, r) for r in area.regions)
        except Exception:  # noqa: BLE001
            continue
    if not rects:
        try:
            return AnchorRect(ptr, 0.0, 0.0, float(window.width), float(window.height))
        except Exception:  # noqa: BLE001
            return AnchorRect(ptr, 0.0, 0.0, 0.0, 0.0)
    return AnchorRect(ptr, min(r.xmin for r in rects), min(r.ymin for r in rects),
                      max(r.xmax for r in rects), max(r.ymax for r in rects))


def _windows_for_area(area_type: str) -> list:
    """Windows hosting ``area_type``: the bubble's own window first for
    ``AGENT_BUBBLE``, the main window first for everything else."""
    main = main_window()
    hosts = [w for w in _windows() if _has_area(w, area_type)]
    if area_type == BUBBLE_AREA:
        return [w for w in hosts if w is not main] + [w for w in hosts if w is main]
    return [w for w in hosts if w is main] + [w for w in hosts if w is not main]


def _resolve_region_spec(spec: dict) -> Optional[AnchorRect]:
    area_type = spec["area"]
    region_type = spec.get("region", DEFAULT_REGION)
    for window in _windows_for_area(area_type):
        for area in _areas(window):
            if area.type != area_type:
                continue
            region = _find_region(area, region_type)
            if region is not None:
                return region_rect(window, region)
    return None


# ---------------------------------------------------------------------------
# Widgets (QA dump).
# ---------------------------------------------------------------------------

def _widget_rect(widget: dict) -> Optional[AnchorRect]:
    rect = widget.get("rect")
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        return None
    try:
        xmin, ymin, xmax, ymax = (float(v) for v in rect)
    except (TypeError, ValueError):
        return None
    if xmax <= xmin or ymax <= ymin:
        return None
    ptr = normalize_ptr(widget.get("w"))
    if ptr is None:
        return None
    return AnchorRect(ptr, xmin, ymin, xmax, ymax)


def op_idname_forms(idname: str) -> set:
    """Both spellings of an operator id: Python ``wm.context_set_enum`` and
    the C ``WM_OT_context_set_enum`` the widget dump reports."""
    forms = {idname}
    if "." in idname and "_OT_" not in idname:
        ns, name = idname.split(".", 1)
        forms.add(f"{ns.upper()}_OT_{name}")
    elif "_OT_" in idname:
        ns, name = idname.split("_OT_", 1)
        forms.add(f"{ns.lower()}.{name}")
    return forms


def _widget_matches(widget: dict, spec: dict, area_types: dict) -> bool:
    if widget.get("popup") and not spec.get("popup"):
        return False
    for key in DUMP_MATCH_KEYS:
        if key not in spec:
            continue
        if key == "op":
            if widget.get("op") not in op_idname_forms(str(spec["op"])):
                return False
            continue
        if widget.get(key) != spec[key]:
            return False
    if "area" in spec:
        area_ptr = normalize_ptr(widget.get("a"))
        if area_ptr is None or area_types.get(area_ptr) != spec["area"]:
            return False
    return True


def _resolve_widget_spec(spec: dict, widgets: list, area_types: dict) -> Optional[AnchorRect]:
    best, best_px = None, 0.0
    for widget in widgets:
        if not isinstance(widget, dict) or not _widget_matches(widget, spec, area_types):
            continue
        rect = _widget_rect(widget)
        if rect is None:
            continue
        px = rect.width * rect.height
        if px > best_px:
            best, best_px = rect, px
    return best


def is_widget_spec(spec: dict) -> bool:
    return any(key in spec for key in DUMP_MATCH_KEYS)


class _Snapshot:
    """One parsed dump + area map, shared by every spec resolved against it."""

    def __init__(self):
        self.widgets = _parse_widgets(_read_dump())
        self.area_types = _area_types_by_ptr()


def resolve(spec: dict, snapshot: Optional[_Snapshot] = None) -> Optional[AnchorRect]:
    """Uncached resolution; ``None`` when the anchor is not on screen.
    A widget spec reads a fresh dump unless ``snapshot`` is supplied."""
    try:
        if not isinstance(spec, dict) or not spec:
            return None
        if is_widget_spec(spec):
            snap = snapshot if snapshot is not None else _Snapshot()
            return _resolve_widget_spec(spec, snap.widgets, snap.area_types)
        if "pill_on_host" in spec:
            from . import anchors_windows
            return anchors_windows.resolve_pill_on_host(spec, snapshot)
        if "window_area" in spec:
            from . import anchors_windows
            return anchors_windows.resolve_window_area_spec(spec)
        if "area" in spec:
            return _resolve_region_spec(spec)
        _logger.warning("tour anchors: unrecognised spec %r", spec)
    except Exception as exc:  # noqa: BLE001 — never raise into the modal
        _logger.debug("tour anchors: resolve(%r) failed: %s", spec, exc)
    return None


class AnchorCache:
    """Throttles ``resolve``: one dump per ``ttl_s``, every spec (including
    ones that resolved to ``None``) re-resolved only once the TTL lapses."""

    def __init__(self, ttl_s: float = 0.5, now=time.monotonic):
        self.ttl_s = float(ttl_s)
        self._now = now
        self._snapshot: Optional[_Snapshot] = None
        self._snapshot_at: float = float("-inf")
        self._results: dict = {}

    @staticmethod
    def _key(spec: dict) -> str:
        return json.dumps(spec, sort_keys=True, default=str)

    def _fresh(self) -> bool:
        return (self._now() - self._snapshot_at) < self.ttl_s

    def get(self, spec: dict) -> Optional[AnchorRect]:
        try:
            key = self._key(spec)
        except Exception:  # noqa: BLE001
            return resolve(spec)
        if not self._fresh():
            self.invalidate()
        if key in self._results:
            return self._results[key]
        if is_widget_spec(spec) and self._snapshot is None:
            self._snapshot = _Snapshot()
        if self._snapshot_at == float("-inf"):
            self._snapshot_at = self._now()
        rect = resolve(spec, self._snapshot)
        self._results[key] = rect
        return rect

    def invalidate(self) -> None:
        self._snapshot = None
        self._snapshot_at = float("-inf")
        self._results = {}
