# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Character Sheet to 3D builder: one framed, all-draft graph or nothing.

The real graph helpers run against in-memory collections; only the catalog
edge (schema sync, model selection, preflight) is replaced, minting sockets
from a fixed contract per card type.
"""

import json
from types import SimpleNamespace as NS

import pytest

from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.modules.moodboard.constants import FRAME_NAME_MAXLEN
from mixar.modules.moodboard.core import character_sheet_workflow as workflow
from mixar.modules.moodboard.core import node_graph, node_templates
from mixar.modules.moodboard.core.assemble_constants import (
    BODY_SOCKET,
    PARAM_KINDS,
    PART_GROUP,
    PART_SOCKET_COUNT,
    param_name,
    part_socket,
)
from mixar.modules.moodboard.core.asset_nodes import find_free_asset_position
from mixar.modules.moodboard.core.character_sheet_catalog import Preflight
from mixar.modules.moodboard.core.character_sheet_workflow_spec import (
    LANES,
    NOTE_MAX_BYTES,
    note_text,
)
from mixar.modules.moodboard.core.frames import item_rect


class Collection(list):
    def __init__(self, factory):
        super().__init__()
        self.factory = factory

    def add(self):
        item = self.factory()
        self.append(item)
        return item

    def remove(self, index):
        del self[index]

    def clear(self):
        del self[:]


def _socket():
    return NS(socket_id='', label='', accepted_types='', required=False,
              group_id='', repeatable=False, visible=True)


def _parameter():
    return NS(name='', parameter_type='STRING', choices_json='[]', value_integer=0,
              value_enum='', value_float=0.0, value_boolean=False, visible=True)


def _action_node():
    return NS(node_id='', action_type='IMAGE_GEN', width=700., height=560., position_x=0.,
              position_y=0., selected=False, frame_id='', label='', prompt='',
              requires_reference=False, state='DRAFT', job_id='', preview_image=None,
              mask_preview=None, preview_object=None, result_names='', schema_json='',
              service_key_id='', model_slug='', input_sockets=Collection(_socket),
              parameters=Collection(_parameter))


def _scene():
    return NS(
        name='Scene',
        mixie_moodboard_images=[],
        mixie_moodboard_action_nodes=Collection(_action_node),
        mixie_moodboard_asset_nodes=[],
        mixie_moodboard_links=Collection(lambda: NS(
            link_id='', from_node_id='', to_node_id='', from_socket='', to_socket='',
            input_order=0, selected=False)),
        mixie_moodboard_textboxes=Collection(lambda: NS(
            text='', font_size=48, width=400., height=100., position_x=0., position_y=0.,
            z_order=0, selected=False, frame_id='')),
        mixie_moodboard_frames=Collection(lambda: NS(
            frame_id='', name='', position_x=0., position_y=0., width=0., height=0.,
            palette_index=0, selected=False, collapsed=False)),
        mixie_moodboard_active_node_id='',
        mixie_moodboard_context_x=0.,
        mixie_moodboard_context_y=0.,
    )


def _sheet(scene, node_id, name, x=0., y=0., selected=False):
    item = NS(node_id=node_id, image=NS(size=(100, 80), source='FILE', name=name),
              scale=1.0, position_x=x, position_y=y, selected=selected,
              embedded_node_id='', frame_id='')
    scene.mixie_moodboard_images.append(item)
    return item


def _sockets(action_type):
    if action_type == 'IMAGE_GEN':
        return [(f"reference_images:{i}", 'IMAGE', 'reference_images', True) for i in range(4)]
    if action_type == 'MODEL_3D':
        return [('image', 'IMAGE', 'image', False)]
    if action_type == 'AUTO_RIG':
        return [('mesh', 'MESH', 'mesh', False)]
    if action_type == 'ASSEMBLE':
        return [(BODY_SOCKET, 'MESH', BODY_SOCKET, False)] + [
            (part_socket(i), 'MESH', PART_GROUP, True) for i in range(PART_SOCKET_COUNT)]
    return []


def _parameters(action_type, count_kind):
    if action_type == 'IMAGE_GEN':
        choices = [{'value': v, 'label': v} for v in ('1', '2', '4')]
        return [('number_of_images', count_kind, choices if count_kind == 'ENUM' else [])]
    if action_type == 'ASSEMBLE':
        kinds = {'slot': 'ENUM', 'hold': 'ENUM', 'size': 'FLOAT', 'flip': 'BOOLEAN'}
        return [(param_name(kind, i), kinds[kind], [])
                for i in range(PART_SOCKET_COUNT) for kind in PARAM_KINDS]
    return []


@pytest.fixture
def board(monkeypatch):
    """A fixture catalog edge; returns a namespace of the build's knobs."""
    knobs = NS(image_sockets=4, has_rig=True, count_kind='INTEGER', notices=[],
               selections=[])

    def sync(scene, node):
        limits = {}
        for _id, kind, _group, _repeat in _sockets(node.action_type):
            limits[kind] = limits.get(kind, 0) + 1
        schema = json.dumps({'type': node.action_type, 'inputs': {'limits': limits}})
        if node.schema_json == schema:
            return
        node.schema_json = schema
        node.input_sockets.clear()
        for socket_id, kind, group, repeatable in _sockets(node.action_type):
            socket = node.input_sockets.add()
            socket.socket_id, socket.accepted_types = socket_id, kind
            socket.group_id, socket.repeatable = group, repeatable
        node.parameters.clear()
        for name, kind, choices in _parameters(node.action_type, knobs.count_kind):
            parameter = node.parameters.add()
            parameter.name, parameter.parameter_type = name, kind
            parameter.choices_json = json.dumps(choices)
            parameter.value_integer, parameter.value_enum = 2, ('2' if choices else 'AUTO')

    def select(node, service, model):
        knobs.selections.append((node.action_type, service, model))
        node.service_key_id, node.model_slug = service, model

    monkeypatch.setattr(node_graph, '_initialize_catalog_selection', sync)
    monkeypatch.setattr(workflow, 'sync_node_schema', sync)
    monkeypatch.setattr(workflow, 'set_node_selection', select)
    monkeypatch.setattr(workflow, 'refresh_node_parameter_visibility', lambda node: None)
    monkeypatch.setattr(workflow, 'preflight', lambda: Preflight(
        'qa', knobs.image_sockets, 'image_to_3d', 'qa3d'))
    monkeypatch.setattr(workflow, 'template_available', lambda key: knobs.has_rig)
    monkeypatch.setattr(workflow, 'post_graph_notice',
                        lambda scene, message, near='': knobs.notices.append((message, near)))
    monkeypatch.setattr(workflow, 'find_free_asset_position',
                        lambda scene, x, y, w, h, **kw: (x - w / 2, y - h / 2))
    monkeypatch.setattr(catalog, 'get_service', lambda key: {
        'input_spec': {'cost_multiplier_param': 'number_of_images'}})
    monkeypatch.setattr(node_templates, 'template_available', lambda key: True)
    return knobs


