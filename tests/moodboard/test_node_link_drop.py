# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Dragging a noodle into open canvas offers the next node.

Releasing a link used to cancel unless the pointer had never left the output
handle, so the one gesture that says "continue from here" did nothing. The
drop resolution itself lives in compiled C++, so the seams are pinned at
source level; the placement it drives is exercised directly.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"

sys.path.insert(0, str(ROOT / "src/scripts"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _node_graph():
    from mixar.modules.moodboard.core import node_graph

    return node_graph


class _Collection(list):
    """Stand-in for an RNA CollectionProperty of graph records."""

    def __init__(self, factory):
        super().__init__()
        self._factory = factory

    def add(self):
        item = self._factory()
        self.append(item)
        return item


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
    )


def _media(node_id: str, *, x: float, y: float, scale: float = 1.0):
    return SimpleNamespace(
        node_id=node_id,
        image=SimpleNamespace(source='IMAGE', size=(1024, 1024)),
        selected=False,
        position_x=x,
        position_y=y,
        scale=scale,
    )


def _scene(media_items):
    return SimpleNamespace(
        mixie_moodboard_images=list(media_items),
        mixie_moodboard_action_nodes=_Collection(_action_node),
        mixie_moodboard_asset_nodes=[],
        mixie_moodboard_links=[],
        mixie_moodboard_active_node_id="",
        mixie_moodboard_context_x=0.0,
        mixie_moodboard_context_y=0.0,
    )


@pytest.fixture
def graph(monkeypatch):
    """``create_connected_action`` with its catalog and wiring stubbed out.

    Both are covered by their own suites; what is under test here is where the
    node lands.
    """
    module = _node_graph()
    monkeypatch.setattr(
        module, "_initialize_catalog_selection", lambda scene, node: None
    )
    monkeypatch.setattr(
        module, "connect_to_next_input", lambda scene, from_id, to_id: None
    )
    return module


def test_a_dropped_noodle_places_its_node_under_the_cursor(graph):
    source = _media("source", x=0.0, y=0.0)
    scene = _scene([source])

    node = graph.create_connected_action(
        scene, 'IMAGE_GEN', "source", drop_position=(1400.0, 250.0)
    )

    # Left edge at the drop point, centred on it vertically: the card's input
    # side lands where the noodle was let go.
    assert node.position_x == pytest.approx(1400.0)
    assert node.position_y == pytest.approx(250.0 - node.height * 0.5)


def test_the_drop_position_wins_over_the_source_relative_placement(graph):
    source = _media("source", x=0.0, y=0.0)
    scene = _scene([source])

    beside = graph.create_connected_action(scene, 'IMAGE_GEN', "source")
    dropped = graph.create_connected_action(
        scene, 'IMAGE_GEN', "source", drop_position=(1400.0, 250.0)
    )

    assert beside.position_x != pytest.approx(dropped.position_x)
    assert dropped.position_x == pytest.approx(1400.0)


def test_without_a_drop_the_node_still_lands_beside_its_source(graph):
    from mixar.modules.moodboard.core.moodboard_utils import (
        get_moodboard_image_display_size,
    )

    source = _media("source", x=120.0, y=40.0)
    scene = _scene([source])
    width, height = get_moodboard_image_display_size(source.image, source.scale)

    node = graph.create_connected_action(scene, 'IMAGE_GEN', "source")

    assert node.position_x == pytest.approx(120.0 + width + graph.ACTION_NODE_GAP)
    assert node.position_y == pytest.approx(40.0 + height * 0.5 - node.height * 0.5)


def _release():
    """The body of ``moodboard_graph_link_release``."""
    link = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph_link.cc")
    return link.split("wmOperatorStatus moodboard_graph_link_release(")[1]


def test_the_modal_hands_every_release_to_one_resolution():
    """Four outcomes share one decision; the modal only frees the drag data."""
    ops = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph.cc")
    cmake = _read(SPACE_MIXIE / "CMakeLists.txt")

    modal = ops.split("if (event->type == LEFTMOUSE && event->val == KM_RELEASE) {")[1]
    assert "moved ? OPERATOR_CANCELLED" not in modal
    assert "moodboard_graph_link_release(" in modal
    # `moved` and the source id are read before MEM_delete frees the drag data.
    assert modal.index("const bool moved = data->moved;") < modal.index(
        "MEM_delete(data);"
    )
    assert "mixie_moodboard_ops_graph_link.cc" in cmake


def test_a_dragged_release_opens_the_continuation_menu():
    """The gesture used to be swallowed: `moved` released into empty canvas
    returned CANCELLED, so only a click on the output handle offered a node."""
    release = _release()

    assert "set_link_drop_anchor(scene_ptr, true, drop_x, drop_y);" in release
    assert release.index("set_link_drop_anchor(scene_ptr, true") < release.index(
        "return call_output_menu(C, scene_ptr, from_node_id, event);\n}"
    )
    # A plain click keeps its old source-relative placement.
    assert release.index("if (!moved) {") < release.index(
        "set_link_drop_anchor(scene_ptr, true"
    )


def test_a_release_over_an_occupied_spot_never_stacks_a_new_card():
    """A card dropped onto existing content would be born hidden underneath it."""
    link = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph_link.cc")

    assert "static bool graph_drop_is_occupied(" in link
    occupied = link.split("static bool graph_drop_is_occupied(")[1].split("\n}")[0]
    for probe in (
        "moodboard_find_asset_node_under_mouse",
        "moodboard_find_image_under_mouse",
        "moodboard_find_textbox_under_mouse",
    ):
        assert probe in occupied
    release = _release()
    assert release.index("graph_drop_is_occupied(scene_ptr, drop_x, drop_y)") < (
        release.index("set_link_drop_anchor(scene_ptr, true")
    )


def test_a_release_on_a_card_body_connects_instead_of_creating():
    """Missing the socket by a few pixels still names an unambiguous target."""
    link = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph_link.cc")
    operators = _read(MOODBOARD / "ui/operators/node_graph_ops.py")
    release = _release()

    assert "moodboard_find_action_node_under_mouse(scene_ptr, x, y, &rect)" in link
    assert "graph_drop_card_target(scene_ptr, drop_x, drop_y, &card)" in release
    # A body drop leaves `socket_id` empty, which the operator reads as "the
    # first free compatible slot".
    target = link.split("static bool graph_drop_card_target(")[1].split("\n}")[0]
    assert "*r_target = MoodboardGraphSocketHit{};" in target
    assert '"socket_id"' not in target
    connect = operators.split("class MIXIE_OT_moodboard_connect_nodes(")[1]
    assert "if self.to_socket:" in connect
    assert "connect_to_next_input(" in connect
    # Released back on its own source there is nothing to connect and nowhere
    # to put a card, so it must not report a cycle the user never asked for.
    assert "STREQ(card.node_id, from_node_id)" in release


def test_the_drop_anchor_is_cleared_at_every_other_menu_entry_point():
    """The output handle's own coordinates sit on the source node's edge, so a
    stale anchor would spawn the next card on top of it."""
    ops = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph.cc")

    drag_start = ops.split("static wmOperatorStatus graph_select_invoke(")[1].split(
        "return OPERATOR_RUNNING_MODAL;"
    )[0]
    assert "moodboard_graph_clear_link_drop_anchor(&scene_ptr);" in drag_start
    context = ops.split("static wmOperatorStatus graph_context_invoke(")[1]
    assert "moodboard_graph_clear_link_drop_anchor(&scene_ptr);" in context


def test_link_drop_state_is_registered_and_unregistered():
    registration = _read(MOODBOARD / "ui/moodboard_scene_registration.py")

    for name in (
        "mixie_moodboard_link_drop_active",
        "mixie_moodboard_link_drop_x",
        "mixie_moodboard_link_drop_y",
    ):
        assert registration.count(f"'{name}'") >= 1, f"{name} is never unregistered"
    # x/y are registered through the shared axis loop.
    assert "f'mixie_moodboard_link_drop_{axis}'" in registration
    assert "'mixie_moodboard_link_drop_active'," in registration


def _menu_draw_ast():
    """The output menu's ``draw`` body, parsed."""
    tree = ast.parse(_read(MOODBOARD / "ui/moodboard_menus.py"))
    menu = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "MIXIE_MT_moodboard_output_menu"
    )
    return next(
        node for node in menu.body
        if isinstance(node, ast.FunctionDef) and node.name == "draw"
    )


