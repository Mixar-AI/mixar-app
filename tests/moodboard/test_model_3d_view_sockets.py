# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generate to 3D node: per-angle multi-view input sockets.

A multi-view catalog model gives the node one optional image socket per vendor
angle; the socket names the angle, and the connected images submit through the
frozen ``multi_view_images`` shape beside the frontal image.
"""

import ast
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from mixar.modules.moodboard.constants import TURNAROUND_VIEW_ORDER
from mixar.modules.moodboard.core import model_3d_views, turnaround_views
from mixar.modules.moodboard.core.model_3d_views import (
    apply_view_sockets,
    build_view_socket_payload,
    split_model_3d_inputs,
    view_socket_id,
    view_type_for_socket,
)
from mixar.modules.moodboard.core.node_schema import build_input_contract

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "src/scripts/mixar/modules/moodboard/core"

# The image_to_3d service contract as seeded by the backend catalog.
PRO_SERVICE = {"input_spec": {"inputs": [
    {"name": "image", "kind": "image", "required": True},
    {"name": "prompt", "kind": "prompt", "required": False},
    {"name": "multi_view_images", "kind": "image", "required": False, "multiple": True},
]}}


def _contract(model):
    contract = build_input_contract(PRO_SERVICE, model)
    apply_view_sockets(contract, model)
    return contract


def test_multi_view_model_gets_one_socket_per_vendor_angle():
    contract = _contract({"supports_multi_view": True, "max_reference_images": 7})
    ids = [socket["id"] for socket in contract["sockets"]]
    assert ids == ["image"] + [f"view:{view}" for view in TURNAROUND_VIEW_ORDER]
    views = contract["sockets"][1:]
    assert all(not s["required"] and not s["repeatable"] for s in views)
    assert [s["label"] for s in views][:3] == ["Left", "Right", "Back"]
    assert contract["limits"]["IMAGE"] == 1 + len(TURNAROUND_VIEW_ORDER)


def test_single_view_model_keeps_one_image_socket():
    # Even when the service publishes an untyped multi_view_images group: an
    # entry without a view_type is refused by the vendor.
    contract = _contract({"max_reference_images": 7})
    assert [socket["id"] for socket in contract["sockets"]] == ["image"]
    assert contract["limits"]["IMAGE"] == 1


def test_reapplying_is_idempotent():
    model = {"supports_multi_view": True}
    contract = _contract(model)
    apply_view_sockets(contract, model)
    assert len(contract["sockets"]) == 1 + len(TURNAROUND_VIEW_ORDER)


@pytest.mark.parametrize("socket_id, expected", [
    ("view:left", "left"), ("view:right_front", "right_front"),
    ("view:front", ""), ("image", ""), ("", ""), (None, ""),
])
def test_view_type_for_socket(socket_id, expected):
    assert view_type_for_socket(socket_id) == expected


# ---------------------------------------------------------------------------
# Resolving connections
# ---------------------------------------------------------------------------

class Still:
    def __init__(self, name):
        self.name = name
        self.source = "FILE"


def _item(name, s3_key="", movie=False):
    image = Still(name)
    if movie:
        image.source = "MOVIE"
    return NS(image=image, s3_key=s3_key, turnaround_main_group="",
              turnaround_group="")


def _links(monkeypatch, pairs):
    from mixar.modules.moodboard.core import node_graph

    resolved = [(NS(to_socket=socket), item) for socket, item in pairs]
    monkeypatch.setattr(node_graph, "input_media_links", lambda s, n: resolved)


def test_split_orders_views_by_vendor_angle(monkeypatch):
    front, back, left = _item("front"), _item("back"), _item("left")
    _links(monkeypatch, [
        (view_socket_id("back"), back), ("image", front), (view_socket_id("left"), left),
    ])
    image, views = split_model_3d_inputs(NS(), NS())
    assert image is front.image
    assert views == [("left", left), ("back", back)]


@pytest.mark.parametrize("pairs, match", [
    ([], "connect one image"),
    ([("view:left", "L")], "connect one image"),
    ([("image", "A"), ("image:1", "B")], "connect only one image"),
])
def test_split_needs_exactly_one_frontal_image(monkeypatch, pairs, match):
    _links(monkeypatch, [(socket, _item(name)) for socket, name in pairs])
    with pytest.raises(ValueError, match=match):
        split_model_3d_inputs(NS(), NS())


def test_video_on_a_view_socket_is_refused(monkeypatch):
    _links(monkeypatch, [("image", _item("front")),
                         ("view:back", _item("clip", movie=True))])
    with pytest.raises(ValueError, match="back view input needs an image"):
        split_model_3d_inputs(NS(), NS())


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------

@pytest.fixture
def accepts_mv(monkeypatch):
    monkeypatch.setattr(turnaround_views, "model_accepts_multi_view", lambda s, m: True)


def test_payload_uses_the_frozen_multi_view_shape(accepts_mv, monkeypatch):
    front = _item("front", "k/front.png")
    left = _item("left", "k/left.png")
    back = _item("back")
    monkeypatch.setattr(
        "mixar.modules.moodboard.core.turnaround_payload._encode_image",
        lambda image: f"b64:{image.name}",
    )
    scene = NS(mixie_moodboard_images=[front, left, back])
    payload, warnings = build_view_socket_payload(
        scene, front.image, [("left", left), ("back", back)],
        "image_to_3d", "hunyuan-pro-fal")
    assert warnings == []
    assert payload == {
        "image_s3_key": "k/front.png",
        "multi_view_images": [
            {"s3_key": "k/left.png", "view_type": "left"},
            {"image_bytes_b64": "b64:back", "filename": "back.png", "view_type": "back"},
        ],
    }


def test_incapable_model_refuses_instead_of_dropping_views(monkeypatch):
    monkeypatch.setattr(turnaround_views, "model_accepts_multi_view", lambda s, m: False)
    front = _item("front", "k/front.png")
    with pytest.raises(ValueError, match="cannot use view inputs"):
        build_view_socket_payload(
            NS(mixie_moodboard_images=[front]), front.image,
            [("left", _item("left", "k/l.png"))], "model_3d", "tripo-low")


def test_a_frontal_image_with_a_board_set_is_refused(accepts_mv):
    front = _item("front", "k/front.png")
    front.turnaround_main_group = "turnaround_x"
    member = _item("companion", "k/c.png")
    member.turnaround_group = "turnaround_x"
    member.view_type = "right"
    scene = NS(mixie_moodboard_images=[front, member])
    with pytest.raises(ValueError, match="also has a Multiple Views set"):
        build_view_socket_payload(
            scene, front.image, [("left", _item("left", "k/l.png"))],
            "image_to_3d", "hunyuan-pro-fal")


# ---------------------------------------------------------------------------
# Wiring (bpy is a MagicMock, so the node operators are pinned at source level)
# ---------------------------------------------------------------------------

def _function_source(path, name):
    tree = ast.parse(path.read_text())
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(path.read_text(), node)


def test_model_3d_node_schema_applies_view_sockets():
    source = _function_source(CORE / "node_schema.py", "sync_node_schema")
    assert "apply_view_sockets(input_contract, model)" in source


def test_run_model_3d_submits_connected_views():
    source = _function_source(CORE / "node_execution.py", "_run_model_3d")
    assert "split_model_3d_inputs(context.scene, node)" in source
    assert "build_view_socket_payload(" in source
    assert "build_active_group_payload(" in source


def test_module_stays_within_the_line_limit():
    assert len(Path(model_3d_views.__file__).read_text().splitlines()) <= 500