def _cards(scene, action_type):
    return [n for n in scene.mixie_moodboard_action_nodes if n.action_type == action_type]


def _links(scene):
    return {(l.from_node_id, l.to_node_id, l.to_socket) for l in scene.mixie_moodboard_links}


def _state(scene):
    return {
        'nodes': [n.node_id for n in scene.mixie_moodboard_action_nodes],
        'links': sorted(_links(scene)),
        'boxes': len(scene.mixie_moodboard_textboxes),
        'frames': [f.frame_id for f in scene.mixie_moodboard_frames],
        'selected': [i.selected for i in scene.mixie_moodboard_images]
        + [n.selected for n in scene.mixie_moodboard_action_nodes],
        'active': scene.mixie_moodboard_active_node_id,
    }


def test_drop_on_a_sheet_builds_the_whole_framed_draft_graph(board):
    scene = _scene()
    sheet = _sheet(scene, 'sheet', 'Warrior Sheet', x=0., y=0.)
    frame = node_templates.create_template(scene, 'CHARACTER_SHEET_3D', (350, 280),
                                           exact_position=True)
    refs, m3d = _cards(scene, 'IMAGE_GEN'), _cards(scene, 'MODEL_3D')
    (rig,), (assemble,) = _cards(scene, 'AUTO_RIG'), _cards(scene, 'ASSEMBLE')
    assert (len(refs), len(m3d), len(scene.mixie_moodboard_textboxes)) == (3, 3, 1)
    assert len(scene.mixie_moodboard_frames) == 1
    assert [n.label for n in refs] == [label for _key, label, _prompt in LANES]
    assert all(n.prompt.startswith(n.label) and '\n' not in n.prompt for n in refs)
    assert all(n.requires_reference for n in refs)
    assert all(n.parameters[0].value_integer == 1 for n in refs)
    assert [n.label for n in m3d] == [''] * 3
    assert (rig.label, assemble.label) == ("Rig Body", "Assemble")
    assert all(n.state == 'DRAFT' and not n.job_id for n in scene.mixie_moodboard_action_nodes)
    assert all(sel[1:] == ('image_gen', 'qa') for sel in board.selections[:3])
    assert all(sel[1:] == ('image_to_3d', 'qa3d') for sel in board.selections[3:6])

    links = _links(scene)
    assert {(sheet.node_id, n.node_id, 'reference_images:0') for n in refs} <= links
    assert {(r.node_id, m.node_id, 'image') for r, m in zip(refs, m3d)} <= links
    assert (m3d[0].node_id, rig.node_id, 'mesh') in links
    assert (rig.node_id, assemble.node_id, BODY_SOCKET) in links
    assert (m3d[1].node_id, assemble.node_id, part_socket(0)) in links
    assert (m3d[2].node_id, assemble.node_id, part_socket(1)) in links
    assert len(links) == 3 + 3 + 1 + 3
    slots = {p.name: p.value_enum for p in assemble.parameters}
    assert (slots['slot:0'], slots['slot:1'], slots['slot:2']) == ('HAND_R', 'HAND_L', 'AUTO')

    # The sheet stays where it was, outside the frame; every card and the note
    # are inside it, and the frame alone is selected.
    assert (sheet.position_x, sheet.position_y, sheet.frame_id) == (0., 0., '')
    members = list(scene.mixie_moodboard_action_nodes) + list(scene.mixie_moodboard_textboxes)
    assert all(item.frame_id == frame.frame_id for item in members)
    assert frame.name == "Warrior Sheet to 3D"
    assert frame.position_x > sheet.position_x + 700.
    assert frame.selected and not sheet.selected
    assert not any(n.selected for n in scene.mixie_moodboard_action_nodes)
    assert scene.mixie_moodboard_active_node_id == ''
    assert board.notices == [(workflow.NOTICE, refs[0].node_id)]
    assert scene.mixie_moodboard_textboxes[0].text == note_text(has_sheet=True, has_rig=True)


