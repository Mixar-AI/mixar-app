# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — named app actions and gate predicates.

``run(name, args)`` performs one beat action against the real app through
existing operators and helpers (no event simulation); ``check(predicate,
flags)`` answers a gate's "did the user do it?" question. Both run on the
main thread from the modal operator's timer, never from a draw callback,
and never raise: a failure is logged and reported as ``False``.

Island semantics: ``island_open`` leaves the island as the MINIMISED
resting pill (that is what the tour asks the user to click), and
``island_expand`` restores it. ``island_expanded`` is True only once the
pill is gone: the bubble's own window survives hidden while minimised, so
the pill's ``pill_cat`` QA target is the one signal a hidden window cannot
fake; the Agent-tab anchor or a tall bubble window then confirms it.
Where the resting pill does not exist (``pill_supported()`` is False:
anything but macOS/Windows) ``island_open`` opens the island expanded and
``island_expanded`` is True as soon as that window is laid out.

Exit paths (the session, ``session.py``, calls these):

* ``snapshot_state()`` before the first beat and ``restore_state(snap)``
  on a CANCELLED or error exit — the user never saw the tour through, so
  the UI mode, drawer, island state and island tab go back to what they
  were.
* ``tour_cleanup`` (the outro beat's action, also run on a completed or
  user-exited tour): Zen Mode and the Agent tab only. The moodboard
  drawer is deliberately LEFT OPEN — the tour ends showing the demo
  concept the user just boarded.
* ``reset_session_state()`` at session start clears the per-session
  island bookkeeping and the anchor cache so a restarted tour (Help →
  Start tour) never inherits a stale "pill seen" flag.
