# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute the real operator method without importing Blender's UI classes.

Real EXR pixel read-back is covered by the QAP-049 QA replay.
"""
import ast
import os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/paint/ui/image_ops/image_ops_save.py'


def execute_image(image, file_format):
    module = ast.parse(SOURCE.read_text())
    operator = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == 'MSaveAllBakedImages')
    method = next(n for n in operator.body if isinstance(n, ast.FunctionDef) and n.name == 'execute')
    tree = NS(mp=NS(channels=[], bake_targets=[NS(image_node='mask')]),
              nodes={'mask': NS(image=image)})
    scene = NS(render=NS(image_settings=NS()), view_settings=NS())
    namespace = dict(
        os=os, bpy=NS(data=NS(scenes=NS(new=lambda _: scene), filepath='')),
        get_active_mpaint_node=lambda: NS(node_tree=tree),
        get_root_height_channel=lambda _: None,
        get_addon_title=lambda: 'Mixar', get_srgb_name=lambda: 'sRGB',
        format_extensions={'OPEN_EXR': '.exr', 'PNG': '.png', 'TIFF': '.tif'},
        remove_datablock=Mock(), pack_image=Mock(),
    )
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['execute'](NS(copy=False, file_format=file_format,
                                  force_exr_vdisp=False, remove_whitespaces=False,
                                  directory='/export'), None)


@pytest.mark.parametrize('file_format', ['OPEN_EXR', 'PNG', 'TIFF'])
@pytest.mark.parametrize('space,is_data', [('Non-Color', True), ('Raw', True),
                                         ('Custom Data', True), ('Linear Rec.709', False),
                                         ('sRGB', False)])
@pytest.mark.parametrize('is_float', [False, True])
@pytest.mark.parametrize('failure', [False, True])
def test_save_colorspace_and_restoration(file_format, space, is_data, is_float, failure):
    image = NS(name='Mask', filepath='', is_float=is_float, is_dirty=False,
               packed_file=None, colorspace_settings=NS(name=space, is_data=is_data))
    seen = []

    def save_render(path, scene):
        seen.append(image.colorspace_settings.name)
        assert scene.render.image_settings.file_format == file_format
        if failure:
            raise RuntimeError('disk write failed')

    image.save_render = save_render
    if failure:
        with pytest.raises(RuntimeError, match='disk write failed'):
            execute_image(image, file_format)
    else:
        assert execute_image(image, file_format) == {'FINISHED'}
    expected = space if is_float or (file_format == 'OPEN_EXR' and is_data) else 'sRGB'
    assert seen == [expected]
    assert image.colorspace_settings.name == space
