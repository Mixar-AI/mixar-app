# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Node-UI fixes: dead sources, producer chaining, atomic creation, re-runs.

Every case here is exercised directly on the graph layer with fake scene
records — the behaviours are pure Python, not C++ draw seams.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"

sys.path.insert(0, str(ROOT / "src/scripts"))


class _Collection(list):
    """Stand-in for an RNA CollectionProperty (index-based ``remove``)."""

    def __init__(self, factory):
        super().__init__()
        self._factory = factory

    def add(self):
        item = self._factory()
        self.append(item)
        return item

    def remove(self, index):
        return list.pop(self, index)


def _socket(socket_id, accepted="IMAGE", *, repeatable=True, group="image_ref"):
    return SimpleNamespace(
        socket_id=socket_id,
        label=socket_id,
        accepted_types=accepted,
        required=False,
        group_id=group,
        repeatable=repeatable,
        visible=True,
    )


def _action_node():
    return SimpleNamespace(
        node_id="",
        action_type="",
        width=520.0,
        height=0.0,
        position_x=0.0,
        position_y=0.0,
        selected=False,
        preview_image=None,
        input_sockets=[],
        parameters=[],
        service_key="",
        service_key_id="",
        model="",
        model_slug="",
        schema_json="{}",
        state="DRAFT",
        error="",
        result_names="",
        prompt="",
    )


def _media(node_id, *, image="IMAGE", x=0.0, y=0.0, scale=1.0):
    return SimpleNamespace(
        node_id=node_id,
        image=(
            None if image is None
            else SimpleNamespace(source=image, name=node_id, size=(1024, 1024))
        ),
        selected=False,
        embedded_node_id="",
        position_x=x,
        position_y=y,
        scale=scale,
    )


def _link():
    return SimpleNamespace(
        link_id="",
        from_node_id="",
        from_socket="output",
        to_node_id="",
        to_socket="input",
        input_order=0,
        selected=False,
    )


def _scene(media_items=()):
    return SimpleNamespace(
        mixie_moodboard_images=list(media_items),
        mixie_moodboard_action_nodes=_Collection(_action_node),
        mixie_moodboard_asset_nodes=_Collection(lambda: None),
        mixie_moodboard_links=_Collection(_link),
        mixie_moodboard_active_node_id="",
        mixie_moodboard_context_x=0.0,
        mixie_moodboard_context_y=0.0,
    )


def _image_target(scene, node_id="target", socket_ids=("image_ref:0",)):
    node = scene.mixie_moodboard_action_nodes.add()
    node.node_id = node_id
    node.action_type = "IMAGE_GEN"
    node.input_sockets = [_socket(sid) for sid in socket_ids]
    node.schema_json = '{"inputs":{"limits":{"IMAGE":%d}}}' % len(socket_ids)
    return node


@pytest.fixture
def graph():
    from mixar.modules.moodboard.core import node_graph

    return node_graph


# --------------------------------------------------------------------------- #
#  Dead media must stop pretending to be an image
# --------------------------------------------------------------------------- #


def test_a_purged_image_reports_no_output_type(graph):
    scene = _scene([_media("live"), _media("dead", image=None)])

    assert graph.node_output_type(scene, "live") == "IMAGE"
    assert graph.node_output_type(scene, "dead") == ""


def test_a_dead_source_cannot_be_connected(graph):
    scene = _scene([_media("dead", image=None)])
    target = _image_target(scene)

    with pytest.raises(ValueError, match="source node is no longer available"):
        graph.connect_nodes(scene, "dead", target.node_id, "image_ref:0")
    assert not scene.mixie_moodboard_links


def test_reconcile_prunes_links_to_a_purged_image(graph):
    scene = _scene([_media("live"), _media("dead", image=None)])
    target = _image_target(scene, socket_ids=("image_ref:0", "image_ref:1"))
    graph.add_link(scene, "dead", target.node_id, to_socket="image_ref:0")
    graph.add_link(scene, "live", target.node_id, to_socket="image_ref:1")

    graph.reconcile_node_links(scene, target)

    assert [link.from_node_id for link in scene.mixie_moodboard_links] == ["live"]


