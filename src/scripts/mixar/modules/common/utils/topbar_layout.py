# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Width budgets for the global menu bar (menus | centred mode slider | account).

The Zen/Engine slider is centred on the WINDOW by native code
(`mixar_topbar_center_mode_slider`), so each side of the bar owns the lane
between the window edge and the slider. The left header shows the editor
menus there; the RIGHT header shows the sound toggle and the account pill
(plus the Engine selectors and Cinema pill). When a lane is too short, its
contents compact instead of running under the slider.

Everything here is pure: widths are logical pixels (region pixels divided by
`preferences.system.ui_scale`), where one UI unit is 20 logical pixels.
"""

UNIT_PX = 20.0

SLIDER_HALF_UNITS = 5.5
"""Half the slider's width in UI units — the design's 220 px track, halved.
The topbar header draws each half at this width; the native painter mirrors
the left half's rectangle to find the full track."""

SLIDER_CLEARANCE_PX = 8.0
"""Gap the native centring keeps between the slider and anything before it."""

EDITOR_MENUS_PX = 262.0
"""Logo + File/Edit/Render/Window/Help plus the trailing separator, as laid
out at 1x (measured ~250 in the running app) with a little slack."""

WORKSPACE_MENU_PX = 28.0
"""Engine's Workspaces icon menu, which follows the editor menus."""

RIGHT_FIXED_PX = 72.0
"""Right header: leading separator, collapsed sound toggle (1.8 units),
the small gap before the account pill and the region's own padding."""

SOUND_TOGGLE_PX = 44.0
"""The collapsed sound toggle and its gap, part of RIGHT_FIXED_PX. It is the
first thing the right lane gives up (it is also in Preferences)."""

ENGINE_RIGHT_EXTRA_PX = 260.0
"""Engine-only right header content (measured): the scene/view-layer popover
and the 180 px Cinema pill, with their gaps."""

ENGINE_SELECTORS_PX = 300.0
"""Extra width of Engine's full scene + view-layer selectors over the popover."""

ENGINE_SELECTORS_MIN_WIDTH = 1640.0
"""Engine never shows the full selectors on a narrower window."""

PROFILE_BASE_UNITS = 3.8
PROFILE_CHAR_UNITS = 0.35
"""The account pill grows with the email: `len(email) * 0.35 + 3.8` units."""

PROFILE_MIN_LABEL_UNITS = 8.0
"""Below this the label would show only a few characters; show the avatar."""

PROFILE_AVATAR_UNITS = 1.8
"""Avatar-only pill: the painter caps the right end with a full-height disc,
so a pill as wide as it is tall (36 logical px) is just the disc."""

LOGIN_UNITS = 6.4
"""Login button with its label."""
LOGIN_ICON_UNITS = 2.6
"""Icon-only Login: the person icon plus the popover's chevron."""

ELLIPSIS = "…"


def logical_width(pixels, ui_scale):
    """Region/area width in logical pixels at the current UI scale."""
    return float(pixels) / max(float(ui_scale or 1.0), 0.01)


def side_lane_px(window_width):
    """Width available on EACH side of the centred slider."""
    return window_width * 0.5 - SLIDER_HALF_UNITS * UNIT_PX - SLIDER_CLEARANCE_PX


def collapse_editor_menus(window_width, *, engine=False):
    """True when the inline editor menus would run under the slider."""
    needed = EDITOR_MENUS_PX + (WORKSPACE_MENU_PX if engine else 0.0)
    return side_lane_px(window_width) < needed


def truncate_middle(text, max_chars):
    """Shorten `text` to `max_chars` with a middle ellipsis (keeps the domain)."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars == 1:
        return ELLIPSIS
    head = max_chars // 2
    tail = max_chars - 1 - head
    return text[:head] + ELLIPSIS + (text[-tail:] if tail else "")


def _account_budget_units(window_width, engine, sound=True, selectors=False):
    budget_px = side_lane_px(window_width) - RIGHT_FIXED_PX
    if engine:
        budget_px -= ENGINE_RIGHT_EXTRA_PX
        if selectors:
            budget_px -= ENGINE_SELECTORS_PX
    if not sound:
        budget_px += SOUND_TOGGLE_PX
    return budget_px / UNIT_PX


def full_account_units(logged_in, email):
    """Width of the account button with its whole label."""
    if logged_in:
        return len(email) * PROFILE_CHAR_UNITS + PROFILE_BASE_UNITS
    return LOGIN_UNITS


def context_account_units(context):
    """`full_account_units` for the account the menu bar is showing."""
    logged_in = bool(getattr(context.window_manager, "mixie_chat_is_logged_in", False))
    scene = getattr(context, "scene", None)
    email = getattr(scene, "mixie_chat_user_id", "") if scene is not None else ""
    return full_account_units(logged_in, email or "")


def engine_full_selectors(window_width, account_units):
    """True when Engine's full scene/view-layer selectors fit beside the
    account button's whole label; otherwise they share one popover."""
    return (window_width >= ENGINE_SELECTORS_MIN_WIDTH and
            _account_budget_units(window_width, True, selectors=True) >= account_units)


def show_sound_toggle(window_width, *, engine=False, logged_in=True):
    """False when even the smallest account button would reach the slider."""
    smallest = PROFILE_AVATAR_UNITS if logged_in else LOGIN_ICON_UNITS
    return _account_budget_units(window_width, engine) >= smallest


def login_button(window_width, *, engine=False, sound=True, selectors=False):
    """(ui_units_x, label) for the logged-out Login button."""
    if LOGIN_UNITS <= _account_budget_units(window_width, engine, sound, selectors):
        return LOGIN_UNITS, "Login"
    return LOGIN_ICON_UNITS, ""


def profile_pill(email, window_width, *, engine=False, sound=True, selectors=False):
    """(ui_units_x, label) for the account pill in the right lane.

    Full email when it fits; otherwise a narrower pill with a middle-ellipsised
    label; on the tightest windows the avatar disc alone. The popover it opens
    always shows the full account.
    """
    full = len(email) * PROFILE_CHAR_UNITS + PROFILE_BASE_UNITS
    budget = _account_budget_units(window_width, engine, sound, selectors)
    if full <= budget:
        return full, email
    if budget >= PROFILE_MIN_LABEL_UNITS:
        chars = int((budget - PROFILE_BASE_UNITS) / PROFILE_CHAR_UNITS)
        label = truncate_middle(email, chars)
        return len(label) * PROFILE_CHAR_UNITS + PROFILE_BASE_UNITS, label
    return PROFILE_AVATAR_UNITS, ""
