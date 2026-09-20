/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Custom GPU overlay drawing for footer region.
 * Handles send button glow, submit icon, plan mode toggle,
 * thumbnails, and remove buttons.
 * Split from mixie_chat_footer.cc for modularity.
 */

#include <algorithm>
#include <cmath>

#include "BLI_time.h"

#include "BLF_api.hh"

#include "BKE_context.hh"

#include "DNA_scene_types.h"

#include "ED_screen.hh"
#include "ED_moodboard_attachment.hh"

#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "mixie_chat_footer_constants.hh"
#include "mixie_chat_footer_intern.hh"
#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Send Button Pulse Glow
 * \{ */

void footer_draw_send_button_glow(ARegion *region,
                                   PointerRNA *scene_ptr,
                                   const FooterElementPositions &pos,
                                   float scale)
{
  PropertyRNA *input_prop = RNA_struct_find_property(scene_ptr, "mixie_chat_input");
  if (input_prop && RNA_property_string_length(scene_ptr, input_prop) > 0) {
    ED_region_pixelspace(region);
    GPU_blend(GPU_BLEND_ALPHA);
    float gc[4];
    chat_ui_get_prompt_button_color(gc);
    gc[3] = 0.2f + 0.12f * std::sin(float(BLI_time_now_seconds() * 3.5));
    float gp = 4.0f * scale;
    rctf gr;
    gr.xmin = float(pos.send_btn_x) - gp;
    gr.xmax = float(pos.send_btn_x + pos.btn_size) + gp;
    gr.ymin = float(pos.buttons_y) - gp;
    gr.ymax = float(pos.buttons_y + pos.btn_size) + gp;
    ui::draw_roundbox_corner_set(ui::CNR_ALL);
    ui::draw_roundbox_4fv(&gr, true, (float(pos.btn_size) + gp * 2.0f) * 0.5f, gc);
    GPU_blend(GPU_BLEND_NONE);
    ED_region_tag_redraw(region);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Submit Button Icon
 * \{ */

void footer_draw_submit_icon(ARegion *region, const FooterElementPositions &pos)
{
  ED_region_pixelspace(region);
  float icon_x = float(pos.send_btn_x);
  float icon_y = float(pos.buttons_y);
  float aspect = 16.0f / float(pos.btn_size);
  ui::icon_draw_ex(
      icon_x, icon_y, ICON_SUBMIT_ARROW, aspect, 1.0f, 0.0f, nullptr, false, UI_NO_ICON_OVERLAY_TEXT);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Plan Mode Toggle Switch (iOS-style)
 * \{ */

void footer_draw_plan_toggle(ARegion *region,
                              const FooterThemeCache *theme,
                              const FooterElementPositions &pos,
                              bool plan_enabled,
                              int plan_toggle_x,
                              float scale)
{
  ED_region_pixelspace(region);
  GPU_blend(GPU_BLEND_ALPHA);

  const int switch_track_w = int(36 * scale);
  const int switch_track_h = int(20 * scale);
  const int knob_padding = int(2 * scale);
  const int knob_diameter = switch_track_h - (knob_padding * 2);
  const int label_gap = int(4 * scale);

  /* Measure label to position the switch after it */
  const int font_id = BLF_default();
  BLF_size(font_id, 11.0f * scale);
  const float label_w = BLF_width(font_id, "Plan", 4);

  /* Switch track position: right-aligned within the toggle area */
  const float track_x = float(plan_toggle_x) + label_w + float(label_gap);
  const float track_cy = float(pos.buttons_y) + float(pos.button_row_height) * 0.5f;
  const float track_y = track_cy - float(switch_track_h) * 0.5f;

  /* Track colors from theme cache */
  const float *track_color = plan_enabled ? theme->toggle_on_color : theme->toggle_off_color;

  /* Draw track (pill shape: radius = half height for fully rounded ends) */
  rctf track_rect;
  track_rect.xmin = track_x;
  track_rect.ymin = track_y;
  track_rect.xmax = track_x + float(switch_track_w);
  track_rect.ymax = track_y + float(switch_track_h);

  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&track_rect, true, float(switch_track_h) * 0.5f, track_color);

  /* Draw knob: left when OFF, right when ON */
  const float *knob_color = theme->toggle_knob_color;
  float knob_x;
  if (plan_enabled) {
    knob_x = track_x + float(switch_track_w) - float(knob_padding) - float(knob_diameter);
  }
  else {
    knob_x = track_x + float(knob_padding);
  }
  const float knob_y = track_y + float(knob_padding);

  rctf knob_rect;
  knob_rect.xmin = knob_x;
  knob_rect.ymin = knob_y;
  knob_rect.xmax = knob_x + float(knob_diameter);
  knob_rect.ymax = knob_y + float(knob_diameter);

  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&knob_rect, true, float(knob_diameter) * 0.5f, knob_color);

  /* Draw "Plan" label text to the left of the switch */
  const float *text_color = theme->toggle_label_color;
  const float label_x = float(plan_toggle_x);
  const float text_h = BLF_height(font_id, "Plan", 4);
  const float label_y = track_cy - text_h * 0.5f;

  BLF_color4fv(font_id, text_color);
  BLF_position(font_id, label_x, label_y, 0.0f);
  BLF_draw(font_id, "Plan", 4);

  GPU_blend(GPU_BLEND_NONE);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Thumbnail Drawing + Remove Buttons
 * \{ */

void footer_draw_thumbnails(const bContext *C,
                             ARegion *region,
                             Main *bmain,
                             PointerRNA *scene_ptr,
                             const FooterElementPositions &pos,
                             const FooterThemeCache *theme,
                             int pending_count,
                             const blender::Vector<FooterAttachmentCache> *attachments,
                             float scale)
{
  /* Draw cached thumbnails */
  if (pending_count > 0 && bmain && attachments) {
    ED_region_pixelspace(region);

    const float *border_color = theme->border_color;
    const float thumb_padding = theme->thumbnail_padding;

    const int max_display = (pending_count < FOOTER_MAX_ATTACHMENTS) ? pending_count :
                                                                        FOOTER_MAX_ATTACHMENTS;
    const int columns = std::max(1, pos.thumb_columns);

    for (int i = 0; i < max_display; i++) {
      const FooterAttachmentCache &cached = (*attachments)[i];
      const int col = i % columns;
      const int row = i / columns;
      const float x = float(pos.side_padding) + float(col * (pos.thumb_size + pos.thumb_spacing));
      const float y = float(pos.thumb_y) + float(row * (pos.thumb_size + pos.thumb_spacing));

      footer_thumbnails_draw_border(x, y, float(pos.thumb_size), border_color);

      footer_thumbnails_draw_image(bmain,
                                    cached.path,
                                    cached.source,
                                    x + thumb_padding,
                                    y + thumb_padding,
                                    float(pos.thumb_size) - (thumb_padding * 2.0f));

      if (cached.source == 1) {
        ED_moodboard_attachment_target(C, region, cached.path,
            {x, x + pos.thumb_size, y, y + pos.thumb_size});
      }
    }
  }

  /* Draw remove buttons (separate UI block for z-order) */
  if (pending_count > 0) {
    ui::Block *remove_block = ui::block_begin(
        C, region, "remove_buttons", blender::ui::EmbossType::Emboss);

    const int remove_btn_size = int(FOOTER_REMOVE_BUTTON_SIZE_BASE * scale);
    const int columns = std::max(1, pos.thumb_columns);

    PropertyRNA *pending_prop = RNA_struct_find_property(
        scene_ptr, "mixie_chat_pending_attachments");
    if (pending_prop) {
      int count = RNA_property_collection_length(scene_ptr, pending_prop);
      const int max_buttons = (count < FOOTER_MAX_ATTACHMENTS) ? count : FOOTER_MAX_ATTACHMENTS;

      for (int index = 0; index < max_buttons; index++) {
        const int col = index % columns;
        const int row = index / columns;
        const int x = pos.side_padding + col * (pos.thumb_size + pos.thumb_spacing);
        const int y = pos.thumb_y + row * (pos.thumb_size + pos.thumb_spacing);
        ui::Button *remove_but = ui::uiDefIconButO(remove_block,
                                          ui::ButtonType::But,
                                          "MIXIE_CHAT_OT_remove_attachment",
                                          blender::wm::OpCallContext::InvokeDefault,
                                          ICON_X,
                                          x + pos.thumb_size - remove_btn_size,
                                          y + pos.thumb_size - remove_btn_size,
                                          remove_btn_size,
                                          remove_btn_size,
                                          std::nullopt);
        RNA_int_set(ui::button_operator_ptr_ensure(remove_but), "index", index);
      }
    }

    ui::block_end(C, remove_block);
    ui::block_draw(C, remove_block);
  }
}

/** \} */
}  // namespace blender
