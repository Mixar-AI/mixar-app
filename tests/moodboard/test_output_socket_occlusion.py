# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""A covered output handle is neither painted, clickable nor a QA target.

Source-level pins for native code that cannot run outside Blender. The bug:
a picture dropped over an older one hid that older picture's ``+`` handle
under its pixels, but the handle's 12 px hit disc still won the click and
opened Create Next Node for an image the user could not see. One query,
``moodboard_graph_point_covered_above``, now answers the same question for the
hit-test, the media handle painter and the QA target exporter.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"
QUERY = "moodboard_graph_point_covered_above"


def _read(name: str) -> str:
    return (SPACE_MIXIE / name).read_text(encoding="utf-8")


def _function_body(text: str, signature_start: str) -> str:
    start = text.index(signature_start)
    open_brace = text.index("{", start)
    depth = 0
    for index in range(open_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace:index + 1]
    raise AssertionError(f"Unterminated function starting at {signature_start!r}")


def test_cache_stacks_bodies_in_paint_order():
    """Pictures, then action cards, then asset cards — the draw pass order.

    The query means "any body AFTER mine covers this point", so the list must
    be appended in exactly the order the canvas paints its bodies.
    """
    header = _read("mixie_intern.hh")
    assert "blender::Vector<MoodboardGraphBody> bodies;" in header
    assert "blender::Map<std::string, int> body_index;" in header
    assert "struct MoodboardGraphBody {" in _read("mixie_moodboard_hit_geometry.hh")

    build = _function_body(_read("mixie_moodboard_graph_geometry.cc"),
                           "void moodboard_graph_cache_build(")
    assert "cache->bodies.clear();" in build
    assert "cache->body_index.clear();" in build
    media = build.index('"mixie_moodboard_images"')
    cards = build.index('"mixie_moodboard_action_nodes"')
    assert media < cards, "pictures must be stacked beneath the cards"
    assert build.count("push_body(") == 2, "one push for pictures, one for both card kinds"
    # Embedded media is painted as its owning card, exactly as the image hit-test skips it.
    media_loop = build[media:cards]
    assert '"embedded_node_id"' in media_loop
    # Rotated pictures cover their rotated footprint, not an axis-aligned box.
    assert '"rotation"' in media_loop

    draw = _read("mixie_draw_moodboard.cc")
    assert draw.index("mixie_draw_moodboard_images(") < draw.index(
        "mixie_draw_moodboard_graph_nodes("), "pictures are painted before cards"


def test_covered_query_walks_only_bodies_above_the_owner():
    hit = _read("mixie_moodboard_graph_hit.cc")
    body = _function_body(hit, f"bool {QUERY}(")
    assert "for (int index = *owner + 1; index < cache.bodies.size(); index++)" in body
    assert "moodboard_inverse_rotate_point(" in body
    assert "BLI_rctf_isect_pt(&body.rect, local_x, local_y)" in body
    # An unknown owner (an id-less picture) is never covered.
    assert "if (!owner) {\n    return false;" in body


def test_output_hit_test_refuses_a_covered_handle():
    hit = _read("mixie_moodboard_graph_hit.cc")
    cards = _function_body(hit, "static bool collection_output_hit(")
    media = _function_body(hit, "bool moodboard_find_output_socket_under_mouse(")
    for body in (cards, media):
        covered = body.index(QUERY)
        # The covered test comes after the disc test and before the hit is accepted.
        assert body.index("region_socket_hit(") < covered
        assert body.index('BLI_strncpy(r_hit->socket_id, "output"') > covered
        assert re.search(rf"if \({QUERY}\([^)]*\)\) \{{\s*continue;", body), (
            "a covered handle must fall through to the next candidate")
    # The entry point builds the body stack once, like the link hit-test does.
    assert "moodboard_graph_cache_build(scene_ptr, &cache);" in media


def test_media_handle_painter_skips_a_covered_handle():
    draw = _read("mixie_draw_moodboard_graph.cc")
    media_pass = draw[draw.index('"mixie_moodboard_images"'):]
    covered = media_pass.index(QUERY)
    painted = media_pass.index("moodboard_draw_output_handle(")
    assert covered < painted, "the media '+' pass must ask before painting"
    assert re.search(rf"if \(!{QUERY}\(\*cache, media_id, handle_x, handle_y\)\)",
                     media_pass)


def test_qa_output_target_is_withheld_when_covered():
    targets = _read("mixie_moodboard_qa_targets.cc")
    covered = targets.index(QUERY)
    output = targets.index('h.surface = "moodboard_output";')
    assert covered < output
    assert re.search(rf"if \(!blender::ed::mixie::{QUERY}\(\s*cache, node_id\.c_str\(\), "
                     r"handle_x, handle_y\)\)", targets)


def test_rotation_helper_is_shared_not_duplicated():
    """One inverse-rotation, declared once; the hit-test and the query share it."""
    header = _read("mixie_moodboard_hit_geometry.hh")
    assert "void moodboard_inverse_rotate_point(" in header
    assert f"bool {QUERY}(" in header
    select = _read("mixie_select.cc")
    assert "static void inverse_rotate_point(" not in select
    assert select.count("void moodboard_inverse_rotate_point(") == 1
    hit = _read("mixie_moodboard_graph_hit.cc")
    assert "M_PI" not in hit, "the query must call the shared helper, not re-derive it"
