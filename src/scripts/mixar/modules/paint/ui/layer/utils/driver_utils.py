# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Driver utility functions for layer duplication."""


def update_driver_targets(obj, target_map):
    """Update driver target object references based on a given object map.

    Args:
        obj: Blender object with animation data.
        target_map (dict): Mapping of old object references to new ones.
    """
    for fcurve in obj.animation_data.drivers if obj.animation_data else []:
        for var in fcurve.driver.variables:
            for target in var.targets:
                if target.id in target_map:
                    target.id = target_map[target.id]
