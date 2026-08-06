# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Safety contracts for the moodboard inference graph.

These are source-level pins. The behaviours they guard live in compiled C++
draw/hit-test code or in RNA declarations that cannot be exercised outside
Blender, and each one regressed silently once already.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"

# The new graph translation units. Excludes files that predate the graph and
# carry their own already-audited buffer pairings.
GRAPH_SOURCES = (
    "mixie_moodboard_graph_geometry.cc",
    "mixie_draw_moodboard_graph.cc",
    "mixie_draw_moodboard_node_ui.cc",
    "mixie_moodboard_ops_graph.cc",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _int_constant(text: str, name: str) -> int:
    match = re.search(rf"^{name}\s*=\s*(\d+)", text, re.MULTILINE)
    assert match, f"{name} is not defined"
    return int(match.group(1))


def _c_define(text: str, name: str) -> int:
    match = re.search(rf"^#define\s+{name}\s+(\d+)", text, re.MULTILINE)
    assert match, f"{name} is not defined"
    return int(match.group(1))


def test_graph_strings_declare_a_maxlen_smaller_than_their_cpp_buffer():
    """Every graph string C++ reads must be bounded on both sides.

    ``RNA_string_get`` is strcpy-shaped. Without a ``maxlen`` an RNA string is
    unbounded, so a catalog-published label or an agent-written object name
    overflows the fixed stack buffer it is read into, during draw.
    """
    constants = _read(MOODBOARD / "constants.py")
    header = _read(SPACE_MIXIE / "mixie_intern.hh")

    pairs = (
        ("GRAPH_NODE_ID_MAXLEN", "MIXIE_GRAPH_ID_BUF"),
        ("GRAPH_SOCKET_ID_MAXLEN", "MIXIE_GRAPH_ID_BUF"),
        ("GRAPH_LABEL_MAXLEN", "MIXIE_GRAPH_LABEL_BUF"),
        ("GRAPH_WIDGET_MAXLEN", "MIXIE_GRAPH_WIDGET_BUF"),
        ("GRAPH_OBJECT_NAMES_MAXLEN", "MIXIE_GRAPH_NAMES_BUF"),
    )
    for python_name, c_name in pairs:
        maxlen = _int_constant(constants, python_name)
        buffer_size = _c_define(header, c_name)
        assert maxlen < buffer_size, (
            f"{python_name}={maxlen} must stay strictly below {c_name}={buffer_size}"
        )


def test_graph_string_properties_all_declare_a_maxlen():
    properties = _read(MOODBOARD / "ui/moodboard_graph_properties.py")

    # Everything C++ reads by name. ``parameter.name`` is excluded on purpose:
    # it is the backend payload key, never read from C++, and truncating it
    # would corrupt the request.
    for field in (
        "node_id",
        "socket_id",
        "accepted_types",
        "group_id",
        "label",
        "widget",
        "title",
        "object_names",
        "from_node_id",
        "to_node_id",
        "from_socket",
        "to_socket",
    ):
        for match in re.finditer(
            rf"^    {field}: StringProperty\((.*?)\)$",
            properties,
            re.MULTILINE | re.DOTALL,
        ):
            assert "maxlen=" in match.group(1), f"{field} declares no maxlen"


def test_graph_cpp_never_reads_rna_strings_unbounded():
    """All reads go through the clamping helper, which truncates instead.

    ``maxlen`` is only enforced on assignment, so a .blend written before those
    limits existed can still carry a longer value into these buffers.
    """
    for name in GRAPH_SOURCES:
        text = _read(SPACE_MIXIE / name)
        stripped = text.replace("mixie_rna_string_get_clamped", "")
        stripped = stripped.replace("mixie_rna_property_string_get_clamped", "")
        # The helper's own definition is the one legitimate raw read: it is
        # guarded by an explicit length check on the line above.
        if name == "mixie_moodboard_graph_geometry.cc":
            stripped = stripped.replace(
                "RNA_property_string_get(ptr, prop, dst);", ""
            )
        assert "RNA_string_get(" not in stripped, f"{name} reads an RNA string unbounded"
        assert "RNA_property_string_get(" not in stripped, (
            f"{name} reads an RNA string unbounded"
        )


def test_link_drag_preview_is_not_keyed_on_a_raw_scene_pointer():
    """A static Scene * outlives its scene across a file load."""
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")

    assert "scene_uid" in geometry
    assert "Scene *scene = nullptr;" not in geometry
    assert "g_link_drag.scene ==" not in geometry
    # Region teardown must be able to drop an in-flight drag outright.
    assert "void moodboard_graph_link_drag_reset()" in geometry
    assert "moodboard_graph_link_drag_reset" in _read(SPACE_MIXIE / "space_mixie.cc")


def test_link_endpoints_and_hit_testing_share_one_pass_cache():
    """Resolving each endpoint independently was O(links * images) per redraw,
    with a locked ``BKE_image_acquire_ibuf`` in the inner loop."""
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")

    assert "void moodboard_graph_cache_build(" in geometry
    assert "moodboard_graph_cache_build(scene_ptr, &cache)" in geometry
    assert "moodboard_graph_cache_build(&scene_ptr, &cache)" in draw
    # Links are culled before their curve is evaluated.
    assert "moodboard_graph_link_bounds" in draw
    assert "is_rect_in_view" in draw


def test_graph_modal_guards_context_before_dereferencing_it():
    ops = _read(SPACE_MIXIE / "mixie_moodboard_ops_graph.cc")

    modal = ops.split("static wmOperatorStatus graph_select_modal(")[1]
    prologue = modal.split("PointerRNA scene_ptr = RNA_id_pointer_create")[0]
    assert "if (!scene || !region)" in prologue


def test_media_lookup_never_writes_during_draw():
    """``node_output_type`` is reached from a menu draw; assigning node ids
    there would write scene data mid-redraw."""
    graph = _read(MOODBOARD / "core/node_graph.py")

    lookup = graph.split("def media_item_by_id(")[1].split("\ndef ")[0]
    assert "ensure_media_node_ids" not in lookup
    # The migration still has to run somewhere outside draw.
    chat_sync = _read(MOODBOARD / "core/chat_sync.py")
    assert "ensure_media_node_ids" in chat_sync


def test_node_service_and_model_resolve_from_saved_slugs():
    """A dynamic EnumProperty is stored as an index into the items list, so it
    drifts when the catalog reorders or has not loaded yet."""
    schema = _read(MOODBOARD / "core/node_schema.py")
    execution = _read(MOODBOARD / "core/node_execution.py")

    assert "def node_service_key(node)" in schema
    assert "def node_model_slug(node)" in schema
    assert "def restore_node_selection(node)" in schema
    # Execution must never read the transient dropdowns.
    assert "node.service_key" not in execution
    assert "node.model" not in execution
    assert "node_service_key(node)" in execution
    assert "node_model_slug(node)" in execution


def test_canvas_menu_filters_catalog_services_to_the_moodboard_surface():
    """Paint-only services (brush_gen under image_gen) must not make a canvas
    action look available."""
    menus = _read(MOODBOARD / "ui/moodboard_menus.py")

    available = menus.split("def _capability_available(")[1].split("\ndef ")[0]
    assert 'surface="moodboard"' in available


def test_asset_selection_does_not_call_object_select_all_from_the_mixie_space():
    """``bpy.ops.object.select_all`` polls false outside a 3D-viewport context
    and raises an uncaught RuntimeError."""
    ops = _read(MOODBOARD / "ui/operators/node_graph_ops.py")

    # Match the call, not the comment that explains why it is not used.
    assert "bpy.ops.object.select_all(" not in ops
    assert "obj.select_set(False)" in ops


def test_load_post_restores_dropdowns_and_normalizes_overlong_ids():
    """Opening a .blend while the catalog is already loaded produces no
    catalog swap, so the swap callback alone cannot re-derive the dropdowns."""
    chat_sync = _read(MOODBOARD / "core/chat_sync.py")
    graph = _read(MOODBOARD / "core/node_graph.py")

    assert "_restore_graph_node_selections" in chat_sync
    assert "restore_node_selection" in chat_sync
    # An id over the maxlen predates the contract and can never match the C++
    # length-first comparison, so its links would be unresolvable forever.
    migration = graph.split("def ensure_media_node_ids(")[1].split("\ndef ")[0]
    assert "GRAPH_NODE_ID_MAXLEN" in migration