"""

import os
import sys
import time

import bpy

from mixar.config.config import UI_MODE_AI, UI_MODE_PRO, get_ui_mode
from mixar.config.logging_config import get_logger

from . import anchors, config
from .beats import A_TAB_AGENT

_logger = get_logger(__name__)

# Read by workflow/ui/operators/ui_mode_ops.py: while True, a mode switch
# does not schedule the tour again on top of the tour's own mode switches
# (including the pre-tour mode it restores after an interruption).
suppress_legacy_restart = False

TAB_IDS = ("AGENT", "THREE_D", "IMAGE", "VIDEO", "SPLAT", "GENERATIONS", "QUEUE")
ISLAND_EXPANDED_MIN_HEIGHT = 160   # px; the pill is 25/44 logical, the bubble >= 230
ISLAND_OPEN_SETTLE_S = 1.0         # pill_cat appears on the pill's first draw
A_PILL_CAT = {"surface": "pill_cat"}
DEMO_ITEM_FLAG = "mixar_tour_demo"  # ID-property on the tour's own board item
_BUSY_STATES = ("busy", "awaiting_input", "modifying")

_anchor_cache = anchors.AnchorCache(ttl_s=0.5)
_island_opened_at = float("-inf")
_pill_seen_since_open = False
_warned_predicates: set = set()


class _LegacyRestartSuppressed:
    def __enter__(self):
        global suppress_legacy_restart
        self._prev = suppress_legacy_restart
        suppress_legacy_restart = True

    def __exit__(self, *_exc):
        global suppress_legacy_restart
        suppress_legacy_restart = self._prev
        return False


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

def _op(path: str):
    module, _, name = path.partition(".")
    return getattr(getattr(bpy.ops, module, None), name, None)


def _call_op(path: str, **kwargs) -> bool:
    """Call an operator if it exists and polls; True on FINISHED."""
    op = _op(path)
    if op is None:
        _logger.warning("tour actions: operator %s is not registered", path)
        return False
    try:
        if hasattr(op, "poll") and not op.poll():
            _logger.debug("tour actions: %s poll failed", path)
            return False
        return "FINISHED" in op(**kwargs)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("tour actions: %s failed: %s", path, exc)
        return False


def _wm():
    return getattr(bpy.context, "window_manager", None)


def _scene():
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        scenes = getattr(bpy.data, "scenes", None)
        scene = scenes[0] if scenes else None
    return scene


def _bubble_windows() -> list:
    return [w for w in anchors._windows() if anchors._has_area(w, anchors.BUBBLE_AREA)]


def _tallest_bubble_window_px() -> int:
    best = 0
    for window in _bubble_windows():
        try:
            best = max(best, int(window.height))
        except Exception:  # noqa: BLE001
            continue
    return best


def _resting_pill_visible() -> bool:
    return _anchor_cache.get(A_PILL_CAT) is not None


def _shown_bubble_windows() -> list:
    """Bubble windows whose WINDOW region is laid out, i.e. the expanded
    island (a minimised island keeps a hidden full-size window)."""
    from .anchors_windows import _window_is_shown
    return [w for w in _bubble_windows() if _window_is_shown(w)]


def pill_supported() -> bool:
    """True where the island has a resting pill (native window controls:
    macOS and Windows). Elsewhere the island only ever shows expanded."""
    return sys.platform in ("darwin", "win32")


def reset_session_state() -> None:
    """Forget the per-session island bookkeeping and cached anchors.
    Called by the session at start so a restarted tour begins clean."""
    global _island_opened_at, _pill_seen_since_open
    _island_opened_at = float("-inf")
    _pill_seen_since_open = False
    _warned_predicates.clear()
    try:
        _anchor_cache.invalidate()
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour actions: anchor cache reset failed: %s", exc)


def snapshot_state() -> dict:
    """Pre-tour UI state for ``restore_state``; see ``actions_state``."""
    from . import actions_state
    return actions_state.snapshot_state()


def restore_state(snapshot: dict) -> bool:
    """Put the UI back the way ``snapshot_state`` found it (cancelled or
    error exits only; completed/exited tours run ``tour_cleanup``)."""
    from . import actions_state
    try:
        return actions_state.restore_state(snapshot)
    except Exception as exc:  # noqa: BLE001 — never raise into the modal
        _logger.warning("tour actions: restore_state raised: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Actions.
# ---------------------------------------------------------------------------

def ensure_zen(_args: dict) -> bool:
    if get_ui_mode() == UI_MODE_AI:
        return True
    with _LegacyRestartSuppressed():
        return _call_op("mixar.set_ui_mode_ai")


def island_open(_args: dict) -> bool:
    """Leave the island as the resting pill: create it minimised, or
    minimise an island that is already open."""
    global _island_opened_at, _pill_seen_since_open
    _anchor_cache.invalidate()
    # Every path stamps the open time and clears the pill flag, the
    # already-a-pill one included: ``island_expanded`` measures from here.
    _island_opened_at = time.monotonic()
    _pill_seen_since_open = False
    if _resting_pill_visible():
        return True
    if not pill_supported():
        # No resting pill on this platform: the island opens expanded and
        # ``island_expanded`` passes once its window is laid out.
        ok = _call_op("mixar.agent_bubble_open_window")
        _anchor_cache.invalidate()
        return ok
    if not _bubble_windows():
        try:
            from mixar.modules.agent_bubble.core.bubble_autoshow import try_invoke_bubble
            ok = bool(try_invoke_bubble(start_minimised=True))
        except Exception as exc:  # noqa: BLE001
            _logger.warning("tour actions: island_open invoke failed: %s", exc)
            ok = False
        if not ok:
            # No host window yet: at least show the island.
            ok = _call_op("mixar.agent_bubble_open_window")
    else:
        # mixar.bubble_minimise has no poll; CANCELLED means "already a
        # pill", which is fine.
        _call_op("mixar.bubble_minimise")
        ok = True
    _anchor_cache.invalidate()
    return ok


def island_expand(_args: dict) -> bool:
    _anchor_cache.invalidate()
    ok = _call_op("mixar.agent_bubble_open_window")   # restores the pill too
    if not ok:
        ok = _call_op("mixar.bubble_restore")
    _anchor_cache.invalidate()
    return ok


def island_tab(args: dict) -> bool:
    tab = str(args.get("tab", "AGENT"))
    if tab not in TAB_IDS:
        _logger.warning("tour actions: unknown island tab %r", tab)
        return False
    wm = _wm()
    if wm is None:
        return False
    try:
        wm.mixar_bubble_tab = tab
    except Exception as exc:  # noqa: BLE001
        _logger.warning("tour actions: island_tab(%s) failed: %s", tab, exc)
        return False
    return True


def _zen_view3d_override():
    try:
        from mixar.modules.moodboard.ui.moodboard_drawer_props import _view3d_override
        override = _view3d_override()
        if override:
            return override
    except Exception:  # noqa: BLE001
        pass
    window, area, region = anchors.host_region()
    if window is None or area is None or area.type != "VIEW_3D":
        return None
    return {"window": window, "screen": window.screen, "area": area,
            "region": region, "space_data": area.spaces.active}


def drawer_set(args: dict) -> bool:
    try:
        amount = min(1.0, max(0.0, float(args.get("amount", 0.0))))
    except (TypeError, ValueError):
        return False
    target = 1.0 if amount >= 0.5 else 0.0
    # The operator is the only writer: it owns the drawer's animation state
    # and region layout. Poking the WindowManager properties directly left
    # the drawer half-drawn, so there is no raw-property fallback.
    override = _zen_view3d_override()
    if override is None:
        _logger.info("tour actions: drawer_set has no Zen 3D View to target")
        return False
    try:
        with bpy.context.temp_override(**override):
            return _call_op("view3d.moodboard_drawer_set", amount=amount, target=target)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("tour actions: drawer_set operator failed: %s", exc)
        return False


def _board_has_image(scene, path: str) -> bool:
    """The demo image is on the board: the ``mixar_tour_demo`` ID-property
    the tour stamps on its own item wins (it survives a renamed or
    re-packed image), then the source filepath."""
    want_abs = os.path.normcase(os.path.abspath(path))
    try:
        items = list(scene.mixie_moodboard_images)
    except Exception:  # noqa: BLE001
        return False
    for item in items:
        try:
            if item.get(DEMO_ITEM_FLAG):
                return True
        except Exception:  # noqa: BLE001
            pass
        image = getattr(item, "image", None)
        if image is None:
            continue
        filepath = getattr(image, "filepath", "") or ""
        try:
            filepath = bpy.path.abspath(filepath)
        except Exception:  # noqa: BLE001
            pass
        if filepath and os.path.normcase(os.path.abspath(filepath)) == want_abs:
            return True
    return False


def moodboard_add_demo_image(_args: dict) -> bool:
    path = config.demo_image_path()
    if not os.path.isfile(path):
        _logger.warning("tour actions: demo image missing at %s", path)
        return False
    scene = _scene()
    if scene is None:
        return False
    if _board_has_image(scene, path):
        return True
    try:
        from mixar.modules.moodboard.core.media_import import load_media_file_to_board
        item = load_media_file_to_board(scene, path)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("tour actions: moodboard_add_demo_image failed: %s", exc)
        return False
    if item is None:
        return False
    try:
        # MixieMoodboardImage is a PropertyGroup: ID-properties are allowed.
        item[DEMO_ITEM_FLAG] = True
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour actions: demo flag not stored: %s", exc)
    return True


def ui_mode(args: dict) -> bool:
    mode = str(args.get("mode", "AI")).upper()
    wanted = {"AI": UI_MODE_AI, "PRO": UI_MODE_PRO}.get(mode)
    if wanted is None:
        _logger.warning("tour actions: unknown ui mode %r", mode)
        return False
    if get_ui_mode() == wanted:
        return True
    with _LegacyRestartSuppressed():
        return _call_op("mixar.set_ui_mode_ai" if wanted == UI_MODE_AI
                        else "mixar.set_ui_mode_pro")


def tour_cleanup(_args: dict) -> bool:
    """End state of a completed or user-exited tour: Zen Mode with the
    island on the Agent tab. The moodboard drawer stays as it is — open,
    showing the demo concept — by design."""
    ok = island_tab({"tab": "AGENT"})
    return ensure_zen({}) and ok


_ACTIONS = {
    "ensure_zen": ensure_zen,
    "island_open": island_open,
    "island_expand": island_expand,
    "island_tab": island_tab,
    "drawer_set": drawer_set,
    "moodboard_add_demo_image": moodboard_add_demo_image,
    "ui_mode": ui_mode,
    "tour_cleanup": tour_cleanup,
}

# Library source + Creator Program Help menu (split out for size).
from .actions_extra import EXTRA_ACTIONS  # noqa: E402

_ACTIONS.update(EXTRA_ACTIONS)


def run(name: str, args: dict) -> bool:
    fn = _ACTIONS.get(name)
    if fn is None:
        _logger.warning("tour actions: unknown action %r", name)
        return False
    try:
        ok = bool(fn(dict(args or {})))
    except Exception as exc:  # noqa: BLE001 — never raise into the modal
        _logger.warning("tour actions: %s raised: %s", name, exc)
        return False
    if not ok:
        _logger.info("tour actions: %s did not complete", name)
    return ok


# ---------------------------------------------------------------------------
# Gate predicates.
# ---------------------------------------------------------------------------

def _island_expanded(_flags: dict) -> bool:
    """True once the resting pill has been seen since ``island_open`` and
    is gone again — the one signal a hidden (minimised) island window
    cannot fake, since it keeps its full height and its uiblocks while
    ordered out. If the pill never appears (minimise unsupported), the
    gate's wall timer runs the auto path instead."""
    global _pill_seen_since_open
    if time.monotonic() - _island_opened_at < ISLAND_OPEN_SETTLE_S:
        return False
    if not pill_supported():
        # No pill will ever appear: the laid-out island window is the signal.
        return bool(_shown_bubble_windows()) or _anchor_cache.get(A_TAB_AGENT) is not None
    if _resting_pill_visible():
        _pill_seen_since_open = True
        return False
    if _island_opened_at > 0.0:
        return _pill_seen_since_open
    # island_open never ran this session (tour started mid-way): fall back
    # to the visible-tab / window-height heuristics.
    if _anchor_cache.get(A_TAB_AGENT) is not None:
        return True
    return _tallest_bubble_window_px() > ISLAND_EXPANDED_MIN_HEIGHT


