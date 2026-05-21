# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...utils.common import get_entity_prop_value


def get_transformation(mapping, entity=None):
    """Extract transformation values from a mapping node.

    Retrieves translation, rotation, and scale values from a mapping node's inputs.
    If the entity has uniform scale enabled, the scale value is retrieved from the
    entity's uniform_scale_value property and applied uniformly across all axes.

    Parameters:
        mapping: The mapping node to extract transformation values from.
        entity: Optional entity object that may contain uniform scale settings.
                Default: None

    Returns:
        tuple: A tuple of three tuples (translation, rotation, scale), where:
            - translation (tuple): (x, y, z) translation values
            - rotation (tuple): (x, y, z) rotation values in radians
            - scale (tuple): (x, y, z) scale values
    """
    translation = (0.0, 0.0, 0.0)
    rotation = (0.0, 0.0, 0.0)
    scale = (1.0, 1.0, 1.0)

    translation = mapping.inputs[1].default_value
    rotation = mapping.inputs[2].default_value

    if entity and hasattr(entity, 'enable_uniform_scale') and entity.enable_uniform_scale:
        scale_val = get_entity_prop_value(entity, 'uniform_scale_value')
        scale = (scale_val, scale_val, scale_val)
    else:
        scale = mapping.inputs[3].default_value

    return translation, rotation, scale

def is_transformed(mapping, entity=None):
    """Check if a mapping node has any non-default transformation applied.

    Determines whether the mapping has any translation, rotation, or scale that differs
    from the default values (0.0 for translation/rotation, 1.0 for scale).

    Parameters:
        mapping: The mapping node to check for transformations.
        entity: Optional entity object that may contain uniform scale settings.
                Default: None

    Returns:
        bool: True if any transformation is applied, False if all transformations
              are at their default values.
    """
    translation, rotation, scale = get_transformation(mapping, entity)

    for t in translation:
        if t != 0.0: return True

    for r in rotation:
        if r != 0.0: return True

    for s in scale:
        if s != 1.0: return True

    return False
