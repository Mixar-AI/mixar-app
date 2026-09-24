# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The radial layout preserves the complete shared Add-menu list."""

import ast
from pathlib import Path
from types import SimpleNamespace


SOURCE = Path(__file__).parents[2] / "src/scripts/mixar/modules/moodboard/ui/moodboard_pie_menu.py"


class Layout:
    def __init__(self):
        self.entries = []
        self.columns = []
        self.separators = 0

    def mixar_surface(self, **kwargs):
        return self

    def menu_pie(self):
        return self

    def column(self):
        child = Layout()
        self.columns.append(child)
        return child

    def separator(self):
        self.separators += 1


def draw(items):
    tree = ast.parse(SOURCE.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == 'MIXIE_MT_moodboard_pie_menu')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'draw')
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    scope = {'available_templates': lambda: items,
             'draw_template': lambda layout, item: layout.entries.append(item)}
    exec(compile(module, str(SOURCE), 'exec'), scope)
    layout = Layout()
    scope['draw'](SimpleNamespace(layout=layout), None)
    return layout


def test_every_add_entry_is_reachable_when_catalog_exceeds_eight_slots():
    items = list(range(10))
    layout = draw(items)
    assert layout.operator_context == 'INVOKE_DEFAULT'
    assert layout.entries == items[:7]
    assert len(layout.columns) == 1
    assert layout.columns[0].entries == items[7:]


def test_sparse_catalog_has_no_old_popup_or_disabled_entries():
    for count in (1, 3, 7, 8):
        items = list(range(count))
        layout = draw(items)
        assert layout.entries + [entry for child in layout.columns
                                 for entry in child.entries] == items
        assert len(layout.entries) + len(layout.columns) + layout.separators == 8
    assert '_popup' not in SOURCE.read_text()
