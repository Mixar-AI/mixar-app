/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Native Flow-styled "Export to Moodboard" popup for the Director overlay.
 *
 * ONE send flow, read top to bottom: whether the keyframe images go, which
 * videos render (Color / Clay / Depth), how big they are, what that comes
 * to, and a single action that names exactly what it will send. It used to
 * be two unrelated actions under jargon headings ("Render Guides", "Beauty
 * Preview", "T1", "camera beats") with a percentage slider whose meaning was
 * a caption away.
 *
 * The two three-up rows are segmented GROUPS — cells edge to edge, each with
 * a resting track and a centred label — and the send is a filled accent pill.
 * They were option rows with a leading icon that fit in "Clay" and not in
 * "Color" or "Depth", labels left-aligned inside their own third, and a send
 * that was bare text: a panel of loose words with one chip among them.
 *
 * Presentation only: the toggles and the size cells bind shot RNA directly,
 * and the action runs the Python-owned `mixar.director_export_to_moodboard`.
 * What it sends is `core/board_export.export_plan`; `send_plan` below is its
 * native mirror, so the label and the operator agree.
 */

#include <algorithm>
#include <cmath>
#include <cstring>
#include <string>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"

#include "DNA_scene_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "../interface/interface_mixar_profile_card.hh"

#include "view3d_director.hh"
#include "view3d_director_overlay_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* `ui::Button::tip` is a NON-owning StringRef, so handing it an entry of an
 * `EnumPropertyItem` array this file is about to free leaves the button
 * pointing at freed memory — an undefined tooltip on hover, and freed bytes in
 * the QA introspection dump. The callback form owns its argument. */
std::string director_tooltip_owned_fn(bContext * /*C*/,
                                      void *argN,
                                      blender::StringRef /*tip*/)
{
  return std::string(static_cast<const char *>(argN));
}

void director_but_tooltip_owned(ui::Button *but, const char *text)
{
  if (but == nullptr || text == nullptr || text[0] == '\0') {
    return;
  }
  const size_t size = strlen(text) + 1;
  char *owned = static_cast<char *>(MEM_new_uninitialized(size, __func__));
  memcpy(owned, text, size);
  ui::button_func_tooltip_set(but, director_tooltip_owned_fn, owned, MEM_delete_void);
}


/* The block is KEEP_OPEN so the toggles multi-select; the Send action still
 * has to dismiss the popup, which KEEP_OPEN otherwise prevents. */
void render_popup_close(bContext * /*C*/, void *arg_block, void * /*arg2*/)
{
  ui::popup_menu_retval_set(static_cast<ui::Block *>(arg_block), ui::RETURN_OK, true);
}

/* Enum-flag rows bound straight to `render_output_types`: a Row button whose
 * value is one flag bit draws pushed while the bit is set and XORs it on
 * click (native PROP_ENUM_FLAG behavior), so selection needs no operator.
 *
 * They are the cells of ONE segmented group — three cells edge to edge, each
 * with a resting track and a centred label, more than one of which may be
 * lit. They were Option rows with a leading icon, which fit in "Clay" and not
 * in "Color" or "Depth", so the row read as a chip with two loose words
 * beside it. */
int draw_kind_toggles(bContext *C,
                      ui::Block *block,
                      DirectorPopupData &data,
                      const bool running,
                      const int y,
                      const int width)
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

  int usable = 0;
  for (int index = 0; index < items_count; index++) {
    usable += int(items[index].identifier && items[index].identifier[0]);
  }
  /* Edge to edge, as the size cells below: each spans from its own edge to
   * the next one's, so integer division never leaves the last one short. */
  const int cells = std::max(usable, 1);
  const auto cell_x = [width, cells](const int index) { return (width * index) / cells; };

  int enabled_count = 0;
  int drawn = 0;
  for (int index = 0; index < items_count; index++) {
    if (!items[index].identifier || !items[index].identifier[0]) {
      continue;
    }
    ui::Button *toggle = ui::uiDefButR_prop(block,
                                           ui::ButtonType::Row,
                                           items[index].name,
                                           cell_x(drawn),
                                           y,
                                           short(cell_x(drawn + 1) - cell_x(drawn)),
                                           short(row_h),
                                           &data.shot_ptr,
                                           kinds_prop,
                                           -1,
                                           0,
                                           float(items[index].value),
                                           std::nullopt);
    director_but_tooltip_owned(toggle, items[index].description);
    ui::UI_mixar_cinema_row_tag(toggle, ui::MixarCinemaRowKind::Segment);
    if (running) {
      ui::button_flag_enable(toggle, ui::BUT_DISABLED);
    }
    enabled_count += int((flags & items[index].value) != 0);
    drawn++;
  }
  if (free_items && items) {
    MEM_delete_void(static_cast<void *>(const_cast<EnumPropertyItem *>(items)));
  }
  return enabled_count;
}

