/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Native Flow-styled "Export to Moodboard" popup for the Director overlay.
 * Presentation only: the render-kind toggles and the resolution slider bind
 * the registered shot RNA directly, and the action rows invoke the
 * Python-owned `mixar.director_send_keyframes` and
 * `mixar.director_render_videos` operators.
 */

#include <algorithm>
#include <cmath>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_scene_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_overlay_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

int render_kind_icon(const char *identifier)
{
  if (STREQ(identifier, "BEAUTY")) {
    return ICON_SHADING_RENDERED;
  }
  if (STREQ(identifier, "CLAY")) {
    return ICON_MESH_UVSPHERE;
  }
  if (STREQ(identifier, "DEPTH")) {
    return ICON_IMAGE_ZDEPTH;
  }
  return ICON_NONE;
}

/* The block is KEEP_OPEN so kind toggles multi-select; the Export and Render
 * actions still have to dismiss the popup, which KEEP_OPEN otherwise
 * prevents. */
void render_popup_close(bContext * /*C*/, void *arg_block, void * /*arg2*/)
{
  ui::popup_menu_retval_set(static_cast<ui::Block *>(arg_block), ui::RETURN_OK, true);
}

/* Enum-flag rows bound straight to `render_output_types`: a Row button whose
 * value is one flag bit draws pushed while the bit is set and XORs it on
 * click (native PROP_ENUM_FLAG behavior), so selection needs no operator. */
int draw_kind_toggles(bContext *C,
                      ui::Block *block,
                      DirectorPopupData &data,
                      const bool running,
                      const int y,
                      const int width,
                      const int gap)
{
  PropertyRNA *kinds_prop = RNA_struct_find_property(&data.shot_ptr, "render_output_types");
  if (!kinds_prop) {
    return 0;
  }
  const EnumPropertyItem *items = nullptr;
  int items_count = 0;
  bool free_items = false;
  RNA_property_enum_items(C, &data.shot_ptr, kinds_prop, &items, &items_count, &free_items);
  const int flags = RNA_property_enum_get(&data.shot_ptr, kinds_prop);
  const int row_h = int(UI_UNIT_Y * 1.15f);
  const int third_w = (width - gap * 2) / 3;

  int enabled_count = 0;
  int drawn = 0;
  for (int index = 0; index < items_count; index++) {
    if (!items[index].identifier || !items[index].identifier[0]) {
      continue;
    }
    ui::Button *toggle = ui::uiDefIconTextButR_prop(block,
                                           ui::ButtonType::Row,
                                           render_kind_icon(items[index].identifier),
                                           items[index].name,
                                           drawn * (third_w + gap),
                                           y,
                                           short(third_w),
                                           short(row_h),
                                           &data.shot_ptr,
                                           kinds_prop,
                                           -1,
                                           0,
                                           float(items[index].value),
                                           items[index].description);
    if (running) {
      ui::button_flag_enable(toggle, ui::BUT_DISABLED);
    }
    enabled_count += int((flags & items[index].value) != 0);
    drawn++;
  }
  if (free_items && items) {
    MEM_delete_void(static_cast<void *>(items));
  }
  return enabled_count;
}

