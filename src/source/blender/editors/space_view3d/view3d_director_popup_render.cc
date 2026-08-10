/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Native Flow-styled Shot Renders popup for the Director overlay.
 * Presentation only: the render-kind toggles and the resolution slider bind
 * the registered shot RNA directly, and the action row invokes the
 * Python-owned `mixar.director_render_videos` operator.
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

/* The block is KEEP_OPEN so kind toggles multi-select; the Render action
 * still has to dismiss the popup, which KEEP_OPEN otherwise prevents. */
void render_popup_close(bContext * /*C*/, void *arg_block, void * /*arg2*/)
{
  UI_popup_menu_retval_set(static_cast<uiBlock *>(arg_block), UI_RETURN_OK, true);
}

/* Enum-flag rows bound straight to `render_output_types`: a Row button whose
 * value is one flag bit draws pushed while the bit is set and XORs it on
 * click (native PROP_ENUM_FLAG behavior), so selection needs no operator. */
int draw_kind_toggles(bContext *C,
                      uiBlock *block,
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
    uiBut *toggle = uiDefIconTextButR_prop(block,
                                           ButType::Row,
                                           0,
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
      UI_but_flag_enable(toggle, UI_BUT_DISABLED);
    }
    enabled_count += int((flags & items[index].value) != 0);
    drawn++;
  }
  if (free_items && items) {
    MEM_freeN(items);
  }
  return enabled_count;
}

uiBlock *render_popup_create(bContext *C, ARegion *region, void * /*arg*/)
{
  uiBlock *block = director_popup_block_begin(C, region, __func__);
  /* Multi-select: picking Beauty/Clay/Depth must not dismiss the popup —
   * it closes on click-outside, Esc, or the Render action below. */
  UI_block_flag_enable(block, UI_BLOCK_KEEP_OPEN);
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

  y -= gap + label_h;
  director_popup_section_label(block, "Render Videos", y, width);
  y -= row_h;
  const int enabled_count = draw_kind_toggles(C, block, data, running, y, width, gap);

  y -= gap + row_h;
  uiBut *resolution = uiDefButR(block,
                                ButType::NumSlider,
                                0,
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
    UI_but_flag_enable(resolution, UI_BUT_DISABLED);
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
    uiBut *render = director_overlay_operator_button(
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
    UI_but_func_set(render, render_popup_close, block, nullptr);
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
      uiDefIconTextBut(block,
                       ButType::Label,
                       0,
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

uiBlock *view3d_director_render_popup_create(bContext *C, ARegion *region, void *arg)
{
  return render_popup_create(C, region, arg);
}
