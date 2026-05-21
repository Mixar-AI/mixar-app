# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ....core.material.get_materials import get_all_objects_with_same_materials
from ....utils.blender_commons import get_active_material, get_user_preferences
from ....utils.classes import dotdict
from ...udim.udim_utils import is_uvmap_udim


def update_bake_to_layer_uv_map(self, context):
    """Update UDIM detection when UV map changes.

    Args:
        self: Operator instance with UV map properties.
        context: Blender context.
    """

    if get_user_preferences().enable_auto_udim_detection:
        mat = get_active_material()
        objs = get_all_objects_with_same_materials(mat)
        self.use_udim = is_uvmap_udim(objs, self.uv_map)


def get_bake_properties_from_self(self):
    """Extract bake properties from operator instance.

    Args:
        self: Operator instance with bake properties.

    Returns:
        dotdict: Dictionary containing all bake properties from the operator.
    """

    bprops = dotdict()

    # NOTE: Getting props from keys doesn't work
    # for prop in self.properties.keys():
    #    try: bprops[prop] = getattr(self, prop)
    #    except Exception as e: print(e)

    props = [
        "bake_device",
        "samples",
        "margin",
        "margin_type",
        "width",
        "height",
        "image_resolution",
        "use_custom_resolution",
        "name",
        "uv_map",
        "uv_map_1",
        "interpolation",
        "type",
        "use_cage",
        "cage_object_name",
        "cage_extrusion",
        "max_ray_distance",
        "normalize",
        "ao_distance",
        "bevel_samples",
        "bevel_radius",
        "multires_base",
        "target_type",
        "fxaa",
        "ssaa",
        "denoise",
        "channel_idx",
        "blend_type",
        "normal_blend_type",
        "normal_map_type",
        "hdr",
        "use_baked_disp",
        "flip_normals",
        "only_local",
        "subsurf_influence",
        "force_bake_all_polygons",
        "use_image_atlas",
        "use_udim",
        "blur",
        "blur_type",
        "blur_factor",
        "blur_size",
    ]

    for prop in props:
        if hasattr(self, prop):
            bprops[prop] = getattr(self, prop)

    return bprops
