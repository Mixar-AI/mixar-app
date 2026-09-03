# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Plugin import inside Edit > Preferences > Add-ons — the primary host.

Placement note: this *prepends* a draw function onto the upstream
``USERPREF_PT_addons`` panel rather than registering a sibling Panel with
``bl_context = "addons"``. A sibling would work (see
``common/ui/panels/privacy_panel.py`` for that pattern), but ``bl_order``
is RNA ``PROP_UNSIGNED`` and ``USERPREF_PT_addons`` already sits at the
default 0, so a panel registered later can only ever sort *below* the
entire scrolling add-on list — the wrong place for an import action the
user is looking for once, early.

``prepend`` is the sanctioned extension point: upstream's own extensions
add-on (``addons_core/bl_pkg``) appends to this very panel, and Blender's
``_GenericUI`` dispatcher isolates each draw function's exceptions, so a
failure here cannot take down the Add-ons tab.

``USERPREF_PT_addons`` carries ``bl_options = {'HIDE_HEADER'}``, so there
is no real panel header to collapse — the section draws its own
disclosure triangle off ``state.show_panel``.
"""

from __future__ import annotations

from bl_ui.space_userpref import USERPREF_PT_addons

from mixar.config.logging_config import get_logger

from ..plugin_import_drawer import draw_plugin_import

logger = get_logger(__name__)


def _draw_addons_prefs_section(panel, context) -> None:
    """Prepended to ``USERPREF_PT_addons.draw``. Signature is (panel, context)."""
    layout = panel.layout
    state = getattr(context.window_manager, "mixie_plugin_import", None)

    box = layout.box()

    header = box.row(align=True)
    if state is None:
        # Properties not registered yet (early startup) — show the header
        # only, so the tab never renders a half-built section.
        header.label(text="Import from Blender", icon="IMPORT")
        return

    header.prop(
        state,
        "show_panel",
        text="",
        icon="TRIA_DOWN" if state.show_panel else "TRIA_RIGHT",
        emboss=False,
    )
    header.label(text="Import from Blender", icon="IMPORT")

    if state.scanned and len(state.plugins):
        sub = header.row(align=True)
        sub.alignment = "RIGHT"
        sub.label(text=f"{len(state.plugins)} found")

    if state.show_panel:
        draw_plugin_import(box, context)

    layout.separator()


def register() -> None:
    # Defensive: the UI loader may re-run register() for a module that has
    # no `classes` tuple to detect prior registration with.
    USERPREF_PT_addons.remove(_draw_addons_prefs_section)
    USERPREF_PT_addons.prepend(_draw_addons_prefs_section)
    logger.debug("Plugin import section added to Preferences > Add-ons")


def unregister() -> None:
    USERPREF_PT_addons.remove(_draw_addons_prefs_section)
