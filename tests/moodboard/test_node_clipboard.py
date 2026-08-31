# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Copy / paste / duplicate of moodboard inference nodes.

Exercised against a hand-rolled fake scene rather than the bpy mock: the
clipboard's whole job is to move field values and re-map link endpoints, and a
MagicMock scene would accept every assignment and assert nothing.
"""

from pathlib import Path

import pytest

from mixar.modules.moodboard.core import node_clipboard

ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"


# --------------------------------------------------------------------------- #
# Fake scene
# --------------------------------------------------------------------------- #


class _Collection(list):
    def __init__(self, factory):
        super().__init__()
        self._factory = factory

    def add(self):
        item = self._factory()
        self.append(item)
        return item

    def remove(self, index):
        del self[index]


class _Socket:
    def __init__(self):
        self.socket_id = ""
        self.label = ""
        self.accepted_types = ""
        self.required = False
        self.group_id = ""
        self.repeatable = False
        self.visible = True


class _Parameter:
    def __init__(self):
        self.name = ""
        self.label = ""
        self.description = ""
        self.parameter_type = 'STRING'
        self.widget = "text"
        self.group = ""
        self.choices_json = "[]"
        self.visible_if_json = "{}"
        self.visible = True
        self.required = False
        self.order = 0
        self.minimum = -1.0e18
        self.maximum = 1.0e18
        self.value_string = ""
        self.value_integer = 0
        self.value_float = 0.0
        self.value_boolean = False
        self.value_enum = ""
        self.value_label = ""


class _ActionNode:
    def __init__(self):
        self.node_id = ""
        self.action_type = 'IMAGE_GEN'
        self.position_x = 0.0
        self.position_y = 0.0
        self.width = 700.0
        self.height = 560.0
        self.selected = False
        self.label = ""
        self.progress_text = ""
        self.prompt = ""
        self.views_per_component = 3
        self.include_full_context = False
        self.service_key_id = ""
        self.service_label = ""
        self.model_slug = ""
        self.model_label = ""
        self.show_mode = False
        self.show_prompt = True
        self.schema_json = "{}"
        self.params_json = "{}"
        self.state = 'DRAFT'
        self.job_id = ""
        self.error = ""
        self.result_names = ""
        self.component_id = ""
        self.preview_image = None
        self.mask_preview = None
        self.preview_object = None
        self.input_sockets = _Collection(_Socket)
        self.parameters = _Collection(_Parameter)


class _Link:
    def __init__(self):
        self.link_id = ""
        self.from_node_id = ""
        self.from_socket = "output"
        self.to_node_id = ""
        self.to_socket = "input"
        self.input_order = 0
        self.selected = False


class _Scene:
    def __init__(self):
        self.mixie_moodboard_action_nodes = _Collection(_ActionNode)
        self.mixie_moodboard_asset_nodes = _Collection(_ActionNode)
        self.mixie_moodboard_links = _Collection(_Link)
        self.mixie_moodboard_images = _Collection(_ActionNode)
        self.mixie_moodboard_active_node_id = ""


# Input limits come from the catalog schema and fail CLOSED: a node whose
# schema declares none accepts no connection at all, so `reconcile_node_links`
# would strip every pasted link. Fixture nodes therefore carry the same shape a
# catalog-backed node has.
_SCHEMA_JSON = '{"inputs": {"limits": {"IMAGE": 4, "TOTAL": 4}}}'


def _add_node(scene, node_id, action_type='IMAGE_GEN', **fields):
    node = scene.mixie_moodboard_action_nodes.add()
    node.node_id = node_id
    node.action_type = action_type
    node.schema_json = _SCHEMA_JSON
    # One image input, which is what every link below lands on.
    socket = node.input_sockets.add()
    socket.socket_id = "image_0"
    socket.accepted_types = "IMAGE"
    for key, value in fields.items():
        setattr(node, key, value)
    return node


def _link(scene, from_id, to_id, to_socket="image_0"):
    link = scene.mixie_moodboard_links.add()
    link.from_node_id = from_id
    link.to_node_id = to_id
    link.to_socket = to_socket
    return link


@pytest.fixture(autouse=True)
def _empty_clipboard():
    node_clipboard.clear()
    yield
    node_clipboard.clear()


# --------------------------------------------------------------------------- #
# What travels
# --------------------------------------------------------------------------- #


def test_copy_carries_configuration_and_paste_gives_it_a_fresh_identity():
    scene = _Scene()
    source = _add_node(
        scene, "a", prompt="a wooden chair", model_slug="gemini-3-pro",
        service_key_id="image_gen", width=820.0, selected=True,
    )
    param = source.parameters.add()
    param.name = "aspect_ratio"
    param.parameter_type = 'STRING'
    param.value_string = "16:9"

    assert node_clipboard.copy_nodes(scene) == 1
    created = node_clipboard.paste_nodes(scene)

    assert len(created) == 1
    copy = created[0]
    assert copy.prompt == "a wooden chair"
    assert copy.model_slug == "gemini-3-pro"
    assert copy.service_key_id == "image_gen"
    assert copy.width == 820.0
    assert [p.value_string for p in copy.parameters] == ["16:9"]
    assert [s.socket_id for s in copy.input_sockets] == ["image_0"]
    # A new card, not a second claim on the original.
    assert copy.node_id and copy.node_id != source.node_id


def test_a_name_survives_the_round_trip_but_live_state_does_not():
    """The header name is configuration and must travel; the queue clock is
    about the original's job and would be a lie on a fresh DRAFT copy."""
    scene = _Scene()
    _add_node(scene, "a", selected=True, label="Chair hero shot",
              progress_text="Queued (#2)  0:31")

    node_clipboard.copy_nodes(scene)
    copy = node_clipboard.paste_nodes(scene)[0]

    assert copy.label == "Chair hero shot"
    assert copy.progress_text == ""


