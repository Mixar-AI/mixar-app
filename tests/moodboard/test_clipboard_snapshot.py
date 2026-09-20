# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The moodboard clipboard's ONE snapshot: media, text boxes, nodes, links.

Exercised against a hand-rolled fake scene (as `test_node_duplicate.py` is)
because the snapshot's job is to move values and remap link endpoints, which a
MagicMock scene would accept without asserting anything.

The cross-process contract is pinned here too: the payload must survive a JSON
round trip and materialise through an injected image resolver, because that is
exactly what a paste in ANOTHER running Mixar does after appending the images
from the on-disk copy buffer.
"""

import json
from pathlib import Path

import pytest

from mixar.modules.moodboard.core import clipboard_snapshot, node_duplicate

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
    """Stand-in for a bpy Image: the snapshot reads `.name`, `.size`, `.source`."""

    def __init__(self, name, size=(1000, 500), source='FILE'):
        self.name = name
        self.size = size
        self.source = source


class _Point:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0


class _Stroke:
    def __init__(self):
        self.color = (1.0, 0.0, 0.0, 1.0)
        self.width = 2.0
        self.points = _Collection(_Point)


class _MediaItem:
    def __init__(self):
        self.node_id = ""
        self.embedded_node_id = ""
        self.image = None
        self.selected = False
        self.position_x = 0.0
        self.position_y = 0.0
        self.scale = 1.0
        self.rotation = 0.0
        self.flip_horizontal = False
        self.flip_vertical = False
        self.generation_prompt = ""
        self.component_role = 'NONE'
        self.component_source_item_id = ""
        self.component_source_segment_id = ""
        self.component_name = ""
        self.show_annotations = True
        self.annotations = _Collection(_Stroke)
        self.group_index = -1
        self.z_order = 0
        self.mixar_created_at_iso = ""


class _TextBox:
    def __init__(self):
        self.text = "Text"
        self.position_x = 0.0
        self.position_y = 0.0
        self.font_size = 14
        self.width = 200.0
        self.height = 100.0
        self.rotation = 0.0
        self.text_color = (1.0, 1.0, 1.0, 1.0)
        self.background_color = (0.0, 0.0, 0.0, 0.5)
        self.bold = False
        self.italic = False
        self.align = 'LEFT'
        self.z_order = 0
        self.selected = False


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
        self.mixie_moodboard_textboxes = _Collection(_TextBox)
        self.mixie_moodboard_active_node_id = ""


_SCHEMA_JSON = '{"inputs": {"limits": {"IMAGE": 4, "TOTAL": 4}}}'


def _add_node(scene, node_id, action_type='IMAGE_GEN', **fields):
    node = scene.mixie_moodboard_action_nodes.add()
    node.node_id = node_id
    node.action_type = action_type
    node.schema_json = _SCHEMA_JSON
    socket = node.input_sockets.add()
    socket.socket_id = "image_0"
    socket.accepted_types = "IMAGE"
    for key, value in fields.items():
        setattr(node, key, value)
    return node


def _add_media(scene, node_id, image, *, selected=True, **fields):
    item = scene.mixie_moodboard_images.add()
    item.node_id = node_id
    item.image = image
    item.selected = selected
    for key, value in fields.items():
        setattr(item, key, value)
    return item


def _link(scene, from_id, to_id, to_socket="image_0"):
    link = scene.mixie_moodboard_links.add()
    link.from_node_id = from_id
    link.to_node_id = to_id
    link.to_socket = to_socket
    return link


def _links(scene):
    return {(link.from_node_id, link.to_node_id) for link in scene.mixie_moodboard_links}


@pytest.fixture
def image_library(monkeypatch):
    """Back `bpy.data.images.get` with a real dict (the suite's bpy is a mock)."""
    import bpy

    library = {}
    monkeypatch.setattr(bpy.data, "images", library, raising=False)
    return library


def _paste(scene, payload, library, anchor=(0.0, 0.0)):
    return clipboard_snapshot.materialize_snapshot(scene, payload, library.get, anchor=anchor)


# --------------------------------------------------------------------------- #
# What one copy contains
# --------------------------------------------------------------------------- #


def test_a_reference_image_wired_into_a_node_pastes_as_a_wired_pair(image_library):
    """The whole point of copying a graph: the media feeding a node comes with
    it and the link is remade between the COPIES, not back to the original."""
    scene = _Scene()
    photo = _Image("photo.png")
    image_library["photo.png"] = photo
    _add_media(scene, "m1", photo, position_x=0.0, position_y=0.0)
    _add_node(scene, "gen", selected=True, position_x=900.0, position_y=0.0)
    _link(scene, "m1", "gen")

    payload = clipboard_snapshot.build_snapshot(scene)
    assert [m["image_name"] for m in payload["media"]] == ["photo.png"]
    assert len(payload["nodes"]) == 1
    assert payload["links"] == [{
        "from_node_id": "m1", "from_socket": "output", "to_node_id": "gen",
        "to_socket": "image_0", "input_order": 0, "internal": True,
    }]

    target = _Scene()
    pasted = _paste(target, payload, image_library)

    assert pasted == 2
    new_media = target.mixie_moodboard_images[0]
    new_node = target.mixie_moodboard_action_nodes[0]
    assert new_media.node_id and new_media.node_id != "m1"
    assert new_media.image is photo
    assert _links(target) == {(new_media.node_id, new_node.node_id)}


def test_a_copied_nodes_result_travels_inside_the_node_never_twice(image_library):
    """selected_exportable_media resolves a selected node to its embedded
    result. That entry must NOT also appear as loose media, or a pasted card
    would come with a second, free-floating copy of its own picture."""
    scene = _Scene()
    result = _Image("result.png")
    image_library["result.png"] = result
    node = _add_node(
        scene, "gen", selected=True, state='SUCCESS', result_names="result.png",
        preview_image=result,
    )
    _add_media(scene, "r1", result, selected=False, embedded_node_id=node.node_id)

    payload = clipboard_snapshot.build_snapshot(scene)
    assert payload["media"] == []
    assert payload["nodes"][0]["result"]["preview_image_name"] == "result.png"

    target = _Scene()
    _paste(target, payload, image_library)
    entries = list(target.mixie_moodboard_images)
    assert len(entries) == 1
    assert entries[0].embedded_node_id == target.mixie_moodboard_action_nodes[0].node_id
    assert entries[0].selected is False


def test_the_result_of_an_uncopyable_node_still_pastes_as_a_loose_item(image_library):
    """MASK_DETAIL never copies (it owns a packed mask), but its picture is
    still what the user selected -- it lands as an ordinary board item."""
    scene = _Scene()
    result = _Image("detail.png")
    image_library["detail.png"] = result
    node = _add_node(scene, "mask", action_type='MASK_DETAIL', selected=True,
                     state='SUCCESS', preview_image=result)
    _add_media(scene, "r1", result, selected=False, embedded_node_id=node.node_id)

    payload = clipboard_snapshot.build_snapshot(scene)
    assert payload["nodes"] == []
    assert [m["image_name"] for m in payload["media"]] == ["detail.png"]

    target = _Scene()
    _paste(target, payload, image_library)
    assert target.mixie_moodboard_images[0].embedded_node_id == ""
    assert target.mixie_moodboard_images[0].selected is True


def test_text_boxes_and_annotations_travel(image_library):
    scene = _Scene()
    photo = _Image("photo.png")
    image_library["photo.png"] = photo
    item = _add_media(scene, "m1", photo, rotation=90.0, generation_prompt="a cat")
    stroke = item.annotations.add()
    stroke.color = (0.0, 1.0, 0.0, 1.0)
    stroke.width = 3.0
    for x, y in ((0.1, 0.2), (0.3, 0.4)):
        point = stroke.points.add()
        point.x, point.y = x, y
    tb = scene.mixie_moodboard_textboxes.add()
    tb.text = "note"
    tb.bold = True
    tb.align = 'CENTER'
    tb.selected = True

    payload = clipboard_snapshot.build_snapshot(scene)
    target = _Scene()
    assert _paste(target, payload, image_library) == 2

    copy = target.mixie_moodboard_images[0]
    assert copy.rotation == 90.0
    assert copy.generation_prompt == "a cat"
    assert [(p.x, p.y) for p in copy.annotations[0].points] == [(0.1, 0.2), (0.3, 0.4)]
    assert copy.annotations[0].width == 3.0
    new_tb = target.mixie_moodboard_textboxes[0]
    assert (new_tb.text, new_tb.bold, new_tb.align) == ("note", True, 'CENTER')
    assert new_tb.selected is True


def test_item_count_and_referenced_names_cover_every_kind(image_library):
    scene = _Scene()
    photo, result = _Image("photo.png"), _Image("result.png")
    _add_media(scene, "m1", photo)
    node = _add_node(scene, "gen", selected=True, state='SUCCESS', preview_image=result)
    _add_media(scene, "r1", result, selected=False, embedded_node_id=node.node_id)
    tb = scene.mixie_moodboard_textboxes.add()
    tb.selected = True

    payload = clipboard_snapshot.build_snapshot(scene)
    assert clipboard_snapshot.item_count(payload) == 3
    assert clipboard_snapshot.referenced_image_names(payload) == ["photo.png", "result.png"]
    assert clipboard_snapshot.item_count(None) == 0
    assert clipboard_snapshot.referenced_image_names({}) == []


# --------------------------------------------------------------------------- #
# The cross-process contract
# --------------------------------------------------------------------------- #


def test_payload_survives_json_and_materialises_through_a_foreign_resolver(image_library):
    """A paste in another Mixar reads the manifest's JSON and binds images to
    the datablocks it just appended -- which may have been RENAMED on a
    collision. The snapshot must never look the recorded name up directly."""
    scene = _Scene()
    photo = _Image("photo.png")
    _add_media(scene, "m1", photo, position_x=10.0, position_y=20.0)
    node = _add_node(scene, "gen", selected=True, prompt="make it blue",
                     position_x=900.0, position_y=0.0, state='SUCCESS',
                     result_names="out.png", preview_image=_Image("out.png"))
    _add_media(scene, "r1", node.preview_image, selected=False, embedded_node_id="gen")
    _link(scene, "m1", "gen")

    wire = json.loads(json.dumps(clipboard_snapshot.build_snapshot(scene)))

    appended = {"photo.png": _Image("photo.png.001"), "out.png": _Image("out.png.001")}
    other = _Scene()
    pasted = clipboard_snapshot.materialize_snapshot(other, wire, appended.get, anchor=(0.0, 0.0))

    assert pasted == 2
    media = other.mixie_moodboard_images
    new_node = other.mixie_moodboard_action_nodes[0]
    assert new_node.prompt == "make it blue"
    assert new_node.state == 'SUCCESS'
    assert new_node.preview_image is appended["out.png"]
    loose = [m for m in media if not m.embedded_node_id]
    assert len(loose) == 1 and loose[0].image is appended["photo.png"]
    assert _links(other) == {(loose[0].node_id, new_node.node_id)}


def test_an_unresolvable_image_is_skipped_and_an_unresolvable_result_is_a_draft():
    scene = _Scene()
    _add_media(scene, "m1", _Image("gone.png"))
    _add_node(scene, "gen", selected=True, state='SUCCESS', preview_image=_Image("lost.png"))
    payload = clipboard_snapshot.build_snapshot(scene)

    other = _Scene()
    pasted = clipboard_snapshot.materialize_snapshot(other, payload, lambda _n: None, anchor=(0.0, 0.0))

    assert pasted == 1
    assert list(other.mixie_moodboard_images) == []
    assert other.mixie_moodboard_action_nodes[0].state == 'DRAFT'


def test_a_source_outside_the_copy_is_dropped_where_it_does_not_resolve(image_library):
    """Same scene: an external reference keeps feeding the copy (a duplicated
    Generate keeps its photo). Another scene or process: the id resolves to
    nothing and reconcile drops the link rather than leaving a dangling one."""
    scene = _Scene()
    photo = _Image("photo.png")
    _add_media(scene, "m1", photo, selected=False)
    _add_node(scene, "gen", selected=True)
    _link(scene, "m1", "gen")
    payload = clipboard_snapshot.build_snapshot(scene)
    assert payload["links"][0]["internal"] is False

    _paste(scene, payload, image_library)
    copy = scene.mixie_moodboard_action_nodes[-1]
    assert ("m1", copy.node_id) in _links(scene)

    other = _Scene()
    _paste(other, payload, image_library)
    assert _links(other) == set()


def test_an_outgoing_link_and_an_orphan_output_link_are_not_copied(image_library):
    """Out of the set: the downstream input already has a source. Into a loose
    output image from an uncopied producer: the paste would claim that node
    generated it."""
    scene = _Scene()
    out = _Image("out.png")
    _add_node(scene, "gen", selected=True)
    _add_node(scene, "down")
    _link(scene, "gen", "down")
    _add_node(scene, "producer")
    _add_media(scene, "o1", out)
    _link(scene, "producer", "o1", to_socket="")

    payload = clipboard_snapshot.build_snapshot(scene)
    assert payload["links"] == []


def test_a_copied_producer_keeps_its_link_to_its_copied_output_image(image_library):
    """Multi-output generations stand their results BESIDE the card, linked
    from its output handle; copying both keeps that relationship."""
    scene = _Scene()
    out = _Image("out.png")
    image_library["out.png"] = out
    _add_node(scene, "producer", selected=True)
    _add_media(scene, "o1", out)
    _link(scene, "producer", "o1", to_socket="")

    payload = clipboard_snapshot.build_snapshot(scene)
    target = _Scene()
    _paste(target, payload, image_library)
    new_node = target.mixie_moodboard_action_nodes[0]
    new_media = target.mixie_moodboard_images[0]
    assert _links(target) == {(new_node.node_id, new_media.node_id)}


def test_a_stale_payload_version_is_refused():
    assert clipboard_snapshot.materialize_snapshot(_Scene(), {"version": 99, "media": []}, lambda n: None) == 0


# --------------------------------------------------------------------------- #
# Placement and selection
# --------------------------------------------------------------------------- #


def test_the_group_is_translated_as_one_block_centred_on_the_anchor(image_library):
    scene = _Scene()
    photo = _Image("photo.png", size=(1000, 1000))
    image_library["photo.png"] = photo
    _add_media(scene, "m1", photo, position_x=0.0, position_y=0.0)
    _add_node(scene, "gen", selected=True, position_x=1000.0, position_y=-200.0,
              width=500.0, height=500.0)
    tb = scene.mixie_moodboard_textboxes.add()
    tb.position_x, tb.position_y, tb.width, tb.height = -300.0, 100.0, 200.0, 100.0
    tb.selected = True

    payload = clipboard_snapshot.build_snapshot(scene)
    target = _Scene()
    _paste(target, payload, image_library, anchor=(5000.0, 5000.0))

    media = target.mixie_moodboard_images[0]
    node = target.mixie_moodboard_action_nodes[0]
    box = target.mixie_moodboard_textboxes[0]
    # Relative layout preserved...
    assert node.position_x - media.position_x == pytest.approx(1000.0)
    assert node.position_y - media.position_y == pytest.approx(-200.0)
    assert box.position_x - media.position_x == pytest.approx(-300.0)
    # ...and the whole group's bounding box centred on the anchor.
    from mixar.modules.moodboard.core.moodboard_utils import get_moodboard_image_display_size

    media_w, media_h = get_moodboard_image_display_size(photo, media.scale)
    left = min(media.position_x, node.position_x, box.position_x)
    right = max(media.position_x + media_w, node.position_x + 500.0, box.position_x + 200.0)
    bottom = min(media.position_y, node.position_y, box.position_y)
    top = max(media.position_y + media_h, node.position_y + 500.0, box.position_y + 100.0)
    assert (left + right) / 2.0 == pytest.approx(5000.0)
    assert (bottom + top) / 2.0 == pytest.approx(5000.0)


def test_paste_selects_exactly_what_it_created(image_library):
    scene = _Scene()
    photo = _Image("photo.png")
    image_library["photo.png"] = photo
    original = _add_media(scene, "m1", photo)
    source_node = _add_node(scene, "gen", selected=True)

    payload = clipboard_snapshot.build_snapshot(scene)
    _paste(scene, payload, image_library)

    assert original.selected is False
    assert source_node.selected is False
    copies = [m for m in scene.mixie_moodboard_images if m is not original]
    assert all(m.selected for m in copies)
    new_node = scene.mixie_moodboard_action_nodes[-1]
    assert new_node.selected is True
    assert scene.mixie_moodboard_active_node_id == new_node.node_id


def test_a_snapshot_is_a_value_independent_of_the_scene(image_library):
    scene = _Scene()
    photo = _Image("photo.png")
    image_library["photo.png"] = photo
    _add_media(scene, "m1", photo, generation_prompt="keep me")
    payload = clipboard_snapshot.build_snapshot(scene)
    scene.mixie_moodboard_images[0].generation_prompt = "changed"
    scene.mixie_moodboard_images.remove(0)

    other = _Scene()
    _paste(other, payload, image_library)
    assert other.mixie_moodboard_images[0].generation_prompt == "keep me"


def test_node_duplicate_lends_its_serializers_and_stays_in_step():
    """Shift+D and Ctrl+C must describe a node identically, so the snapshot
    reuses node_duplicate's serializer and materializer rather than owning a
    second field table that would drift."""
    source = (MOODBOARD / "core/clipboard_snapshot.py").read_text(encoding="utf-8")
    assert "node_duplicate.serialize_node(scene, node)" in source
    assert "node_duplicate.materialize_node(scene, data, delta, resolve)" in source
    assert node_duplicate.materialize_node is node_duplicate._materialize
