# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Auto-enable the bundled KIRI 3DGS Render addon at startup.

Splat environments (World Labs worlds, locally imported ``.spz``/``.ply``)
are Gaussian splats which we convert to a 3DGS PLY and import via KIRI 3DGS
Render (it builds the real-time splat geometry-nodes setup and exposes
``sna.dgs_render_import_ply_e0a3a``). We vendor KIRI **v4.1.5** (supports
Blender 4.3-5.0; do NOT use v5.x which targets Blender 5.1+) under
``scripts/addons_core/kiri_3dgs_render`` so users never install anything —
``addon_utils.paths()`` maps the bundled scripts dir to ``addons_core``
(a plain ``scripts/addons`` would never be scanned there). The upstream
extension wheels (open3d/scipy/dash, ~1 GB) are deliberately NOT vendored:
the import + render path never touches them and the addon's only open3d
uses are availability-guarded. See the vendored README.mixar.md.

**The enable MUST be deferred to a timer.** Bootstrap ``register()`` runs
during startup-script registration, when ``bpy.context`` is the restricted
``_RestrictContext`` — and KIRI's own ``register()`` reaches into the window
manager (addon keymaps), so ``addon_utils.enable`` fails there and the addon
silently stays off (the shipped build imported splats as plain green point
clouds). A one-shot ``bpy.app.timers`` callback runs after startup completes
with a real context, where the same enable succeeds.

The splat importer also self-heals (``world_labs_importer._ensure_kiri``)
by enabling on demand, so a failure here degrades to a slightly slower first
import rather than a lost feature.

NOTE: the addon folder must be a valid Python module name — it cannot start
with a digit, so the vendored folder is ``kiri_3dgs_render`` (not
``3dgs_render``). The internal operator ids are unaffected (they are
Serpens-generated and independent of the folder name).
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Vendored addon module/folder name under scripts/addons_core/.
_ADDON_MODULE = "kiri_3dgs_render"

_MAX_ATTEMPTS = 3
_RETRY_INTERVAL_S = 2.0
_attempts = 0


def _enable_kiri():
    """Timer callback: enable the vendored addon; retry a few times.

    Returns None to stop the timer, or a float to run again later.
    """
    global _attempts
    _attempts += 1
    try:
        import addon_utils

        available = {mod.__name__ for mod in addon_utils.modules()}
        if _ADDON_MODULE not in available:
            if _attempts < _MAX_ATTEMPTS:
                return _RETRY_INTERVAL_S
            logger.info(
                "KIRI 3DGS Render addon ('%s') not bundled; splat rendering "
                "will be unavailable until it is vendored under "
                "scripts/addons_core/. Splat import falls back to plain PLY.",
                _ADDON_MODULE,
            )
            return None

        _default_set, loaded = addon_utils.check(_ADDON_MODULE)
        if not loaded:
            addon_utils.enable(_ADDON_MODULE, default_set=True, persistent=True)
            logger.info("Enabled KIRI 3DGS Render addon ('%s')", _ADDON_MODULE)
        return None
    except Exception as exc:  # noqa: BLE001
        if _attempts < _MAX_ATTEMPTS:
            logger.debug(
                "KIRI enable attempt %d failed (%s); retrying", _attempts, exc,
            )
            return _RETRY_INTERVAL_S
        logger.warning("Failed to enable KIRI 3DGS Render addon: %s", exc)
        return None


def register() -> None:
    """Schedule the addon enable for after startup (real context)."""
    global _attempts
    _attempts = 0
    try:
        import bpy

        bpy.app.timers.register(_enable_kiri, first_interval=0.5)
    except Exception as exc:  # pragma: no cover - bpy always present in Blender
        logger.debug("Could not schedule KIRI addon enable: %s", exc)


def unregister() -> None:
    """Cancel a pending enable; leave an already-enabled addon alone.

    We intentionally do not disable the addon here: it is a user-facing addon
    and may be in use independently of the splat features.
    """
    try:
        import bpy

        if bpy.app.timers.is_registered(_enable_kiri):
            bpy.app.timers.unregister(_enable_kiri)
    except Exception:  # noqa: BLE001
        pass