def test_selected_stills_are_the_sheet_and_the_count_enum_is_pinned(board):
    board.count_kind = 'ENUM'
    scene = _scene()
    first = _sheet(scene, 'front', 'Front', selected=True)
    second = _sheet(scene, 'back', 'Back', x=900., selected=True)
    workflow.build_character_sheet_workflow(
        scene, sources=workflow.resolve_sheet_sources(scene, (0, 0), False, ''), center=(0, 0))
    refs = _cards(scene, 'IMAGE_GEN')
    links = _links(scene)
    for node in refs:
        assert (first.node_id, node.node_id, 'reference_images:0') in links
        assert (second.node_id, node.node_id, 'reference_images:1') in links
        assert node.parameters[0].value_enum == '1'
    assert not first.selected and not second.selected
    assert scene.mixie_moodboard_frames[0].name == "Front to 3D"


class Reallocating(Collection):
    """``.add()`` moves every item, as RNA does: old references go empty."""

    def add(self):
        for index, old in enumerate(self):
            self[index] = NS(**vars(old))
            old.__dict__.clear()
        return super().add()


def test_a_generate_image_card_as_the_sheet_is_read_by_id(board):
    scene = _scene()
    scene.mixie_moodboard_action_nodes = Reallocating(_action_node)
    card = scene.mixie_moodboard_action_nodes.add()
    card.node_id, card.label = 'card', 'Hero'
    card.preview_image = NS(name='Hero Render', size=(100, 80), source='FILE')
    sources = workflow.resolve_sheet_sources(scene, (0, 0), False, 'card')
    assert sources == [card]
    frame = workflow.build_character_sheet_workflow(scene, sources=sources, center=(0, 0))
    refs = _cards(scene, 'IMAGE_GEN')[1:]
    assert all(('card', n.node_id, 'reference_images:0') in _links(scene) for n in refs)
    assert frame.name == "Hero Render to 3D"
    assert frame.position_x > 700.


