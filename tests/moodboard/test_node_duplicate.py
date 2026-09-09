# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Duplicating moodboard inference nodes.

Exercised against a hand-rolled fake scene rather than the bpy mock: the
snapshot's whole job is to move field values and re-map link endpoints, and a
MagicMock scene would accept every assignment and assert nothing.

There is no node clipboard -- Ctrl/Cmd+C and +V belong to the board's media --
so a duplicate is a snapshot taken and re-materialised in one breath.
"""

from pathlib import Path

import pytest

from mixar.modules.moodboard.core import node_duplicate

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


class _Image:
    """Stand-in for a bpy Image datablock: the clipboard only reads `.name`."""

    def __init__(self, name):
        self.name = name


class _MediaItem:
    """A `mixie_moodboard_images` entry."""

    def __init__(self):
        self.node_id = ""
        self.embedded_node_id = ""
        self.image = None
        self.selected = False
        self.scale = 1.0
        self.rotation = 0.0
        self.flip_horizontal = False
        self.flip_vertical = False
        self.generation_prompt = ""
        self.component_role = ""
        self.component_name = ""
        self.mixar_created_at_iso = ""


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
        self.mixie_moodboard_images = _Collection(_MediaItem)
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

    payload = node_duplicate.snapshot_selected(scene)
    assert len(payload["nodes"]) == 1
    created = node_duplicate.paste_snapshot(scene, payload)

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

    payload = node_duplicate.snapshot_selected(scene)
    copy = node_duplicate.paste_snapshot(scene, payload)[0]

    assert copy.label == "Chair hero shot"
    assert copy.progress_text == ""


def _finished_node(scene, node_id, image_name="chair.png", **fields):
    """A node that has generated `image_name`, with the board entry to match."""
    image = _Image(image_name)
    node = _add_node(
        scene, node_id, selected=True, state='SUCCESS',
        result_names=image_name, preview_image=image, **fields
    )
    item = scene.mixie_moodboard_images.add()
    item.image = image
    item.embedded_node_id = node_id
    item.node_id = f"media-{node_id}"
    return node, image, item


@pytest.fixture
def image_library(monkeypatch):
    """Back `bpy.data.images.get` with a real dict.

    The suite's `bpy` is a MagicMock, so an unpatched `.get()` hands back a
    MagicMock for ANY name -- the paste would appear to resolve a datablock
    that does not exist, and the deleted-original branch could never be
    exercised.
    """
    import bpy

    library = {}
    monkeypatch.setattr(bpy.data, "images", library, raising=False)
    return library


def test_a_pasted_node_never_inherits_the_originals_queue_job():
    """Inheriting job_id would make the copy's Cancel kill the original's job --
    node_job_bridge resolves the live job by graph_node_id -- and progress_text
    is that job's live clock, which the copy has no business advertising."""
    scene = _Scene()
    _add_node(
        scene, "a", selected=True, state='RUNNING', job_id="job-123",
        progress_text="Processing  0:42", component_id="comp-1",
    )

    payload = node_duplicate.snapshot_selected(scene)
    copy = node_duplicate.paste_snapshot(scene, payload)[0]

    assert copy.job_id == ""
    assert copy.progress_text == ""
    assert copy.component_id == ""
    # Running work has no result yet, so the copy is a plain draft.
    assert copy.state == 'DRAFT'
    assert copy.preview_image is None
    assert copy.result_names == ""


def test_a_copy_carries_the_image_the_node_generated(image_library):
    """The point of copying a finished card: the copy shows the same picture."""
    scene = _Scene()
    _, image, _ = _finished_node(scene, "a")
    image_library["chair.png"] = image

    payload = node_duplicate.snapshot_selected(scene)
    copy = node_duplicate.paste_snapshot(scene, payload)[0]

    assert copy.state == 'SUCCESS'
    assert copy.result_names == "chair.png"
    # The DATABLOCK is shared, exactly as duplicating a board image shares it:
    # remove_image_safely frees one only at users <= 1, so deleting either card
    # leaves the other's picture intact.
    assert copy.preview_image is image


