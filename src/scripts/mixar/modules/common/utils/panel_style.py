# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared "new design" panel-styling primitives.

The Mixar account card introduced a native, dark, teal-accented design
language backed by the ``MX_*`` palette. That language is exposed to Python
through a small set of ``layout.mixar_*`` methods (rendered in C++ by the
``widget_mixar_*`` widgets): ``mixar_section``, ``mixar_dropdown``,
``mixar_toggle``, ``mixar_input`` and ``mixar_operator``.

This module wraps those methods with graceful ``layout.box()`` / ``prop()`` /
``operator()`` fallbacks so any Mixar panel — in any module — can adopt the
new design with a single import, while still rendering correctly on an older
build whose C++ predates the widgets (and under the ``bpy`` test mock, where
the styled methods do not exist).

It is the module-agnostic home for this pattern. ``moodboard`` and
``asset_search`` grew their own local copies before this existed; new panels
should depend on this ``common`` helper instead of those module-scoped ones.

The spacing tokens mirror ``moodboard.constants`` so panels share one rhythm.
"""

from __future__ import annotations

# Vertical rhythm — kept in sync with ``moodboard.constants`` so every Mixar
# surface breathes the same way. Duplicated (not imported) so this ``common``
# helper carries no dependency on the moodboard module.
SEP_SECTION = 0.8   #: Between major sections.
SEP_INTRA = 0.15    #: Between elements inside a section.
SEP_FOOTER = 1.0    #: Before a primary action (Generate / submit).
HINT_SCALE_Y = 0.85     #: Subtle info / constraint labels.
ACTION_SCALE_Y = 1.4    #: Primary call-to-action buttons.


def _has(layout, name: str) -> bool:
    """True when *layout* exposes a styled ``mixar_*`` method.

    A plain ``getattr(..., None)`` is not enough under the test mock: a
    ``MagicMock`` auto-creates every attribute, so ``hasattr`` is always
    True there. Panels are expected to run against a real ``uiLayout`` in
    Blender; the explicit check keeps the fallback path reachable for the
    mock and for older builds.
    """
    return hasattr(layout, name)


def section(layout, label=None, icon='NONE', *, align=False):
    """Open a styled section container and return a column to draw into.

    Uses the native ``mixar_section`` card (dark fill, subtle border,
    rounded corners) when available, otherwise a standard ``box()``. When
    *label* is given it is drawn as the section header followed by a small
    intra-section separator.
    """
    box = layout.mixar_section() if _has(layout, 'mixar_section') else layout.box()
    col = box.column(align=align)
    if label:
        col.label(text=label, icon=icon)
        col.separator(factor=SEP_INTRA)
    return col


def section_separator(layout):
    """Standard separator between two major sections."""
    layout.separator(factor=SEP_SECTION)


def dropdown(layout, data, prop, text=""):
    """Enum selector — styled ``mixar_dropdown`` with a ``prop()`` fallback."""
    if _has(layout, 'mixar_dropdown'):
        layout.mixar_dropdown(data, prop, text=text)
    else:
        layout.prop(data, prop, text=text)


def toggle(layout, data, prop, text=""):
    """Boolean pill toggle — ``mixar_toggle`` with a ``prop()`` fallback."""
    if _has(layout, 'mixar_toggle'):
        layout.mixar_toggle(data, prop, text=text)
    else:
        layout.prop(data, prop, text=text)


def text_input(layout, data, prop, text=""):
    """Text field with a focus ring — ``mixar_input`` w/ ``prop()`` fallback."""
    if _has(layout, 'mixar_input'):
        layout.mixar_input(data, prop, text=text)
    else:
        layout.prop(data, prop, text=text)


def hint(layout, text, icon='NONE'):
    """Subtle, smaller-scale info / constraint label."""
    row = layout.row()
    row.scale_y = HINT_SCALE_Y
    row.label(text=text, icon=icon)


def primary_operator(layout, operator_id, text="", icon='NONE'):
    """Primary call-to-action button.

    Renders the gradient/teal-glow ``mixar_operator`` when available,
    otherwise a plain ``operator()``. Returns the operator properties so
    callers can set fields on it (identical to ``layout.operator``).
    """
    if _has(layout, 'mixar_operator'):
        return layout.mixar_operator(operator_id, text=text, icon=icon)
    return layout.operator(operator_id, text=text, icon=icon)