def test_a_pasted_node_never_inherits_the_originals_generation():
    """Inheriting job_id would make the copy's Cancel kill the original's job
    (node_job_bridge resolves the live job by graph_node_id), and inheriting
    state/result_names would advertise a result the copy does not own."""
    scene = _Scene()
    _add_node(
        scene, "a", selected=True, state='SUCCESS', job_id="job-123",
        result_names="chair.png", error="boom", component_id="comp-1",
        preview_image=object(),
    )

    node_clipboard.copy_nodes(scene)
    copy = node_clipboard.paste_nodes(scene)[0]

    assert copy.state == 'DRAFT'
    assert copy.job_id == ""
    assert copy.result_names == ""
    assert copy.error == ""
    assert copy.component_id == ""
    assert copy.preview_image is None


def test_mask_detail_nodes_are_not_copyable():
    """They own a packed mask datablock that is released with the node, so a
    copy would either double-free it or be unable to generate."""
    scene = _Scene()
    _add_node(scene, "m", action_type='MASK_DETAIL', selected=True)
    assert node_clipboard.selected_action_nodes(scene) == []
    assert node_clipboard.copy_nodes(scene) == 0


# --------------------------------------------------------------------------- #
# Links
# --------------------------------------------------------------------------- #


def test_links_inside_the_copied_set_are_recreated_between_the_copies():
    scene = _Scene()
    _add_node(scene, "a", selected=True)
    _add_node(scene, "b", selected=True)
    _link(scene, "a", "b")

    node_clipboard.copy_nodes(scene)
    created = node_clipboard.paste_nodes(scene)

    new_ids = {node.node_id for node in created}
    internal = [
        link for link in scene.mixie_moodboard_links
        if link.from_node_id in new_ids and link.to_node_id in new_ids
    ]
    assert len(internal) == 1
    # The originals' link is untouched.
    assert any(
        link.from_node_id == "a" and link.to_node_id == "b"
        for link in scene.mixie_moodboard_links
    )


def test_an_external_source_still_feeds_the_copy():
    """Duplicating a Generate node should keep its reference image."""
    scene = _Scene()
    _add_node(scene, "src", action_type='IMAGE_GEN')  # not selected
    _add_node(scene, "gen", selected=True)
    _link(scene, "src", "gen")

    node_clipboard.copy_nodes(scene)
    copy = node_clipboard.paste_nodes(scene)[0]

    assert any(
        link.from_node_id == "src" and link.to_node_id == copy.node_id
        for link in scene.mixie_moodboard_links
    )


def test_outgoing_links_are_not_recreated():
    """The downstream node's input already has a source; a second one would
    exceed the socket's occupancy."""
    scene = _Scene()
    _add_node(scene, "a", selected=True)
    _add_node(scene, "down")  # not selected
    _link(scene, "a", "down")

    node_clipboard.copy_nodes(scene)
    copy = node_clipboard.paste_nodes(scene)[0]

    assert not any(
        link.from_node_id == copy.node_id and link.to_node_id == "down"
        for link in scene.mixie_moodboard_links
    )