ui::Block *render_popup_create(bContext *C, ARegion *region, void * /*arg*/)
{
  ui::Block *block = director_popup_block_begin(C, region, __func__);
  /* Multi-select: picking Beauty/Clay/Depth must not dismiss the popup —
   * it closes on click-outside, Esc, or the Export/Render actions below. */
  ui::block_flag_enable(block, ui::BLOCK_KEEP_OPEN);
  DirectorPopupData data;
  if (!director_popup_data_get(C, &data) || data.shot_ptr.data == nullptr) {
    director_popup_section_label(block, "No active Director shot", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }
  const Scene *scene = CTX_data_scene(C);

  const int width = UI_UNIT_X * 12;
  const int row_h = int(UI_UNIT_Y * 1.15f);
  const int label_h = int(UI_UNIT_Y * 0.85f);
  const int gap = int(UI_UNIT_Y * 0.25f);
  int y = 0;

  char shot_name[128] = "";
  RNA_string_get(&data.shot_ptr, "name", shot_name);
  char heading[160];
  BLI_snprintf(heading,
               sizeof(heading),
               "%s  ·  T%d",
               shot_name,
               RNA_int_get(&data.shot_ptr, "version"));
  y -= label_h;
  director_popup_section_label(block, heading, y, width);

  const bool running = RNA_boolean_get(&data.shot_ptr, "render_is_running");
  const int beat_count = int(data.state.beats.size());

  /* Keyframe stills → Moodboard: the only path that boards captures, since
   * capture itself packs without boarding. */
  y -= gap + label_h;
  director_popup_section_label(block, "Keyframes", y, width);
  y -= row_h;
  char export_label[64];
  BLI_snprintf(export_label,
               sizeof(export_label),
               "Export %d Keyframe%s",
               beat_count,
               beat_count == 1 ? "" : "s");
  ui::Button *export_stills = director_overlay_operator_button(
      block,
      "MIXAR_OT_director_send_keyframes",
      ICON_EXPORT,
      export_label,
      0,
      y,
      width,
      row_h,
      "Place this shot's keyframe stills together on the Moodboard");
  director_overlay_disable_button(export_stills, beat_count < 1);
  ui::button_func_set(export_stills, render_popup_close, block, nullptr);

  /* Rendered motion-guide videos → Moodboard. */
  y -= gap + label_h;
  director_popup_section_label(block, "Render Guides", y, width);
  y -= row_h;
  const int enabled_count = draw_kind_toggles(C, block, data, running, y, width, gap);

  y -= gap + row_h;
  ui::Button *resolution = ui::uiDefButR(block,
                                ui::ButtonType::NumSlider,
                                "Resolution",
                                0,
                                y,
                                short(width),
                                short(row_h),
                                &data.shot_ptr,
                                "render_resolution_percentage",
                                0,
                                0,
                                0,
                                std::nullopt);
  if (running) {
    ui::button_flag_enable(resolution, ui::BUT_DISABLED);
  }

  y -= label_h;
  if (beat_count < 2) {
    director_popup_section_label(block, "Capture at least two camera beats", y, width);
  }
  else {
    const float fps = std::max(data.state.fps, 0.001f);
    const float duration = float(data.state.frame_end - data.state.frame_start) / fps;
    const int percent = RNA_int_get(&data.shot_ptr, "render_resolution_percentage");
    const int render_w = std::max(1, int(std::lround(scene->r.xsch * percent / 100.0)));
    const int render_h = std::max(1, int(std::lround(scene->r.ysch * percent / 100.0)));
    char summary[96];
    BLI_snprintf(summary,
                 sizeof(summary),
                 "%.1fs  ·  %d × %d  ·  %g fps",
                 double(duration),
                 render_w,
                 render_h,
                 double(fps));
    director_popup_section_label(block, summary, y, width);
  }

  y -= gap + row_h;
  if (running) {
    char status[256] = "";
    RNA_string_get(&data.shot_ptr, "render_status", status);
    director_popup_section_label(
        block, status[0] ? status : "Rendering shot videos", y, width);
  }
  else {
    char action[64];
    BLI_snprintf(action,
                 sizeof(action),
                 "Render %d Video%s to Moodboard",
                 enabled_count,
                 enabled_count == 1 ? "" : "s");
    ui::Button *render = director_overlay_operator_button(
        block,
        "MIXAR_OT_director_render_videos",
        ICON_RENDER_ANIMATION,
        action,
        0,
        y,
        width,
        row_h,
        "Render the shot beat span and add each video to Moodboard");
    director_overlay_disable_button(render, beat_count < 2 || enabled_count == 0);
    ui::button_func_set(render, render_popup_close, block, nullptr);
  }

  PropertyRNA *outputs_prop = RNA_struct_find_property(&data.shot_ptr, "render_outputs");
  const int output_count = outputs_prop ?
                               RNA_property_collection_length(&data.shot_ptr, outputs_prop) :
                               0;
  if (output_count > 0) {
    y -= gap + label_h;
    director_popup_section_label(block, "On Moodboard", y, width);
    for (int index = output_count - 1; index >= std::max(0, output_count - 3); index--) {
      PointerRNA output_ptr;
      if (!RNA_property_collection_lookup_int(&data.shot_ptr, outputs_prop, index, &output_ptr)) {
        continue;
      }
      PropertyRNA *image_prop = RNA_struct_find_property(&output_ptr, "image");
      PointerRNA image_ptr = image_prop ? RNA_property_pointer_get(&output_ptr, image_prop) :
                                          PointerRNA_NULL;
      const ID *image_id = static_cast<const ID *>(image_ptr.data);
      y -= label_h;
      ui::uiDefIconTextBut(block,
                       ui::ButtonType::Label,
                       ICON_FILE_MOVIE,
                       image_id ? image_id->name + 2 : "Missing video",
                       0,
                       y,
                       short(width),
                       short(label_h),
                       nullptr,
                       std::nullopt);
    }
  }

  director_popup_block_end(block);
  return block;
}

}  // namespace

ui::Block *view3d_director_render_popup_create(bContext *C, ARegion *region, void *arg)
{
  return render_popup_create(C, region, arg);
}
}  // namespace blender
