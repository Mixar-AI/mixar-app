# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Central registry for Python-level data migrations.

Migrations are sorted by (version, subversion) and run sequentially on scenes
whose stored version is older than the migration's target version.

Usage:
    from mixar.modules.common.versioning import register_migration

    def my_migration(scene):
        # modify scene data ...
        pass

    register_migration(1, 0, my_migration, "Description of what changed")
"""

import logging

logger = logging.getLogger(__name__)

# Current Python schema version. Bump subversion when adding migrations.
MIXAR_PY_VERSION = (1, 0)

# Sorted list of (version, subversion, callable, description)
_migrations = []


def register_migration(version, subversion, fn, description=""):
    """Register a migration function for a specific version.

    Args:
        version: Major version this migration targets.
        subversion: Sub-version this migration targets.
        fn: Callable(scene) that performs the migration.
        description: Human-readable description of the migration.
    """
    _migrations.append((version, subversion, fn, description))
    _migrations.sort(key=lambda m: (m[0], m[1]))


def get_file_version(scene):
    """Return the Mixar Python version stored in a scene.

    Returns (0, 0) for pre-versioning files.
    """
    raw = scene.get("_mixar_file_version")
    if raw is None:
        return (0, 0)
    return (int(raw[0]), int(raw[1]))


def set_file_version(scene, version=None):
    """Stamp the current Mixar Python version onto a scene."""
    ver = version or MIXAR_PY_VERSION
    scene["_mixar_file_version"] = [ver[0], ver[1]]


def run_migrations(scene):
    """Run all pending migrations on a scene.

    Only migrations whose (version, subversion) is strictly newer than
    the scene's stored version are executed.

    Returns:
        int: Number of migrations applied.
    """
    file_ver = get_file_version(scene)
    applied = 0
    for ver, subver, fn, desc in _migrations:
        if file_ver < (ver, subver):
            try:
                logger.info("Running migration (%d.%d): %s", ver, subver, desc)
                fn(scene)
                applied += 1
            except Exception:
                logger.exception(
                    "Migration (%d.%d) failed: %s", ver, subver, desc
                )
    if applied:
        set_file_version(scene)
        logger.info("Applied %d migration(s), version now %s", applied, MIXAR_PY_VERSION)
    return applied