def test_the_copy_gets_its_own_board_entry_for_the_result(image_library):
    """`preview_image` draws the tile, but the board ENTRY is what video
    playback (moodboard_find_embedded_media_index) and Export
    (media_utils.node_exportable_media) resolve through. Sharing one entry
    between two cards would leave the second unable to play or save the clip it
    is displaying."""
    scene = _Scene()
    _, image, original_item = _finished_node(scene, "a")
    image_library["chair.png"] = image

    payload = node_duplicate.snapshot_selected(scene)
    copy = node_duplicate.paste_snapshot(scene, payload)[0]

    entries = [
        item for item in scene.mixie_moodboard_images
        if item.embedded_node_id == copy.node_id
    ]
    assert len(entries) == 1
    assert entries[0] is not original_item
    assert entries[0].image is image
    # Node-owned media are never selected -- a selected board item is synced
    # back into the chat composer as an attachment.
    assert entries[0].selected is False
    # The original keeps its own entry, untouched.
    assert original_item.embedded_node_id == "a"


def test_a_result_whose_datablock_is_gone_pastes_as_a_draft(image_library):
    """Copy a card, delete it (which frees the datablock at users <= 1), paste.
    A card advertising a result it cannot show would be worse than a draft."""
    scene = _Scene()
    _finished_node(scene, "a")
    payload = node_duplicate.snapshot_selected(scene)
    # image_library deliberately left empty: the datablock went with the node.

    copy = node_duplicate.paste_snapshot(scene, payload)[0]

    assert copy.state == 'DRAFT'
    assert copy.preview_image is None
    assert copy.result_names == ""


def test_mask_detail_result_media_is_not_copied():
    """MASK_DETAIL is uncopyable outright, so nothing of it -- configuration or
    result -- ever reaches the clipboard."""
    scene = _Scene()
    _finished_node(scene, "m", action_type='MASK_DETAIL')
    assert len(node_duplicate.snapshot_selected(scene)["nodes"]) == 0


def test_mask_detail_nodes_are_not_copyable():
    """They own a packed mask datablock that is released with the node, so a
    copy would either double-free it or be unable to generate."""
    scene = _Scene()
    _add_node(scene, "m", action_type='MASK_DETAIL', selected=True)
    assert node_duplicate.selected_action_nodes(scene) == []
    assert len(node_duplicate.snapshot_selected(scene)["nodes"]) == 0


# --------------------------------------------------------------------------- #
# Links
# --------------------------------------------------------------------------- #


def test_links_inside_the_copied_set_are_recreated_between_the_copies():
    scene = _Scene()
    _add_node(scene, "a", selected=True)
    _add_node(scene, "b", selected=True)
    _link(scene, "a", "b")

    payload = node_duplicate.snapshot_selected(scene)
    created = node_duplicate.paste_snapshot(scene, payload)

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

    payload = node_duplicate.snapshot_selected(scene)
    copy = node_duplicate.paste_snapshot(scene, payload)[0]

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

    payload = node_duplicate.snapshot_selected(scene)
    copy = node_duplicate.paste_snapshot(scene, payload)[0]

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

    payload = node_duplicate.snapshot_selected(scene)
    created = node_duplicate.paste_snapshot(scene, payload, anchor=(5000.0, 5000.0))

    dx = created[1].position_x - created[0].position_x
    dy = created[1].position_y - created[0].position_y
    assert dx == pytest.approx(900.0)
    assert dy == pytest.approx(-300.0)
    # The set's left edge lands on the anchor.
    assert min(n.position_x for n in created) == pytest.approx(5000.0)


def test_duplicate_lands_in_place_and_owns_nothing_shared():
    """The copies land ON the originals: the caller hands straight off to the
    grab modal, so they follow the mouse to wherever the user drops them --
    the same gesture a duplicated image has. A fixed offset instead left nodes
    stranded where they were dropped, unable to be placed."""
    scene = _Scene()
    _add_node(scene, "a", selected=True, position_x=100.0, position_y=100.0)
    payload = node_duplicate.snapshot_selected(scene)
    before = len(scene.mixie_moodboard_action_nodes)

    scene.mixie_moodboard_action_nodes[0].prompt = "changed after copying"
    created = node_duplicate.duplicate_selected_nodes(scene)

    assert len(scene.mixie_moodboard_action_nodes) == before + 1
    assert created[0].position_x == pytest.approx(100.0)
    assert created[0].position_y == pytest.approx(100.0)
    # A snapshot is a value, not a live view: one taken before the edit still
    # materialises what was there then, whatever a later duplicate does.
    pasted = node_duplicate.paste_snapshot(scene, payload)
    assert pasted[0].prompt == ""