def test_the_continuation_menu_forwards_the_drop_anchor_to_every_entry():
    """One entry left without the anchor drops its node beside the source
    instead, so the same menu would place cards two different ways."""
    draw = _menu_draw_ast()

    calls = [
        node for node in ast.walk(draw)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_connected_action"
    ]
    assert calls, "the continuation menu offers no actions"
    for call in calls:
        passed = {ast.unparse(arg) for arg in call.args}
        passed |= {ast.unparse(kw.value) for kw in call.keywords}
        assert "drop" in passed, f"{ast.unparse(call)} drops the anchor"


def test_the_create_operator_never_remembers_a_drop_position():
    """A REGISTER operator re-fills unset properties from its last run, so one
    node created by dropping a noodle would pin every later menu entry."""
    operators = _read(MOODBOARD / "ui/operators/node_graph_ops.py")

    create = operators.split("class MIXIE_OT_moodboard_create_connected_action(")[1]
    create = create.split("\nclass ")[0]
    for prop in ("use_drop_position", "drop_x", "drop_y"):
        declaration = create.split(f"{prop}: bpy.props.")[1].split("\n")[0]
        assert "SKIP_SAVE" in declaration, f"{prop} is remembered between runs"


def test_the_menu_reads_the_anchor_without_writing_scene_data():
    """``_link_drop_anchor`` runs from a menu draw, where a write to scene data
    tags the depsgraph and re-triggers the redraw that called it."""
    tree = ast.parse(_read(MOODBOARD / "ui/moodboard_menus.py"))
    anchor = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_link_drop_anchor"
    )

    reads = {
        node.args[1].value
        for node in ast.walk(anchor)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and isinstance(node.args[1], ast.Constant)
    }
    assert reads == {
        "mixie_moodboard_link_drop_active",
        "mixie_moodboard_link_drop_x",
        "mixie_moodboard_link_drop_y",
    }
    for node in ast.walk(anchor):
        assert not isinstance(node, (ast.Assign, ast.AugAssign)), (
            "the anchor lookup writes during draw"
        )