/** Video size presets: `VIDEO_SIZE_PRESETS` in `director/constants.py`. */
struct VideoSize {
  int percent;
  const char *name;
  const char *tip;
};
constexpr VideoSize VIDEO_SIZES[] = {
    {25, "Draft", "A quarter of the output size: fastest"},
    {50, "Half", "Half the output size"},
    {100, "Full", "The full output size: slowest"},
};

/** What the Send action will send — `core/board_export.export_plan`. */
struct SendPlan {
  int images = 0;
  int videos = 0;
};

SendPlan send_plan(const DirectorPopupData &data,
                   const bool export_images,
                   const int chosen_videos,
                   const bool running)
{
  SendPlan plan;
  if (export_images) {
    for (const DirectorBeatView &beat : data.state.beats) {
      plan.images += int(beat.has_still);
    }
  }
  int distinct = 0;
  int previous = 0;
  blender::Vector<int> frames;
  for (const DirectorBeatView &beat : data.state.beats) {
    frames.append(beat.frame);
  }
  std::sort(frames.begin(), frames.end());
  for (const int frame : frames) {
    distinct += int(distinct == 0 || frame != previous);
    previous = frame;
  }
  if (!running && distinct >= 2) {
    plan.videos = chosen_videos;
  }
  return plan;
}

/** "Send 3 Images + 2 Videos" — `core/board_export.plan_label`. */
void send_label(const SendPlan &plan, char *r_label, const size_t size)
{
  if (plan.images > 0 && plan.videos > 0) {
    BLI_snprintf(r_label,
                 size,
                 "Send %d Image%s + %d Video%s",
                 plan.images,
                 plan.images == 1 ? "" : "s",
                 plan.videos,
                 plan.videos == 1 ? "" : "s");
  }
  else if (plan.images > 0) {
    BLI_snprintf(r_label, size, "Send %d Image%s", plan.images, plan.images == 1 ? "" : "s");
  }
  else if (plan.videos > 0) {
    BLI_snprintf(r_label, size, "Send %d Video%s", plan.videos, plan.videos == 1 ? "" : "s");
  }
  else {
    BLI_strncpy(r_label, "Nothing to Send", size);
  }
}

