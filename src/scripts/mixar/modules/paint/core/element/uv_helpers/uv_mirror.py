# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
UV mirror offset handling functions.
"""

from mathutils import Vector

from ......config.logging_config import get_logger
from ....utils.common import get_first_mirror_modifier

logger = get_logger(__name__)


def set_uv_mirror_offsets(obj, matrix):
    """
    Set UV mirror offsets on the object's mirror modifier based on transformation matrix.

    This function adjusts the mirror modifier's UV offset values (mirror_offset_u,
    mirror_offset_v, offset_u, offset_v) based on the provided transformation matrix.
    The original offset values are stored in the object's mp properties before modification.

    Parameters
    ----------
    obj : bpy.types.Object
        The Blender object with a mirror modifier whose UV offsets need to be adjusted.
    matrix : mathutils.Matrix
        The transformation matrix used to calculate new offset values.

    Returns
    -------
    None
    """
    mirror = get_first_mirror_modifier(obj)
    if not mirror:
        return

    movec = Vector((mirror.mirror_offset_u / 2, mirror.mirror_offset_v / 2, 0.0))
    movec = matrix @ movec

    if mirror.use_mirror_u:
        obj.mp.ori_mirror_offset_u = mirror.mirror_offset_u
        mirror.mirror_offset_u = movec.x * 2 - (1.0 - matrix[0][0])

    if mirror.use_mirror_v:
        obj.mp.ori_mirror_offset_v = mirror.mirror_offset_v
        mirror.mirror_offset_v = movec.y * 2 - (1.0 - matrix[1][1])

    obj.mp.ori_offset_u = mirror.offset_u
    mirror.offset_u *= matrix[0][0]

    obj.mp.ori_offset_v = mirror.offset_v
    mirror.offset_v *= matrix[1][1]
