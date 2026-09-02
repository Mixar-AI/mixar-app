# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`View Queue` lands on the agent island's Queue tab.

The toast's action button is the main way the queue is opened, and the island
is where the user is already watching the status pill tick — the sidebar
panel stays as the fallback for builds/platforms without the island.
"""

import ast
from pathlib import Path

SRC = (
    Path(__file__).resolve().parents[1]
    / "src/scripts/mixar/modules/common/job_queue/ui/operators/queue_ops.py"
)
SOURCE = SRC.read_text()
TREE = ast.parse(SOURCE)


def _func(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _queue_view_execute() -> ast.FunctionDef:
    for node in TREE.body:
        if isinstance(node, ast.ClassDef) and node.name == "MIXIE_OT_queue_view":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "execute":
                    return item
    raise AssertionError("MIXIE_OT_queue_view.execute not found")


def test_the_island_is_tried_before_the_sidebar():
    body = _queue_view_execute().body
    assert isinstance(body[0], ast.If)
    assert "_show_island_queue_tab" in ast.dump(body[0].test)


def test_the_sidebar_remains_the_fallback():
    """A build without the spacetype, or a platform whose window controls are
    stubbed, must still get somewhere."""
    src = ast.get_source_segment(SOURCE, _queue_view_execute())
    assert "find_largest_queue_area" in src
    assert "active_panel_category" in src


def test_the_tab_is_set_after_the_window_opens():
    """The open path restores from the pill; a tab set first is repainted
    before the window is on screen."""
    src = ast.get_source_segment(SOURCE, _func("_show_island_queue_tab"))
    assert src.index("agent_bubble_open_window") < src.index("mixar_bubble_tab = 'QUEUE'")


def test_it_reaches_the_island_without_importing_it():
    """`common/` must not depend on a feature module; the tab is plain RNA
    and opening is a plain operator call."""
    fn = _func("_show_island_queue_tab")
    imported = [
        name.name
        for node in ast.walk(fn)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name in node.names
    ] + [
        node.module
        for node in ast.walk(fn)
        if isinstance(node, ast.ImportFrom) and node.module
    ]
    assert not any("agent_bubble" in mod for mod in imported), imported
    assert not any("mixar.modules" in mod for mod in imported), imported