def _rects_overlap(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def test_the_frame_clears_every_still_and_card_beside_the_sheet(board, monkeypatch):
    monkeypatch.setattr(workflow, 'find_free_asset_position', find_free_asset_position)
    scene = _scene()
    _sheet(scene, 'front', 'Front', selected=True)
    _sheet(scene, 'back', 'Back', x=900., selected=True)
    later = scene.mixie_moodboard_action_nodes.add()
    later.node_id, later.position_x, later.position_y = 'later', 1400., -200.
    others = [item_rect(item) for item in scene.mixie_moodboard_images] + [item_rect(later)]
    frame = workflow.build_character_sheet_workflow(
        scene, sources=workflow.resolve_sheet_sources(scene, (0, 0), False, ''), center=(0, 0))
    rect = (frame.position_x, frame.position_y,
            frame.position_x + frame.width, frame.position_y + frame.height)
    assert not any(_rects_overlap(rect, other) for other in others)
    assert later.frame_id == '' and rect[0] > others[-1][2]


def test_a_multibyte_sheet_name_fits_the_frame_name_in_bytes(board):
    scene = _scene()
    sheet = _sheet(scene, 'sheet', '\u5263' * 60)
    names = [
        workflow.build_character_sheet_workflow(scene, sources=[sheet], center=(0, 0)).name
        for _run in range(2)
    ]
    assert all(len(name.encode('utf-8')) < FRAME_NAME_MAXLEN for name in names)
    assert names[0].endswith(" to 3D") and names[1] == names[0] + " 1"


def test_without_a_sheet_the_note_asks_for_one_and_space_is_found(board):
    scene = _scene()
    frame = workflow.build_character_sheet_workflow(scene, sources=[], center=(5000, 0))
    assert frame.name == "Character Sheet to 3D"
    assert not any(l.to_socket.startswith('reference_images') for l in scene.mixie_moodboard_links)
    text = scene.mixie_moodboard_textboxes[0].text
    assert text.startswith(workflow.note_text(has_sheet=False, has_rig=True)[:40])
    assert "character sheet" in text.split('.')[0]
    assert frame.position_x < 5000 < frame.position_x + frame.width


def test_explicit_source_wins_and_the_frame_name_is_unique(board):
    scene = _scene()
    _sheet(scene, 'selected', 'Selected', selected=True)
    _sheet(scene, 'chosen', 'Chosen', x=2000.)
    existing = scene.mixie_moodboard_frames.add()
    existing.frame_id, existing.name = 'old', "Chosen to 3D"
    sources = workflow.resolve_sheet_sources(scene, (0, 0), False, 'chosen')
    assert [item.node_id for item in sources] == ['chosen']
    frame = workflow.build_character_sheet_workflow(scene, sources=sources, center=(0, 0))
    assert frame.name == "Chosen to 3D 1"


def test_without_auto_rig_the_body_3d_card_feeds_assemble(board):
    board.has_rig = False
    scene = _scene()
    workflow.build_character_sheet_workflow(scene, sources=[], center=(0, 0))
    assert not _cards(scene, 'AUTO_RIG')
    body, (assemble,) = _cards(scene, 'MODEL_3D')[0], _cards(scene, 'ASSEMBLE')
    assert (body.node_id, assemble.node_id, BODY_SOCKET) in _links(scene)
    assert "Auto Rig is unavailable" in scene.mixie_moodboard_textboxes[0].text


def test_too_many_stills_are_refused_before_any_mutation(board):
    board.image_sockets = 1
    scene = _scene()
    _sheet(scene, 'a', 'A', selected=True)
    _sheet(scene, 'b', 'B', x=900., selected=True)
    before = _state(scene)
    sources = workflow.resolve_sheet_sources(scene, (0, 0), False, '')
    with pytest.raises(ValueError, match='at most 1 reference images'):
        workflow.build_character_sheet_workflow(scene, sources=sources, center=(0, 0))
    assert _state(scene) == before


def test_unwirable_catalog_is_refused(board, monkeypatch):
    monkeypatch.setattr(workflow, 'preflight', lambda: None)
    with pytest.raises(ValueError, match='accepts references'):
        workflow.build_character_sheet_workflow(_scene(), sources=[], center=(0, 0))


def _fail_on(monkeypatch, name, call):
    original = getattr(workflow, name)
    calls = []

    def failing(*args, **kwargs):
        calls.append(1)
        if len(calls) == call:
            raise RuntimeError(f"{name} failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow, name, failing)


@pytest.mark.parametrize('name, call', [
    ('create_connected_action', 1), ('create_connected_action', 5),
    ('create_connected_action', 7), ('create_connected_action', 8),
    ('sync_node_schema', 2), ('sync_node_schema', 6), ('connect_nodes', 1),
    ('connect_nodes', 4), ('connect_nodes', 7), ('connect_nodes', 9),
    ('create_frame', 1), ('select_frame', 1), ('post_graph_notice', 1),
])
def test_any_failure_rolls_the_whole_build_back(board, monkeypatch, name, call):
    scene = _scene()
    sheet = _sheet(scene, 'sheet', 'Sheet', selected=True)
    kept = scene.mixie_moodboard_action_nodes.add()
    kept.node_id, kept.selected = 'kept', True
    scene.mixie_moodboard_active_node_id = 'kept'
    before = _state(scene)
    _fail_on(monkeypatch, name, call)
    with pytest.raises(ValueError, match='failed'):
        workflow.build_character_sheet_workflow(scene, sources=[sheet], center=(0, 0))
    assert _state(scene) == before
    assert sheet.frame_id == ''


def test_a_card_that_fails_after_its_add_is_rolled_back(board, monkeypatch):
    sync, calls = node_graph._initialize_catalog_selection, []

    def failing(scene, node):
        calls.append(node.action_type)
        if node.action_type == 'MODEL_3D':
            raise RuntimeError("schema failed")
        sync(scene, node)

    monkeypatch.setattr(node_graph, '_initialize_catalog_selection', failing)
    scene = _scene()
    with pytest.raises(ValueError, match='schema failed'):
        workflow.build_character_sheet_workflow(scene, sources=[], center=(0, 0))
    assert 'MODEL_3D' in calls
    assert not scene.mixie_moodboard_action_nodes and not scene.mixie_moodboard_links


class _BrokenNote(NS):
    @property
    def font_size(self):
        return 0

    @font_size.setter
    def font_size(self, value):
        raise RuntimeError("note write failed")


def test_a_note_that_fails_after_its_add_is_rolled_back(board):
    scene = _scene()
    scene.mixie_moodboard_textboxes = Collection(lambda: _BrokenNote(
        text='', width=0., height=0., position_x=0., position_y=0., z_order=0,
        selected=False, frame_id=''))
    with pytest.raises(ValueError, match='note write failed'):
        workflow.build_character_sheet_workflow(scene, sources=[], center=(0, 0))
    assert not scene.mixie_moodboard_textboxes and not scene.mixie_moodboard_action_nodes


def test_a_type_error_surfaces_as_a_value_error(board, monkeypatch):
    def broken(scene, node):
        raise TypeError("bad catalog")

    monkeypatch.setattr(workflow, 'sync_node_schema', broken)
    scene = _scene()
    with pytest.raises(ValueError, match='bad catalog'):
        workflow.build_character_sheet_workflow(scene, sources=[], center=(0, 0))
    assert not scene.mixie_moodboard_action_nodes and not scene.mixie_moodboard_links


def test_prompts_and_notes_fit_their_fields():
    for _key, label, prompt in LANES:
        assert '\n' not in prompt and prompt.startswith(label)
        assert "no people" not in prompt.lower()
    for has_sheet in (True, False):
        for has_rig in (True, False):
            text = note_text(has_sheet=has_sheet, has_rig=has_rig)
            assert len(text.encode('utf-8')) <= NOTE_MAX_BYTES and '\n' not in text
            assert f"runs {6 + has_rig} jobs" in text
