# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Auto-enable the bundled KIRI 3DGS Render addon at startup.

World Labs worlds arrive as Gaussian splats which we convert to a 3DGS PLY and
import via KIRI 3DGS Render (it builds the real-time splat geometry-nodes setup
and exposes ``sna.dgs_render_import_ply_e0a3a``). We vendor KIRI **v4.1.5**
(supports Blender 4.3-5.0; do NOT use v5.x which targets Blender 5.1+) under
``scripts/addons/`` so users never install anything.

This bootstrap simply enables the addon if it is present. It is a graceful
no-op when the addon hasn't been vendored: the World Labs importer falls back
to a plain (non-splat) PLY import and logs a warning, so the rest of Mixar is
unaffected.

NOTE: the addon folder must be a valid Python module name — it cannot start
with a digit, so the vendored folder is ``kiri_3dgs_render`` (not
``3dgs_render``). The internal operator ids are unaffected (they are
Serpens-generated and independent of the folder name).
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Vendored addon module/folder name under scripts/addons/.
_ADDON_MODULE = "kiri_3dgs_render"


def register() -> None:
    """Enable the KIRI 3DGS Render addon if it is bundled."""
    try:
        import addon_utils
    except Exception as exc:  # pragma: no cover - bpy/addon_utils always present in Blender
        logger.debug("addon_utils unavailable: %s", exc)
        return

    # Is the addon discoverable? (present under a scripts/addons path)
    available = {mod.__name__ for mod in addon_utils.modules()}
    if _ADDON_MODULE not in available:
        logger.info(
            "KIRI 3DGS Render addon ('%s') not bundled; World Labs splat "
            "rendering will be unavailable until it is vendored under "
            "scripts/addons/. World import falls back to plain PLY.",
            _ADDON_MODULE,
        )
        return

    try:
        default_set, loaded = addon_utils.check(_ADDON_MODULE)
        if not loaded:
            addon_utils.enable(_ADDON_MODULE, default_set=True, persistent=True)
            logger.info("Enabled KIRI 3DGS Render addon ('%s')", _ADDON_MODULE)
    except Exception as exc:
        logger.warning("Failed to enable KIRI 3DGS Render addon: %s", exc)


def unregister() -> None:
    """Leave the addon enabled on teardown.

    We intentionally do not disable it on unregister: it is a user-facing addon
    and may be in use independently of the World Labs feature.
    """
    return