def test_duplicating_nodes_hands_off_to_the_grab_modal():
    """Both entry points must, or a duplicated node cannot be placed -- which
    is exactly how it differed from a duplicated image."""
    transform = (MOODBOARD / "ui/operators/transform_ops.py").read_text(
        encoding="utf-8"
    )
    ops = (MOODBOARD / "ui/operators/node_duplicate_ops.py").read_text(
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
    payload = node_duplicate.snapshot_selected(scene)
    copy = node_duplicate.paste_snapshot(scene, payload)[0]

    assert original.selected is False
    assert copy.selected is True
    assert scene.mixie_moodboard_active_node_id == copy.node_id


def test_a_snapshot_is_independent_of_the_original_nodes():
    """Plain dicts, not RNA pointers: deleting the originals (or switching
    scene) must not invalidate what was snapshotted."""
    scene = _Scene()
    _add_node(scene, "a", selected=True, prompt="keep me")
    payload = node_duplicate.snapshot_selected(scene)
    scene.mixie_moodboard_action_nodes.remove(0)

    other = _Scene()
    pasted = node_duplicate.paste_snapshot(other, payload)
    assert [node.prompt for node in pasted] == ["keep me"]


# --------------------------------------------------------------------------- #
# There is no node clipboard
# --------------------------------------------------------------------------- #


def test_ctrl_c_and_ctrl_v_belong_to_media_alone():
    """Node copy/paste used to share Ctrl+C / Ctrl+V with the board's media and
    resolve by poll(), which made one binding mean two things depending on what
    happened to be selected -- and needed the image copy to reach over and clear
    the node clipboard so the LAST copy won. Both are gone: the keys copy and
    paste media, and duplicating a node is Shift+D."""
    keymap = (MOODBOARD / "ui/keymap.py").read_text(encoding="utf-8")
    menus = (MOODBOARD / "ui/moodboard_menus.py").read_text(encoding="utf-8")
    clipboard_ops = (MOODBOARD / "ui/operators/clipboard_ops.py").read_text(
        encoding="utf-8"
    )
    ops = (MOODBOARD / "ui/operators/node_duplicate_ops.py").read_text(
        encoding="utf-8"
    )

    for source in (keymap, menus, clipboard_ops, ops):
        assert "moodboard_copy_nodes" not in source
        assert "moodboard_paste_nodes" not in source
    assert "mixie.moodboard_copy_image" in keymap
    assert "mixie.moodboard_paste_image" in keymap
    # Nothing left to keep in step with, so the reach-over is gone too.
    assert "node_clipboard" not in clipboard_ops
    assert "node_duplicate" not in clipboard_ops

    # The module keeps no clipboard state of its own either.
    core = (MOODBOARD / "core/node_duplicate.py").read_text(encoding="utf-8")
    assert "_CLIPBOARD" not in core
    assert "def clear(" not in core
    assert "def has_content(" not in core


def test_the_duplicate_menu_entry_spells_out_its_shortcut():
    """Shift+D reaches node duplication through `mixie.moodboard_duplicate`, a
    different operator, so Blender cannot draw the shortcut next to this entry
    by itself -- and an unlabelled menu item is the only place a user would
    look for it."""
    menus = (MOODBOARD / "ui/moodboard_menus.py").read_text(encoding="utf-8")

    entry = menus.split('"mixie.moodboard_duplicate_nodes"')[1][:200]
    assert "Shift D" in entry


def test_copying_resolves_through_a_selected_node_to_its_result():
    """A generated image or video is owned by its node and is never `selected`
    itself, so a copy keyed on `item.selected` had nothing to copy when the user
    had a finished card selected. The in-app clipboard resolves the selection
    the same way Export does."""
    clipboard = (MOODBOARD / "core/moodboard_clipboard.py").read_text(
        encoding="utf-8"
    )
    clipboard_ops = (MOODBOARD / "ui/operators/clipboard_ops.py").read_text(
        encoding="utf-8"
    )

    assert "selected_exportable_media" in clipboard
    assert "for item in selected_exportable_media(scene):" in clipboard
    # The poll and the OS-clipboard still both resolve the same way, or Ctrl+C
    # on a node would be greyed out, or copy in-app but not to the system.
    assert clipboard_ops.count("selected_exportable_media") >= 2
    # A pasted result is a free-standing board item: `embedded_node_id` is not
    # among the fields a copy carries, so it cannot claim the node's result.
    assert '"embedded_node_id"' not in clipboard.split("_IMAGE_FIELDS = (")[1].split(")")[0]


def test_pasting_deselects_the_node_the_copy_came_from():
    """Otherwise the node stays selected beside the item just pasted, and the
    next Ctrl+C copies both -- the result twice over."""
    clipboard = (MOODBOARD / "core/moodboard_clipboard.py").read_text(
        encoding="utf-8"
    )
    paste = clipboard.split("def paste_clipboard(")[1]
    assert "deselect_graph_nodes(scene)" in paste