def _bubble_tab_is(tab: str) -> bool:
    wm = _wm()
    return wm is not None and getattr(wm, "mixar_bubble_tab", None) == tab


def _drawer_open(_flags: dict) -> bool:
    wm = _wm()
    try:
        return wm is not None and float(wm.mixar_moodboard_drawer_amount) >= 0.98
    except (TypeError, ValueError):
        return False


def _ui_mode_is(mode: str) -> bool:
    wanted = {"AI": UI_MODE_AI, "PRO": UI_MODE_PRO}.get(mode.upper())
    return wanted is not None and get_ui_mode() == wanted


def check(predicate: str, flags: dict) -> bool:
    flags = flags or {}
    try:
        if predicate == "viewport_interacted":
            return bool(flags.get("viewport_interacted"))
        if predicate == "island_expanded":
            return _island_expanded(flags)
        if predicate.startswith("bubble_tab:"):
            return _bubble_tab_is(predicate.split(":", 1)[1])
        if predicate == "drawer_open":
            return _drawer_open(flags)
        if predicate.startswith("ui_mode:"):
            return _ui_mode_is(predicate.split(":", 1)[1])
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour actions: check(%s) failed: %s", predicate, exc)
        return False
    if predicate not in _warned_predicates:
        _warned_predicates.add(predicate)
        _logger.warning("tour actions: unknown gate predicate %r", predicate)
    return False
