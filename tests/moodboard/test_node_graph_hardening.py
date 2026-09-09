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
    "mixie_draw_moodboard_graph_sockets.cc",
    "mixie_draw_moodboard_media_labels.cc",
    "mixie_draw_moodboard_node_ui.cc",
    "mixie_moodboard_ops_graph.cc",
    "mixie_moodboard_ops_graph_link.cc",
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
        ("GRAPH_ACCEPTED_TYPES_MAXLEN", "MIXIE_GRAPH_ID_BUF"),
        ("GRAPH_LABEL_MAXLEN", "MIXIE_GRAPH_LABEL_BUF"),
        ("GRAPH_WIDGET_MAXLEN", "MIXIE_GRAPH_WIDGET_BUF"),
        ("GRAPH_OBJECT_NAMES_MAXLEN", "MIXIE_GRAPH_NAMES_BUF"),
        ("GRAPH_ERROR_MAXLEN", "MIXIE_GRAPH_ERROR_BUF"),
        # Read into a stack buffer when composing a parameter's tooltip.
        ("GRAPH_DESCRIPTION_MAXLEN", "MIXIE_GRAPH_DESCRIPTION_BUF"),
        # Read into a stack buffer by the card header's state side.
        ("GRAPH_PROGRESS_MAXLEN", "MIXIE_GRAPH_PROGRESS_BUF"),
        # Read into a stack buffer by the refused-connection notice.
        ("GRAPH_NOTICE_MAXLEN", "MIXIE_GRAPH_NOTICE_BUF"),
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
        "value_label",
        "service_label",
        "model_label",
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
    with a locked ``BKE_image_acquire_ibuf`` in the inner loop. The draw side
    goes further: ONE cache per frame, built at the mode entry and passed to
    every graph pass — each pass building its own tripled the per-frame
    ImBuf acquires."""
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")
    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    draw_mode = _read(SPACE_MIXIE / "mixie_draw_moodboard.cc")

    assert "void moodboard_graph_cache_build(" in geometry
    assert "moodboard_graph_cache_build(scene_ptr, &cache)" in geometry
    assert "moodboard_graph_cache_build(&scene_ptr, &graph_cache)" in draw_mode
    assert "mixie_draw_moodboard_links(C, v2d, &graph_cache)" in draw_mode
    assert "mixie_draw_moodboard_graph_nodes(C, v2d, &graph_cache)" in draw_mode
    # The passes consume the shared cache, never build their own.
    assert "moodboard_graph_cache_build" not in draw
    # The nodes pass reads media rects from the cache instead of re-acquiring
    # every image's ImBuf for its aspect.
    assert "BKE_image_acquire_ibuf" not in draw
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


def test_catalog_swap_refreshes_nodes_independently_of_the_npanel_engine():
    """The sidebar engine and the moodboard nodes are two independent consumers
    of the catalog. Sharing one try block meant anything raising in the engine
    branch — including the blanket `except ImportError` that exists for "the
    params module is not loaded yet" — skipped the node sweep silently, so the
    N-panel picked up a catalog change while every node kept its old dropdowns
    and nothing was logged."""
    consumers = _read(
        ROOT / "src/scripts/mixar/bootstrap/generation_catalog/consumers.py"
    )

    engine_at = consumers.index("rebuild_from_catalog()")
    nodes_at = consumers.index("sync_all_node_schemas()")
    # A try of its own, opened AFTER the engine branch has been closed off.
    between = consumers[engine_at:nodes_at]
    assert between.count("except") >= 1, "node sweep shares the engine's try block"
    assert "try:" in between
    # And its own log line, so a node-side failure is not reported as an
    # engine failure (or not at all).
    assert "Moodboard node catalog refresh failed" in consumers
    # Every consumer is called, and none can stop the next one.
    fanout = consumers.split("def notify_catalog_swapped()")[1]
    for call in ("_rebuild_parameter_engine()", "_refresh_moodboard_nodes()",
                 "_refresh_sidebar_tab_labels()"):
        assert call in fanout


def test_one_unresolvable_node_cannot_strand_the_rest_of_the_board():
    """The sweep walks every node of every scene. Without per-node isolation a
    single node whose service/model no longer resolves aborts the loop, leaving
    every later node — and every later scene — on the previous catalog."""
    schema = _read(MOODBOARD / "core/node_schema.py")
    sweep = schema.split("def sync_all_node_schemas()")[1].split(
        "def _sync_one_node_schema"
    )[0]
    assert "try:" in sweep and "except Exception" in sweep
    assert "_sync_one_node_schema(" in sweep
    # Named, not swallowed: a stale dropdown is indistinguishable from a node
    # nobody has touched, so the node id has to reach the log.
    assert 'getattr(node, "node_id"' in sweep


def test_every_extend_select_property_skips_save():
    """`extend` must never persist between invocations.

    These are REGISTER operators, so `WM_operator_last_properties_init` refills
    any non-PROP_SKIP_SAVE property the invocation did not set from the previous
    run -- and the plain-click keymap items set nothing. Without the flag, ONE
    Shift or Cmd click remembered `extend = true`, so every later plain click
    took the toggle branch, which returns FINISHED and installs no modal: cards
    could no longer be dragged at all, a press only selected or deselected them.
    Media select had the flag and kept working, which is exactly how the two
    came to behave differently.
    """
    # Anchor on the DEFINITION (`"extend", false, ...`), not on the reads
    # (`RNA_boolean_get(op->ptr, "extend")`), which have no trailing comma.
    definition = '"extend",'
    checked = 0
    for name in ("mixie_moodboard_ops_graph.cc", "mixie_moodboard_ops_select.cc"):
        source = _read(SPACE_MIXIE / name)
        for tail in source.split(definition)[1:]:
            checked += 1
            assert "PROP_SKIP_SAVE" in tail[:400], (
                f"{name}: extend is defined without PROP_SKIP_SAVE"
            )
    assert checked == 2, f"expected both extend properties, found {checked}"


def test_repeatable_inputs_keep_their_own_type_and_name():
    """A shared `max_materials` budget used to collapse every repeatable input
    into one pooled, untyped "Material N" group -- which is how Generate Video
    advertised a single violet socket named "Material 1" when it actually takes
    images AND videos, each with its own ceiling. The budget is a limit, not a
    description of the inputs."""
    from mixar.modules.moodboard.core.node_schema import build_input_contract

    service = {}
    model = {
        "input_spec": {
            "max_materials": 5,
            "inputs": [
                {"name": "image", "kind": "image", "multiple": True, "max_count": 4},
                {"name": "video", "kind": "video", "multiple": True, "max_count": 2},
            ],
        }
    }
    contract = build_input_contract(service, model)
    labels = [socket["label"] for socket in contract["sockets"]]
    accepted = {socket["label"]: socket["accepted_types"] for socket in contract["sockets"]}
    groups = {socket["group_id"] for socket in contract["sockets"]}

    assert not any(label.startswith("Material") for label in labels), labels
    assert "Image 1" in labels and "Video 1" in labels
    assert accepted["Image 1"] == ["IMAGE"]
    assert accepted["Video 1"] == ["VIDEO"]
    assert groups == {"image", "video"}

    # Per-type ceilings AND the pooled budget, both enforced by connect_nodes.
    assert contract["limits"]["IMAGE"] == 4
    assert contract["limits"]["VIDEO"] == 2
    assert contract["limits"]["TOTAL"] == 5


def test_a_large_input_group_cannot_starve_a_later_one_of_sockets():
    """Generate Video declares 30 reference images and THEN 10 reference videos.
    The socket budget used to be handed out in declaration order, so images took
    30 of the 32 slots and the node minted just TWO video sockets -- while
    `limits` still advertised ten, so eight of them could never be connected and
    nothing reported why. Sockets and limits must agree, and no group may be
    starved by an earlier one."""
    from mixar.modules.moodboard.core.node_schema import build_input_contract

    # The live catalog contract for video_gen / seedance-2-5.
    service = {
        "input_spec": {
            "max_materials": 50,
            "inputs": [
                {"kind": "prompt", "name": "prompt", "required": True},
                {
                    "name": "reference_images",
                    "kind": "image",
                    "multiple": True,
                    "max_count": 30,
                },
                {
                    "name": "reference_videos",
                    "kind": "video",
                    "multiple": True,
                    "max_count": 10,
                },
            ],
        }
    }
    contract = build_input_contract(service, {})
    per_type = {}
    for socket in contract["sockets"]:
        accepted = socket["accepted_types"][0]
        per_type[accepted] = per_type.get(accepted, 0) + 1

    assert per_type["VIDEO"] == 10, per_type
    assert per_type["IMAGE"] == 30, per_type

    # A limit the sockets cannot satisfy is the failure this regressed on.
    assert contract["limits"]["VIDEO"] == per_type["VIDEO"]
    assert contract["limits"]["IMAGE"] == per_type["IMAGE"]


def test_socket_budget_is_shared_rather_than_drained_in_order():
    """The budget allocator itself: an over-subscribed contract degrades by
    sharing what is left, never by giving the first group everything."""
    from mixar.modules.moodboard.core.node_schema import (
        _MAX_INPUT_SOCKETS,
        _allocate_socket_budget,
    )

    # Fits: everyone gets what they asked for.
    assert _allocate_socket_budget([30, 10], _MAX_INPUT_SOCKETS) == [30, 10]
    # Over-subscribed: the budget is spent in full and the small group survives.
    granted = _allocate_socket_budget([100, 4], 10)
    assert sum(granted) == 10
    assert granted[1] == 4, granted
    # Never hands out more than a group wants, or more than the budget.
    assert _allocate_socket_budget([2, 2], 50) == [2, 2]
    assert _allocate_socket_budget([], 10) == []


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
