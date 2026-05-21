# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
UV transformation matrix building and application functions.
"""

from mathutils import Euler, Matrix
import numpy

from ....utils.common import get_entity_prop_value


def build_transformation_matrix(mapping, entity):
    """
    Build the transformation matrix based on mapping type.

    Parameters
    ----------
    mapping : object
        The mapping node.
    entity : object
        The entity object.

    Returns
    -------
    tuple
        A tuple containing:
        - m: The main transformation matrix (4x4 for POINT, or translation matrix for TEXTURE)
        - m1: Rotation Z matrix (3x3, only for TEXTURE mapping, else None)
        - m2: Rotation Y matrix (3x3, only for TEXTURE mapping, else None)
        - m3: Rotation X matrix (3x3, only for TEXTURE mapping, else None)
        - m4: Scale matrix (3x3, only for TEXTURE mapping, else None)
        - translation: Tuple of (tx, ty, tz)
        - rotation: Tuple of (rx, ry, rz)
        - scale: Tuple of (sx, sy, sz)
    """
    translation_x = mapping.inputs[1].default_value[0]
    translation_y = mapping.inputs[1].default_value[1]
    translation_z = mapping.inputs[1].default_value[2]

    rotation_x = mapping.inputs[2].default_value[0]
    rotation_y = mapping.inputs[2].default_value[1]
    rotation_z = mapping.inputs[2].default_value[2]

    if hasattr(entity, 'enable_uniform_scale') and entity.enable_uniform_scale:
        scale_x = scale_y = scale_z = get_entity_prop_value(entity, 'uniform_scale_value')
    else:
        scale_x = mapping.inputs[3].default_value[0]
        scale_y = mapping.inputs[3].default_value[1]
        scale_z = mapping.inputs[3].default_value[2]

    m1 = m2 = m3 = m4 = None

    if mapping.vector_type == 'POINT':
        # Scale
        m = Matrix((
            (scale_x, 0, 0),
            (0, scale_y, 0),
            (0, 0, scale_z)
        ))

        # Rotate
        m.rotate(Euler((rotation_x, rotation_y, rotation_z)))

        # Translate
        m = m.to_4x4()
        m[0][3] = translation_x
        m[1][3] = translation_y
        m[2][3] = translation_z

    elif mapping.vector_type == 'TEXTURE':
        # Translate matrix
        m = Matrix((
            (1, 0, 0, -translation_x),
            (0, 1, 0, -translation_y),
            (0, 0, 1, -translation_z),
            (0, 0, 0, 1),
        ))

        # Rotate z matrix
        m1 = Matrix(((1, 0, 0), (0, 1, 0), (0, 0, 1)))
        m1.rotate(Euler((0, 0, -rotation_z)))

        # Rotate y matrix
        m2 = Matrix(((1, 0, 0), (0, 1, 0), (0, 0, 1)))
        m2.rotate(Euler((0, -rotation_y, 0)))

        # Rotate x matrix
        m3 = Matrix(((1, 0, 0), (0, 1, 0), (0, 0, 1)))
        m3.rotate(Euler((-rotation_x, 0, 0)))

        # Scale matrix
        m4 = Matrix((
            (1 / scale_x, 0, 0),
            (0, 1 / scale_y, 0),
            (0, 0, 1 / scale_z)
        ))
    else:
        m = None

    return (m, m1, m2, m3, m4,
            (translation_x, translation_y, translation_z),
            (rotation_x, rotation_y, rotation_z),
            (scale_x, scale_y, scale_z))


def apply_uv_transformation(obj, temp_uv_layer, mapping, m, m1, m2, m3, m4):
    """
    Apply UV transformation using numpy vectorized operations.

    Parameters
    ----------
    obj : bpy.types.Object
        The Blender object.
    temp_uv_layer : object
        The temporary UV layer.
    mapping : object
        The mapping node.
    m : Matrix
        The main transformation matrix.
    m1, m2, m3, m4 : Matrix or None
        Additional transformation matrices for TEXTURE mapping.
    """
    # Create numpy array to store uv coordinates
    arr = numpy.zeros(len(obj.data.loops) * 2, dtype=numpy.float32)
    temp_uv_layer.data.foreach_get('uv', arr)
    arr.shape = (arr.shape[0] // 2, 2)

    # Optimized numpy vectorized UV transformation
    # Add z=0 column for 3D transformation
    uvs_3d = numpy.column_stack([arr, numpy.zeros(len(arr), dtype=numpy.float32)])

    if mapping.vector_type == 'TEXTURE':
        # Convert matrices to numpy arrays
        m_np = numpy.array(m, dtype=numpy.float32)
        m1_np = numpy.array(m1, dtype=numpy.float32)
        m2_np = numpy.array(m2, dtype=numpy.float32)
        m3_np = numpy.array(m3, dtype=numpy.float32)
        m4_np = numpy.array(m4, dtype=numpy.float32)

        # Apply translation (4x4 matrix)
        ones = numpy.ones((len(uvs_3d), 1), dtype=numpy.float32)
        uvs_4d = numpy.column_stack([uvs_3d, ones])
        uvs_4d = uvs_4d @ m_np.T
        uvs_3d = uvs_4d[:, :3]

        # Apply rotation matrices (3x3)
        uvs_3d = uvs_3d @ m1_np.T
        uvs_3d = uvs_3d @ m2_np.T
        uvs_3d = uvs_3d @ m3_np.T
        uvs_3d = uvs_3d @ m4_np.T

        # Extract UV coordinates
        arr[:, 0] = uvs_3d[:, 0]
        arr[:, 1] = uvs_3d[:, 1]
    else:
        # POINT mapping - single 4x4 matrix
        m_np = numpy.array(m, dtype=numpy.float32)
        ones = numpy.ones((len(uvs_3d), 1), dtype=numpy.float32)
        uvs_4d = numpy.column_stack([uvs_3d, ones])
        uvs_4d = uvs_4d @ m_np.T
        arr[:, 0] = uvs_4d[:, 0]
        arr[:, 1] = uvs_4d[:, 1]

    # Set back uv coordinates
    temp_uv_layer.data.foreach_set('uv', arr.ravel())
