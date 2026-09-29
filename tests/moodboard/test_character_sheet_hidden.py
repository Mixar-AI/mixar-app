# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Character Sheet to 3D template ships hidden: offered nowhere, created never.

The catalog below is rich enough for the workflow to wire, so the withdrawal is
the only reason the template is missing. The catalog gate itself is pinned in
``test_character_sheet_catalog.py`` with the withdrawal lifted.
"""

from pathlib import Path

import pytest

from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.modules.moodboard.core import node_templates
from mixar.modules.moodboard.core.canvas_template_fit import canvas_template_strip_items
from mixar.modules.moodboard.core.character_sheet_catalog import preflight
from mixar.modules.moodboard.core.workflow_templates import WORKFLOW_TEMPLATES

TEMPLATE = 'CHARACTER_SHEET_3D'
UI = Path(__file__).resolve().parents[2] / "src/scripts/mixar/modules/moodboard/ui"


def _capability(key, service_key, models, **service):
    record = {'key': service_key, 'surface': 'moodboard', 'models': models}
    record.update(service)
    return {'key': key, 'services': [record]}


def _ids(items):
    return {item[0] for item in items}


@pytest.fixture
def rich_catalog(monkeypatch):
    """Everything the workflow needs, Auto Rig included."""
    references = {'inputs': [{'kind': 'image', 'name': 'reference_images', 'multiple': True}]}
    monkeypatch.setattr(catalog, '_catalog', {'capabilities': [
        _capability('image_gen', 'image_gen', [{'slug': 'qa', 'max_reference_images': 4}],
                    input_spec=references),
        _capability('model_gen', 'image_to_3d', [{'slug': 'qa3d'}],
                    input_spec={'inputs': [{'kind': 'image', 'name': 'image'}]}),
        _capability('animate', 'animate', [{'slug': 'rig'}]),
    ]})
    # Without the withdrawal this catalog would offer the workflow.
    assert preflight() is not None


def test_the_template_ships_hidden():
    assert WORKFLOW_TEMPLATES[TEMPLATE]['hidden'] is True


def test_no_add_surface_lists_it(rich_catalog):
    assert not node_templates.template_available(TEMPLATE)
    offered = node_templates.available_templates()
    assert TEMPLATE not in _ids(offered)
    assert TEMPLATE not in _ids(canvas_template_strip_items(offered))
    # The withdrawal is scoped to this template: its members stay offered.
    assert {'IMAGE_GEN', 'MODEL_3D', 'AUTO_RIG'} <= _ids(offered)


def test_creation_is_refused_before_the_board_is_read(rich_catalog):
    # A None scene proves the refusal happens up front: past the gate the
    # builder would fail on the scene with something other than ValueError.
    with pytest.raises(ValueError):
        node_templates.create_template(None, TEMPLATE, (0, 0))


def test_lifting_the_flag_offers_it_again(rich_catalog, monkeypatch):
    monkeypatch.setitem(WORKFLOW_TEMPLATES[TEMPLATE], 'hidden', False)
    assert node_templates.template_available(TEMPLATE)
    assert TEMPLATE in _ids(node_templates.available_templates())


def test_no_surface_draws_the_unfiltered_registry():
    """One gate hides the template everywhere only while every surface asks it.

    Nothing under ui/ may draw entries from the raw ``NODE_TEMPLATES`` registry
    (its operator enum is the one place that must list all of them), nor call
    ``canvas_template_strip_items()`` without the available entries, whose
    default is that registry.
    """
    sources = {path.relative_to(UI).as_posix(): path.read_text(encoding="utf-8")
               for path in UI.rglob("*.py")}
    assert sorted(name for name, text in sources.items() if "NODE_TEMPLATES" in text) == [
        "operators/node_template_ops.py",
    ]
    assert [name for name, text in sources.items()
            if "canvas_template_strip_items()" in text] == []