# --------------------------------------------------------------------------- #
# Placement and clipboard lifetime
# --------------------------------------------------------------------------- #


def test_paste_at_an_anchor_preserves_the_shape_of_the_selection():
    scene = _Scene()
    _add_node(scene, "a", selected=True, position_x=0.0, position_y=0.0)
    _add_node(scene, "b", selected=True, position_x=900.0, position_y=-300.0)

    node_clipboard.copy_nodes(scene)
    created = node_clipboard.paste_nodes(scene, anchor=(5000.0, 5000.0))

    dx = created[1].position_x - created[0].position_x
    dy = created[1].position_y - created[0].position_y
    assert dx == pytest.approx(900.0)
    assert dy == pytest.approx(-300.0)
    # The set's left edge lands on the anchor.
    assert min(n.position_x for n in created) == pytest.approx(5000.0)


def test_duplicate_lands_in_place_and_leaves_the_clipboard_alone():
    """The copies land ON the originals: the caller hands straight off to the
    grab modal, so they follow the mouse to wherever the user drops them --
    the same gesture a duplicated image has. A fixed offset instead left nodes
    stranded where they were dropped, unable to be placed."""
    scene = _Scene()
    _add_node(scene, "a", selected=True, position_x=100.0, position_y=100.0)
    node_clipboard.copy_nodes(scene)
    before = len(scene.mixie_moodboard_action_nodes)

    scene.mixie_moodboard_action_nodes[0].prompt = "changed after copying"
    created = node_clipboard.duplicate_selected_nodes(scene)

    assert len(scene.mixie_moodboard_action_nodes) == before + 1
    assert created[0].position_x == pytest.approx(100.0)
    assert created[0].position_y == pytest.approx(100.0)
    # Duplicating is not copying: the user's clipboard still holds the snapshot
    # taken before the edit.
    pasted = node_clipboard.paste_nodes(scene)
    assert pasted[0].prompt == ""


def test_duplicating_nodes_hands_off_to_the_grab_modal():
    """Both entry points must, or a duplicated node cannot be placed -- which
    is exactly how it differed from a duplicated image."""
    transform = (MOODBOARD / "ui/operators/transform_ops.py").read_text(
        encoding="utf-8"
    )
    ops = (MOODBOARD / "ui/operators/node_clipboard_ops.py").read_text(
        encoding="utf-8"
    )
    for source in (transform, ops):
        assert "bpy.ops.mixie.moodboard_grab('INVOKE_DEFAULT')" in source

    # And the grab modal has to know how to move a node at all.
    modal = (MOODBOARD / "ui/operators/transform_modal_ops.py").read_text(
        encoding="utf-8"
    )
    assert "'ACTION_NODE': \"mixie_moodboard_action_nodes\"" in modal
    assert "'ASSET_NODE': \"mixie_moodboard_asset_nodes\"" in modal
    assert "_selected_graph_nodes(scene)" in modal


def test_pasting_selects_the_new_nodes_and_deselects_the_originals():
    scene = _Scene()
    original = _add_node(scene, "a", selected=True)
    node_clipboard.copy_nodes(scene)
    copy = node_clipboard.paste_nodes(scene)[0]

    assert original.selected is False
    assert copy.selected is True
    assert scene.mixie_moodboard_active_node_id == copy.node_id


def test_clipboard_is_independent_of_the_original_nodes():
    """Plain dicts, not RNA pointers: deleting the originals (or switching
    scene) must not invalidate what was copied."""
    scene = _Scene()
    _add_node(scene, "a", selected=True, prompt="keep me")
    node_clipboard.copy_nodes(scene)
    scene.mixie_moodboard_action_nodes.remove(0)

    other = _Scene()
    pasted = node_clipboard.paste_nodes(other)
    assert [node.prompt for node in pasted] == ["keep me"]


def test_copying_an_image_clears_the_node_clipboard():
    """Both live on Ctrl+C/Ctrl+V and the node paste is gated on this
    clipboard, so a stale node set would hijack the next paste."""
    source = (MOODBOARD / "ui/operators/clipboard_ops.py").read_text(encoding="utf-8")
    assert "node_clipboard.clear()" in source
