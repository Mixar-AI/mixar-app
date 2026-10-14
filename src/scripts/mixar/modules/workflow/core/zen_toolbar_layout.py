# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Width tiers for the Zen scene toolbar (pure; widths in logical pixels).

The toolbar is three lanes: left (Scene, Add Objects, render settings), the
centred shading cluster and the right lane (Cinema, playback, Sky Light,
Export). A tier is chosen by summing the lanes' laid-out widths, so the
widest layout that actually fits is always shown; narrower tiers move
controls into native popovers rather than letting the header clip them.
Lane widths are measured at 1x in the running app (layout-time, so the Scene
button counts at its reserved hover width) and include each lane's internal
row gaps; re-measure them when a toolbar control changes width.
"""

FULL = "FULL"
"""Inline render engine + samples; every right-lane control inline."""
COMPACT = "COMPACT"
"""Render settings collapse into a labelled popover."""
NARROW = "NARROW"
"""Render popover becomes an icon; playback, Sky Light and Export move into
the Scene Controls overflow popover."""
TIGHT = "TIGHT"
"""Cinema Mode also moves into the overflow popover."""
MINIMAL = "MINIMAL"
"""The grid/X-ray chips join the overflow and the shading row shrinks to its
popover, leaving Scene, Add Objects, render, shading and overflow."""

_ORDER = (FULL, COMPACT, NARROW, TIGHT, MINIMAL)

LEFT_BASE_PX = 249.0
"""Header inset, the Scene button at its reserved hover width (the native
pass contracts it at rest), Add Objects and the gap before render settings."""

RENDER_PX = {FULL: 481.0, COMPACT: 160.0}
"""Inline engine + samples, or the labelled popover; icon-only below."""
RENDER_ICON_PX = 32.0

OBJECT_CONTROLS_PX = {FULL: 140.0, COMPACT: 140.0}
"""The Object Controls restore button, shown while the floating selection
menu is closed; icon-only (below) from NARROW on."""
OBJECT_CONTROLS_ICON_PX = 36.0

CENTER_PX = 165.0
"""Grid, X-ray, the four shading modes and the shading popover."""
CENTER_MINIMAL_PX = 32.0

RIGHT_FULL_PX = 584.0
"""Cinema 180 + playback + Sky Light + Export, with the trailing inset."""
RIGHT_NARROW_PX = 228.0
"""Cinema + the overflow popover."""
RIGHT_TIGHT_PX = 40.0
"""The overflow popover alone."""

MIN_GAP_PX = 14.0
"""Smallest flexible gap kept on each side of the centred cluster."""


def required_width(tier, *, object_controls=False):
    """Logical header width the lanes of `tier` need, gaps included."""
    left = LEFT_BASE_PX + RENDER_PX.get(tier, RENDER_ICON_PX)
    if object_controls:
        left += OBJECT_CONTROLS_PX.get(tier, OBJECT_CONTROLS_ICON_PX)
    center = CENTER_MINIMAL_PX if tier == MINIMAL else CENTER_PX
    if tier in (FULL, COMPACT):
        right = RIGHT_FULL_PX
    elif tier == NARROW:
        right = RIGHT_NARROW_PX
    else:
        right = RIGHT_TIGHT_PX
    return left + center + right + 2 * MIN_GAP_PX


def tier_for_width(width, *, object_controls=False):
    """The widest tier whose lanes fit in `width`."""
    for tier in _ORDER[:-1]:
        if width >= required_width(tier, object_controls=object_controls):
            return tier
    return MINIMAL


def at_most(tier, limit):
    """True when `tier` is `limit` or narrower."""
    return _ORDER.index(tier) >= _ORDER.index(limit)


def overflow_sections(tier):
    """Controls drawn in the Scene Controls popover for `tier`, in order."""
    if not at_most(tier, NARROW):
        return ()
    sections = []
    if at_most(tier, TIGHT):
        sections.append("CINEMA")
    if at_most(tier, MINIMAL):
        sections.append("GUIDES")
    sections += ["PLAYBACK", "SKY", "EXPORT"]
    return tuple(sections)
