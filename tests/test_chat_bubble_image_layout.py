# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level pins for chat-bubble attachment thumbnail layout.

The C++ overlay cannot be compiled from the standalone suite, so these
tests read the draw/layout sources. The user-visible bug: a tall attached
reference sheet showed only a cropped feet-strip, left of the prompt text.

1. **Same left edge as the message text.** Attachments used to be drawn at
   ``bubble_x`` plus ``image_style.margin`` while the prompt used
   ``bubble_x + h_padding``. The thumbnail must start at ``h_padding`` and
   fit the text column (``content_width``).

2. **View2D-space quad, not a pixel blit.** Message drawing runs under
   ``UI_view2d_view_ortho``. ``PixelBitmapDrawer`` (the 5.2 successor of
   ``immDrawPixelsTexScaledFullSize``) is a pixel-space blit; in that
   matrix a native-size sheet is clipped to a sliver at the top of the
   region. The attachment widget uploads a UNORM texture and draws it with
   ``chat_ui_draw_image`` (the same GPU-matrix path as the rest of the
   bubble).
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/source/blender/editors/space_mixie_chat"
IMAGE_CC = CHAT / "mixie_chat_ui_attachments.cc"
RENDER_CC = CHAT / "mixie_chat_messages_render.cc"
LAYOUT_CC = CHAT / "mixie_chat_messages_layout.cc"
CONTENT_CC = CHAT / "mixie_chat_messages_content.cc"
HIT_CC = CHAT / "mixie_chat_hit_testing.cc"
WIDGETS_CC = CHAT / "mixie_chat_ui_widgets.cc"
INTERN_HH = CHAT / "mixie_chat_intern.hh"


def _fn(src: str, name: str) -> str:
    start = src.index(name + "(")
    start = src.rindex("\n", 0, start)
    depth = 0
    i = src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start : j + 1]
    raise AssertionError(name)


class TestAttachmentSharesTheTextColumn:
    def test_message_draw_uses_text_inset_and_content_width(self):
        body = _fn(
            RENDER_CC.read_text(encoding="utf-8"),
            "void mixie_chat_render_messages",
        )
        assert "layout.bubble_x + layout.style.h_padding" in body
        assert "layout.content_width" in body
        assert "layout.bubble_x, att_y" not in body
        assert "layout.bubble_width, &image_style" not in body

    def test_layout_height_uses_the_text_column_width(self):
        src = LAYOUT_CC.read_text(encoding="utf-8")
        calc = _fn(src, "static float calculate_attachments_height")
        assert "available_width" in calc
        build = _fn(src, "float mixie_chat_build_layout_cache")
        compact = " ".join(build.split())
        assert (
            "calculate_attachments_height( bmain, &msg_ptr, &image_style, "
            "&layout.attachments, content_width)"
            in compact
        )

    def test_header_requires_available_width_on_height_calc(self):
        src = INTERN_HH.read_text(encoding="utf-8")
        assert "float available_width);" in src


class TestAttachmentDrawsInView2D:
    def test_image_widget_draws_a_textured_quad(self):
        src = IMAGE_CC.read_text(encoding="utf-8")
        draw = _fn(src, "float chat_ui_draw_image_attachment")
        upload = _fn(src, "static gpu::Texture *upload_attachment_texture")
        assert "chat_ui_draw_image(" in draw
        assert "upload_attachment_texture(" in draw
        assert "GPU_texture_create_2d" in upload
        assert "GPU_texture_update" in upload
        assert "GPU_texture_free" in draw
        assert "PixelBitmapDrawer" not in draw
        assert "immDrawPixelsTexScaledFullSize" not in draw

    def test_left_edge_is_the_callers_x_not_an_extra_margin(self):
        draw = _fn(
            IMAGE_CC.read_text(encoding="utf-8"),
            "float chat_ui_draw_image_attachment",
        )
        assert "rect.xmin = x;" in draw
        assert "x + style->margin" not in draw

    def test_aspect_fit_is_shared_by_layout_and_draw(self):
        src = IMAGE_CC.read_text(encoding="utf-8")
        calc = _fn(src, "float chat_ui_calc_image_attachment_height")
        draw = _fn(src, "float chat_ui_draw_image_attachment")
        assert "attachment_max_width(style, available_width)" in calc
        assert "attachment_max_width(style, max_width)" in draw
        assert "chat_ui_calc_image_bounds" in calc
        assert "chat_ui_calc_image_bounds" in draw

    def test_widgets_no_longer_own_the_pixel_blit(self):
        src = WIDGETS_CC.read_text(encoding="utf-8")
        assert "chat_ui_draw_image_attachment" not in src
        assert "PixelBitmapDrawer" not in src
        assert "immDrawPixelsTexScaledFullSize" not in src


class TestMarkdownLeavesRoomForTheThumbnail:
    def test_markdown_starts_below_attachments(self):
        src = CONTENT_CC.read_text(encoding="utf-8")
        compact = " ".join(src.split())
        assert compact.count("layout.attachments_height") >= 2
        assert "v_padding - layout.attachments_height" in compact

    def test_hit_testing_markdown_rect_matches_the_draw_offset(self):
        body = _fn(
            HIT_CC.read_text(encoding="utf-8"),
            "bool mixie_chat_layout_text_rect",
        )
        compact = " ".join(body.split())
        assert "layout->attachments_height" in compact
        assert "is_markdown_content" in body
        assert "v_padding - layout->attachments_height" in compact
