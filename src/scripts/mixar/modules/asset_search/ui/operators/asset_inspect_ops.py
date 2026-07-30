# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Asset Inspect Operators

Thin wrapper around ``core/render_session.py``: the standalone operator runs
a full render session to completion; the training modal drives the session
itself (chunked per timer tick) for real-time progress. The module keeps its
original public API (``get_collected_asset_data`` / render-filter functions)
for existing callers.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.core.render_session import (
    RenderSession,
    build_render_plan,
    collect_asset_metadata as _collect_asset_metadata,  # noqa: F401 — re-export
)

logger = get_logger(__name__)

# Module-level storage for collected asset data (populated by inspect operator
# or by the training modal after its chunked session finishes).
_collected_assets = []

# Render filter: None = render all, set = only matching identities
_render_filter = None


def get_collected_asset_data():
    """Return the list of asset metadata dicts collected by the last run."""
    return list(_collected_assets)


def set_collected_asset_data(assets):
    """Publish a finished render session's results for downstream consumers."""
    global _collected_assets
    _collected_assets = list(assets)


def set_render_filter(asset_identities):
    """Set filter so only matching assets (name/library/blend_file dicts) are rendered."""
    global _render_filter
    if asset_identities is None:
        _render_filter = None
    else:
        _render_filter = {
            f"{a['name']}|{a['library']}|{a['blend_file']}"
            for a in asset_identities
        }


def clear_render_filter():
    global _render_filter
    _render_filter = None


def get_render_filter():
    """The current identity-filter set (or None) for plan building."""
    return _render_filter


class MIXIE_OT_inspect_asset_libraries(Operator):
    """Scan custom asset libraries, render EEVEE previews for each asset"""

    bl_idname = "mixie.inspect_asset_libraries"
    bl_label = "Inspect Asset Libraries"
    bl_description = (
        "Scan all custom asset libraries, render 512x512 EEVEE previews "
        "for each object and collection asset, and store them in memory"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        _collected_assets.clear()

        if not context.preferences.filepaths.asset_libraries:
            self.report({"WARNING"}, "No custom asset libraries found")
            return {"CANCELLED"}

        items, discovery_failures = build_render_plan(context, _render_filter)
        session = RenderSession(context, items)
        session.failures.extend(discovery_failures)
        session.start()
        try:
            while not session.done:
                session.step(8)
        finally:
            session.finish()

        set_collected_asset_data(session.collected)
        for label, reason in session.failures:
            logger.warning("[Asset Inspector] Skipped %s: %s", label, reason)

        summary = (
            f"Rendered {len(session.collected)} asset preview(s) to memory"
            + (f", {len(session.failures)} skipped" if session.failures else "")
        )
        logger.debug("[Asset Inspector] %s", summary)
        self.report({"INFO"}, summary)
        return {"FINISHED"}


classes = (
    MIXIE_OT_inspect_asset_libraries,
)


def register():
    """Register operator classes"""
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    """Unregister operator classes"""
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
