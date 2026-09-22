# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""World Labs splat node: append-only type, IMAGE in, SPLAT out, one enqueue."""

from pathlib import Path
from types import SimpleNamespace
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "src/scripts/mixar/modules"
MOODBOARD = MODULES / "moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"

sys.path.insert(0, str(ROOT / "src/scripts"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_node_type_is_appended_last_and_mirrored_in_cpp():
    from mixar.modules.moodboard.core.node_graph import _ACCEPTED_SOURCE_TYPES
    from mixar.modules.moodboard.core.node_schema import (
        _OUTPUT_TYPES,
        _capability_for_action,
        output_type_for_action,
    )
    from mixar.modules.moodboard.ui.moodboard_graph_properties import (
        ACTION_TYPES,
        capability_for_action,
    )

    assert ACTION_TYPES[9][0] == 'WORLD_LABS'
    assert _OUTPUT_TYPES['WORLD_LABS'] == 'SPLAT'
    assert output_type_for_action('WORLD_LABS') == 'SPLAT'
    assert _ACCEPTED_SOURCE_TYPES['WORLD_LABS'] == {'IMAGE'}
    assert capability_for_action('WORLD_LABS') == "world_labs"
    assert _capability_for_action('WORLD_LABS') == "world_labs"

    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph_sockets.cc")
    kinds = re.findall(
        r"'(\w)'", re.search(r"ACTION_OUTPUT_KINDS\[\]\s*=\s*\{([^}]*)\}", draw).group(1)
    )
    assert len(kinds) == len(ACTION_TYPES) and kinds[9] == 'S'


def test_splat_output_is_not_a_mesh_continuation_source():
    from mixar.modules.moodboard.core.node_graph import mesh_source_object_names
    from mixar.modules.moodboard.core.node_schema import output_type_for_action

    assert output_type_for_action('WORLD_LABS') != 'MESH'
    scene = SimpleNamespace(
        mixie_moodboard_action_nodes=[
            SimpleNamespace(
                node_id="splat",
                action_type='WORLD_LABS',
                result_names="WorldLabs_splat,WorldLabs_proxy",
            )
        ],
        mixie_moodboard_asset_nodes=[],
        mixie_moodboard_images=[],
    )
    assert mesh_source_object_names(scene, "splat") == []


def test_run_action_uses_shared_enqueue_not_generate_to_3d():
    enqueue = _read(MOODBOARD / "core/world_labs_enqueue.py")
    execution = _read(MOODBOARD / "core/node_execution.py")
    queue = _read(MOODBOARD / "core/world_labs_queue.py")
    ops = _read(MOODBOARD / "ui/operators/world_labs_ops.py")

    assert "def run_world_labs_node(" in enqueue
    assert "elif node.action_type == 'WORLD_LABS':" in execution
    assert "run_world_labs_node" in execution
    assert "enqueue_world_labs_job" in enqueue
    assert "graph_node_id=node.node_id" in enqueue
    assert "ensure_graph_listener(FEATURE_WORLD_LABS)" in enqueue
    assert "graph_node_id: str = \"\"" in queue
    assert "create_asset_result" in queue
    assert "resolve_world_labs_catalog as _catalog_settings" in ops
    assert "def _catalog_settings(" not in ops


def test_schema_injects_optional_image_when_catalog_omits_it():
    schema = _read(MOODBOARD / "core/node_schema.py")
    inject = schema[schema.index("if node.action_type == 'WORLD_LABS'"):]
    assert '"accepted_types": ["IMAGE"]' in inject
    assert '"required": False' in inject
    assert 'limits["IMAGE"]' in inject


def test_menus_offer_splat_from_an_image_or_image_gen():
    context_menu = _read(MOODBOARD / "ui/moodboard_menus.py")
    node_menus = _read(MOODBOARD / "ui/moodboard_node_menus.py")
    output_menu = _read(MOODBOARD / "ui/moodboard_output_menu.py")

    assert "if source_type == 'IMAGE' and capability_available(\"world_labs\")" in output_menu
    assert "'WORLD_LABS', \"Generate Splat\"" in output_menu
    assert "action_node.action_type == 'IMAGE_GEN'" in context_menu
    assert "'WORLD_LABS', \"Generate Splat\"" in context_menu
    assert "selected_stills > 0 and _capability_available(\"world_labs\")" in context_menu
    assert "for item in available_templates():" in node_menus
    assert "draw_template(layout, item, drop=drop)" in node_menus


def test_selected_media_keeps_one_still_for_splat():
    from mixar.modules.moodboard.core import node_graph

    still_a = SimpleNamespace(selected=True, image=SimpleNamespace(source='FILE'))
    still_b = SimpleNamespace(selected=True, image=SimpleNamespace(source='FILE'))
    movie = SimpleNamespace(selected=True, image=SimpleNamespace(source='MOVIE'))
    scene = SimpleNamespace(mixie_moodboard_images=[still_a, still_b, movie])

    assert node_graph._selected_media(scene, 'WORLD_LABS') == [still_a]
    assert node_graph._selected_media(scene, 'IMAGE_GEN') == [still_a, still_b]
