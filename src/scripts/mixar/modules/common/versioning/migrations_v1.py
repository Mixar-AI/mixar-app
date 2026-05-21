# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Initial migrations for Mixar Python schema v1.0.

This module registers migrations that bring pre-versioning files
up to Python schema version (1, 0).
"""

import logging

import bpy

from .registry import register_migration

logger = logging.getLogger(__name__)


def _migrate_layer_schema_v2(scene):
    """Upgrade paint layers to schema v2 (Substance Painter style architecture).

    Iterates all node groups that are Mixar paint node groups and ensures
    their layers have the current schema version set.
    """
    from mixar.modules.paint.core.migration.layer_migration import ensure_all_layers_schema

    for nt in bpy.data.node_groups:
        mp = getattr(nt, 'mp', None)
        if mp is not None and getattr(mp, 'is_mpaint_node', False):
            ensure_all_layers_schema(mp)
            logger.debug("Migrated layers for node group '%s'", nt.name)


register_migration(1, 0, _migrate_layer_schema_v2, "Upgrade paint layers to schema v2")