ui::Block *render_popup_create(bContext *C, ARegion *region, void *arg)
{
  ui::Block *block = director_popup_block_begin(C, region, __func__);
  /* Multi-select: a toggle must not dismiss the popup — it closes on
   * click-outside, Esc, or the Send action below. */
  ui::block_flag_enable(block, ui::BLOCK_KEEP_OPEN);
  DirectorPopupData data;
  if (!director_popup_data_get(C, &data) || data.shot_ptr.data == nullptr) {
    director_popup_section_label(block, "No shot to export yet", 0, UI_UNIT_X * 10);
    director_popup_block_end(block);
    return block;
  }
  const Scene *scene = CTX_data_scene(C);

  const int width = director_popup_width(arg, UI_UNIT_X * 12);
  const int row_h = int(UI_UNIT_Y * 1.15f);
  const int label_h = int(UI_UNIT_Y * 0.85f);
  /* One `gap` between sections (caption to caption); half of it between
   * the rows inside a section. Widths are the bar's; only y moves. */
  const int gap = int(UI_UNIT_Y * 0.25f);
  const int inner_gap = gap / 2;
  int y = 0;

  /* Which shot, in words: "Take 2", never "T2". */
  char shot_name[128] = "";
  RNA_string_get(&data.shot_ptr, "name", shot_name);
  char heading[160];
  BLI_snprintf(heading,
               sizeof(heading),
               "%s  \xc2\xb7  Take %d",
               shot_name,
               RNA_int_get(&data.shot_ptr, "version"));
  y -= label_h;
  director_popup_section_label(block, heading, y, width);

  const bool running = RNA_boolean_get(&data.shot_ptr, "render_is_running");
  const bool export_images = RNA_boolean_get(&data.shot_ptr, "export_images");
  int stills = 0;
  for (const DirectorBeatView &beat : data.state.beats) {
    stills += int(beat.has_still);
  }

  /* ---- Keyframe images: the stills each Add Keyframe captured. ---- */
  y -= gap + row_h;
  char images_label[64];
  if (stills > 0) {
    BLI_snprintf(images_label, sizeof(images_label), "Keyframe Images (%d)", stills);
  }
  else {
    BLI_strncpy(images_label, "Keyframe Images (none yet)", sizeof(images_label));
  }
  ui::Button *images = ui::uiDefIconTextButR(block,
                                             ui::ButtonType::Toggle,
                                             ICON_IMAGE_DATA,
                                             images_label,
                                             0,
                                             y,
                                             short(width),
                                             short(row_h),
                                             &data.shot_ptr,
                                             "export_images",
                                             0,
                                             stills > 0 ?
                                                 "Add each keyframe's captured image to the "
                                                 "Moodboard" :
                                                 "Keyframes added with Add Keyframe carry an "
                                                 "image; this shot has none yet");
  director_popup_state(images, false, stills > 0);

  /* ---- Videos: which, and how big. ---- */
  y -= gap + label_h;
  director_popup_section_label(block, "Videos", y, width);
  y -= row_h;
  const int chosen_videos = draw_kind_toggles(C, block, data, running, y, width);

  y -= inner_gap + row_h;
  const int percent = RNA_int_get(&data.shot_ptr, "render_resolution_percentage");
  /* Edge to edge, as the lens popup's cells: each spans from its own edge to
   * the next one's, so integer division never leaves the last one short. */
  const int cells = int(ARRAY_SIZE(VIDEO_SIZES));
  const auto cell_x = [width, cells](const int index) { return (width * index) / cells; };
  for (int index = 0; index < cells; index++) {
    const VideoSize &size = VIDEO_SIZES[index];
    ui::Button *cell = ui::uiDefButR(block,
                                     ui::ButtonType::Row,
                                     size.name,
                                     cell_x(index),
                                     y,
                                     short(cell_x(index + 1) - cell_x(index)),
                                     short(row_h),
                                     &data.shot_ptr,
                                     "render_resolution_percentage",
                                     0,
                                     0,
                                     float(size.percent),
                                     size.tip);
    director_popup_state(cell, percent == size.percent, !running);
    /* One segmented group, lit by BUT_ACTIVE_DEFAULT like the lens cells. */
    ui::UI_mixar_cinema_row_tag(cell, ui::MixarCinemaRowKind::Segment);
  }

  /* What those choices come to — or why no video will render. */
  const SendPlan plan = send_plan(data, export_images, chosen_videos, running);
  y -= label_h;
  if (running) {
    char status[256] = "";
    RNA_string_get(&data.shot_ptr, "render_status", status);
    director_popup_section_label(block, status[0] ? status : "Rendering videos", y, width);
  }
  else if (chosen_videos > 0 && plan.videos == 0) {
    director_popup_section_label(block, "Videos need two or more keyframes", y, width);
  }
  else {
    const float fps = std::max(data.state.fps, 0.001f);
    const float duration = float(data.state.frame_end - data.state.frame_start) / fps;
    const int render_w = std::max(1, int(std::lround(scene->r.xsch * percent / 100.0)));
    const int render_h = std::max(1, int(std::lround(scene->r.ysch * percent / 100.0)));
    char summary[96];
    BLI_snprintf(summary,
                 sizeof(summary),
                 "%d \xc3\x97 %d  \xc2\xb7  %.1f s  \xc2\xb7  %g fps",
                 render_w,
                 render_h,
                 double(duration),
                 double(fps));
    director_popup_section_label(block, summary, y, width);
  }

  /* ---- The one action, named for exactly what it sends. ---- */
  y -= gap + row_h;
  char action[64];
  send_label(plan, action, sizeof(action));
  ui::Button *send = director_overlay_operator_button(
      block,
      "MIXAR_OT_director_export_to_moodboard",
      ICON_EXPORT,
      action,
      0,
      y,
      width,
      row_h,
      "Add the chosen images to the Moodboard; videos render into it in the background");
  director_overlay_disable_button(send, plan.images == 0 && plan.videos == 0);
  ui::UI_mixar_cinema_row_tag(send, ui::MixarCinemaRowKind::Action);
  ui::button_func_set(send, render_popup_close, block, nullptr);

  /* What already went: one line, not a list of file names. */
  PropertyRNA *outputs_prop = RNA_struct_find_property(&data.shot_ptr, "render_outputs");
  const int output_count = outputs_prop ?
                               RNA_property_collection_length(&data.shot_ptr, outputs_prop) :
                               0;
  if (output_count > 0) {
    y -= inner_gap + label_h;
    char sent[64];
    BLI_snprintf(sent,
                 sizeof(sent),
                 "%d video%s already on the Moodboard",
                 output_count,
                 output_count == 1 ? "" : "s");
    ui::Button *entry = ui::uiDefIconTextBut(block,
                                             ui::ButtonType::Label,
                                             ICON_FILE_MOVIE,
                                             sent,
                                             0,
                                             y,
                                             short(width),
                                             short(label_h),
                                             nullptr,
                                             std::nullopt);
    /* Caption with its film icon leading. */
    ui::UI_mixar_cinema_row_tag(entry, ui::MixarCinemaRowKind::Caption);
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