# --------------------------------------------------------------------------- #
#  A producer whose results stand beside it must still feed downstream nodes
# --------------------------------------------------------------------------- #


def test_downstream_resolves_the_latest_standalone_output(graph):
    source = _media("source")
    first = _media("out-1")
    second = _media("out-2")
    scene = _scene([source, first, second])
    producer = _image_target(scene, node_id="producer")
    downstream = _image_target(scene, node_id="downstream")
    graph.add_link(scene, producer.node_id, downstream.node_id, to_socket="image_ref:0")

    # Nothing generated yet: the producer genuinely contributes no image.
    assert graph.input_media_items(scene, downstream) == []

    graph.connect_image_outputs_as_nodes(scene, producer, "out-1")
    graph.connect_image_outputs_as_nodes(scene, producer, "out-2")

    resolved = graph.input_media_items(scene, downstream)
    assert [item.node_id for item in resolved] == ["out-2"]


# --------------------------------------------------------------------------- #
#  Creating a connected action is atomic
# --------------------------------------------------------------------------- #


def test_unwirable_creation_leaves_no_orphan_node(graph, monkeypatch):
    scene = _scene([_media("source")])
    # Catalog still loading: the new node gets no sockets, so the immediate
    # continuation link must fail.
    monkeypatch.setattr(graph, "_initialize_catalog_selection", lambda *_: None)

    with pytest.raises(ValueError, match="No available input"):
        graph.create_connected_action(scene, "IMAGE_GEN", "source")

    assert len(scene.mixie_moodboard_action_nodes) == 0
    assert not scene.mixie_moodboard_links
    assert scene.mixie_moodboard_active_node_id == ""


def test_a_dead_explicit_source_is_rejected_before_any_node_is_added(graph):
    scene = _scene([_media("dead", image=None)])

    with pytest.raises(ValueError, match="source node is no longer available"):
        graph.create_connected_action(scene, "IMAGE_GEN", "dead")
    assert len(scene.mixie_moodboard_action_nodes) == 0


def test_the_happy_path_still_creates_and_wires_the_node(graph, monkeypatch):
    scene = _scene([_media("source")])

    def fake_init(_scene, node):
        node.input_sockets = [_socket("image_ref:0")]
        node.schema_json = '{"inputs":{"limits":{"IMAGE":1}}}'

    monkeypatch.setattr(graph, "_initialize_catalog_selection", fake_init)

    node = graph.create_connected_action(scene, "IMAGE_GEN", "source")

    assert scene.mixie_moodboard_action_nodes == [node]
    assert [(link.from_node_id, link.to_node_id) for link in scene.mixie_moodboard_links] == [
        ("source", node.node_id)
    ]


# --------------------------------------------------------------------------- #
#  A rejected re-run must not deface a generating node
# --------------------------------------------------------------------------- #


def test_mark_run_failed_keeps_a_generating_node_running():
    from mixar.modules.moodboard.core.node_execution import mark_run_failed

    node = SimpleNamespace(state="RUNNING", error="")
    assert mark_run_failed(node, "This node is already running") is False
    assert node.state == "RUNNING"
    assert node.error == ""

    idle = SimpleNamespace(state="DRAFT", error="")
    assert mark_run_failed(idle, "Enter a prompt") is True
    assert idle.state == "FAILED"
    assert idle.error == "Enter a prompt"


def test_the_run_operator_records_failures_only_through_the_guard():
    ops = (MOODBOARD / "ui/operators/node_graph_ops.py").read_text(encoding="utf-8")
    run_op = ops.split("class MIXIE_OT_moodboard_run_action_node")[1]
    run_op = run_op.split("class MIXIE_OT_moodboard_cancel_action_node")[0]

    assert "mark_run_failed(node" in run_op
    assert "node.state = 'FAILED'" not in run_op
