# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Creation metadata must be readable without fabricating legacy dates."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mixar.modules.moodboard.core.media_utils import moodboard_added_time

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / 'src/scripts/mixar/modules/moodboard/ui'


@pytest.mark.parametrize('value, expected', [
    ('2026-11-06T09:04:03.123456+00:00', '2026-11-06 09:04:03 UTC'),
    ('2026-11-06T10:04:03+01:00', '2026-11-06 09:04:03 UTC'),
    ('2026-11-06T09:04:03Z', '2026-11-06 09:04:03 UTC'),
    ('', ''), ('not a date', ''), (None, ''),
    ('2026-11-06T09:04:03', ''),
])
def test_timestamp_display(value, expected):
    item = SimpleNamespace(mixar_created_at_iso=value)
    assert moodboard_added_time(item) == expected
    assert item.mixar_created_at_iso == value


def test_missing_legacy_property():
    assert moodboard_added_time(SimpleNamespace()) == ''


@pytest.mark.parametrize('values, expected', [
    (['2026-11-06T09:04:03+00:00'], 'Added: 2026-11-06 09:04:03 UTC'),
    ([''], 'Added: Unknown'), ([], None), (['', ''], None),
])
def test_menu_displays_selected_result_time(values, expected):
    # Execute the real draw prefix: Blender's mocked Menu base cannot be instantiated.
    tree = ast.parse((UI / 'moodboard_menus.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    draw = next(n for n in cls.body if isinstance(n, ast.FunctionDef))
    branch = next(n for n in draw.body if isinstance(n, ast.If)
                  and ast.unparse(n.test) == 'len(exportable_media) == 1')
    layout = Mock()
    namespace = dict(layout=layout, iface_=lambda text: text,
                     moodboard_added_time=moodboard_added_time,
                     exportable_media=[SimpleNamespace(mixar_created_at_iso=v) for v in values])
    exec(compile(ast.Module(body=[branch], type_ignores=[]), '<menu>', 'exec'), namespace)
    if expected is None:
        layout.label.assert_not_called()
    else:
        layout.label.assert_called_once_with(text=expected, translate=False, icon='TIME')


def test_generated_result_uses_own_timestamp_not_its_node_or_selection():
    from mixar.modules.moodboard.core.media_utils import selected_exportable_media

    output = SimpleNamespace(image=object(), selected=False, embedded_node_id='node',
                             mixar_created_at_iso='2026-11-06T09:04:03+00:00')
    older = SimpleNamespace(image=object(), selected=False, embedded_node_id='',
                            mixar_created_at_iso='2026-11-05T09:04:03+00:00')
    scene = SimpleNamespace(mixie_moodboard_images=[older, output],
                            mixie_moodboard_action_nodes=[
                                SimpleNamespace(node_id='node', selected=True)])
    selected = selected_exportable_media(scene)
    assert selected == [output]
    assert moodboard_added_time(selected[0]) == '2026-11-06 09:04:03 UTC'
