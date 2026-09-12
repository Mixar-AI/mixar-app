/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Painting for the Zen Mode sliding moodboard drawer: the panel chrome, the
 * moodboard canvas at its current slide offset, and the grip on its leading
 * edge.
 *
 * Geometry comes from `view3d_moodboard_drawer.hh` and is not re-derived here;
 * nothing here resizes or re-adds a region either, since a draw pass has this
 * region's framebuffer bound and is iterating `area->regionbase` (the Agent
 * Bubble footer crash class).
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLI_rect.h"

#include "BKE_context.hh"
#include "BLF_api.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_userdef_types.h"

#include "ED_screen.hh"

#include "GPU_framebuffer.hh"
#include "GPU_immediate.hh"
#include "GPU_state.hh"
#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "mixie_moodboard_canvas.hh"

#include "view3d_moodboard_drawer.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* Match the editor's opaque black canvas, framed as a Mixar overlay. */
constexpr float DRAWER_FILL[4] = {0.0f, 0.0f, 0.0f, 1.0f};
constexpr float DRAWER_FILL_EDGE[4] = {0.0f, 0.0f, 0.0f, 1.0f};
constexpr float DRAWER_BORDER[4] = {0.180f, 0.478f, 0.278f, 0.55f};

constexpr float GRIP_FILL[4] = {0.086f, 0.106f, 0.098f, 0.96f};
constexpr float GRIP_BORDER[4] = {0.220f, 0.760f, 0.400f, 0.70f};
constexpr float GRIP_DOT[4] = {0.62f, 0.68f, 0.64f, 0.92f};

void clear_tab_gutter(const int width, const int height)
{
  /* Draw transparent pixels without blending: attachment clears are not
   * scissor-limited on every GPU backend. */
  GPU_blend(GPU_BLEND_NONE);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4f(0.0f, 0.0f, 0.0f, 0.0f);
  immRectf(pos, 0.0f, 0.0f, float(width), float(height));
  immUnbindProgram();
  GPU_blend(GPU_BLEND_ALPHA);
}

void draw_empty_hint(const bContext *C, const ARegion *region, const int offset)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return;
  }
  PointerRNA ptr = RNA_id_pointer_create(&scene->id);
  for (const char *name : {"mixie_moodboard_images", "mixie_moodboard_action_nodes",
                           "mixie_moodboard_textboxes"})
  {
    PropertyRNA *prop = RNA_struct_find_property(&ptr, name);
    if (prop && RNA_property_collection_length(&ptr, prop) > 0) {
      return;
    }
  }
  const int font = BLF_default();
  BLF_size(font, 13.0f * UI_SCALE_FAC);
  const char *label = "Drop references here";
  const float color[4] = {0.62f, 0.68f, 0.64f, 1.0f};
  BLF_color4fv(font, color);
  BLF_position(font,
               offset + 0.5f * (region->winx - BLF_width(font, label, strlen(label))),
               0.5f * region->winy,
               0.0f);
  BLF_draw(font, label, strlen(label));
}

/** Paint the edge grip with its right edge at `x_right`, in region-local
 * pixels. Three dots rather than a glyph: the affordance should read as
 * something to pull, not as a button to press. */
void draw_grip(const float x_right, const float y_centre)
{
  const float scale = UI_SCALE_FAC;
  const float grip_w = VIEW3D_MOODBOARD_DRAWER_GRIP_WIDTH * scale;
  const float grip_h = VIEW3D_MOODBOARD_DRAWER_GRIP_HEIGHT * scale;
  const float x_left = x_right - grip_w;

  rctf bar;
  bar.xmin = x_left;
  bar.xmax = x_right;
  bar.ymin = y_centre - grip_h * 0.5f;
  bar.ymax = y_centre + grip_h * 0.5f;

  ui::draw_roundbox_corner_set(ui::CNR_TOP_LEFT | ui::CNR_BOTTOM_LEFT);
  ui::draw_roundbox_4fv_ex(&bar,
                           GRIP_FILL,
                           GRIP_FILL,
                           /*shade_dir*/ 0.0f,
                           GRIP_BORDER,
                           U.pixelsize,
                           grip_w * 0.5f);

  const float dot_r = 2.0f * scale;
  const float dot_gap = 9.0f * scale;
  const float centre_x = 0.5f * (x_left + x_right);
  for (int i = -1; i <= 1; i++) {
    const float dot_y = y_centre + float(i) * dot_gap;
    rctf dot;
    dot.xmin = centre_x - dot_r;
    dot.xmax = centre_x + dot_r;
    dot.ymin = dot_y - dot_r;
    dot.ymax = dot_y + dot_r;
    ui::draw_roundbox_4fv_ex(
        &dot, GRIP_DOT, GRIP_DOT, 0.0f, GRIP_DOT, U.pixelsize, dot_r);
  }
}

}  // namespace

void view3d_moodboard_drawer_region_draw(const bContext *C, ARegion *region)
{
  if (!view3d_moodboard_drawer_zen_active(C)) {
    return;
  }

  const float amount = view3d_moodboard_drawer_display_amount(C);

  /* The QA provider runs with no context of its own, so it can only read this
   * region. Caching the amount the pass actually used is what lets it report
   * the grip where the user sees it. */
  MoodboardDrawerRuntime *runtime = static_cast<MoodboardDrawerRuntime *>(region->regiondata);
  if (runtime) {
    runtime->amount = amount;
  }

  if (region->overlap) {
    /* Transparent background: the viewport extends behind this region and the
     * strip the drawer has not covered yet has to show it through. */
    GPU_clear_color(0.0f, 0.0f, 0.0f, 0.0f);
  }
  else {
    /* Region overlap disabled in the preferences — docked opaque, so fall back
     * to the editor background. */
    ui::theme::frame_buffer_clear(TH_BACK);
  }

  ED_region_pixelspace(region);
  GPU_blend(GPU_BLEND_ALPHA);

  const int winx = region->winx;
  const int winy = region->winy;
  if (winx <= 0 || winy <= 0) {
    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  const float scale = UI_SCALE_FAC;

  /* The grip rides the panel's leading edge, and it is placed from the same
   * expression the hit test and the QA provider use — converted out of window
   * space with this region's own `winrct`, so a 1-pixel disagreement between
   * the region and the area cannot make the handle drift away from the pixels
   * that answer a click. */
  float grip_right = float(winx);
  float grip_centre_y = 0.5f * float(winy);
  const ScrArea *area = CTX_wm_area(C);
  rcti grip_win;
  if (area && view3d_moodboard_drawer_grip_rect_for(area, region, amount, &grip_win)) {
    grip_right = float(grip_win.xmax - region->winrct.xmin);
    grip_centre_y = 0.5f * float((grip_win.ymin - region->winrct.ymin) +
                                 (grip_win.ymax - region->winrct.ymin));
  }

  rcti panel_win;
  const bool panel_visible = view3d_moodboard_drawer_panel_rect_for(
      area, region, amount, &panel_win);
  /* The body begins at the tab's flat inner edge. Reserving this gutter
   * inside the overlap region lets the tab protrude without clipping it. */
  const float open_panel_xmin = (VIEW3D_MOODBOARD_DRAWER_PAD +
                                 VIEW3D_MOODBOARD_DRAWER_GRIP_WIDTH) * scale;
  const float off = std::max(0.0f, grip_right - open_panel_xmin);

  if (panel_visible) {
    /* Clip to the part of the panel that has already slid in. REGION-LOCAL
     * coordinates: each region draws into its own framebuffer whose origin is
     * the region's corner (`wm_draw_region_bind` scissors to `0, 0, winx,
     * winy`), so offsetting by `winrct` would put the box outside it and clip
     * everything away, with nothing drawn and no error. Restored below — the
     * scissor is state the rest of the frame relies on. */
    int scissor_prev[4];
    GPU_scissor_get(scissor_prev);
    const int panel_xmin = panel_win.xmin - region->winrct.xmin;
    GPU_scissor(panel_xmin, 0, winx - panel_xmin, winy);

    rctf panel;
    panel.xmin = panel_xmin;
    panel.xmax = float(winx);
    panel.ymin = 0.0f;
    panel.ymax = float(winy);

    /* Rounded left edge, square right edge: the drawer meets the area's edge,
     * so only the face it slides in from should look like a card. */
    const float radius = std::min(VIEW3D_MOODBOARD_DRAWER_RADIUS * scale,
                                  0.5f * (panel.xmax - panel.xmin));
    ui::draw_roundbox_corner_set(ui::CNR_TOP_LEFT | ui::CNR_BOTTOM_LEFT);
    ui::draw_roundbox_4fv_ex(&panel,
                             /*inner1 (right)*/ DRAWER_FILL,
                             /*inner2 (left)*/ DRAWER_FILL_EDGE,
                             /*shade_dir*/ 0.0f,
                             DRAWER_BORDER,
                             U.pixelsize,
                             radius);

    /* `mixie_moodboard_region_set_view2d()` rebuilds `cur` around the centre it
     * is handed, so shifting the centre here slides the whole canvas — grid,
     * links, images, graph nodes — as one piece. The region keeps its width, so
     * the zoom ratio it derives from `winrct` is untouched and only the
     * translation survives. */
    const rctf saved_cur = region->v2d.cur;
    const float span = BLI_rctf_size_x(&saved_cur);
    const float delta = span > 0.0f ? float(off) * (span / float(winx)) : 0.0f;
    if (span > 0.0f) {
      region->v2d.cur.xmin = saved_cur.xmin - delta;
      region->v2d.cur.xmax = saved_cur.xmax - delta;
    }
    ed::mixie::mixie_moodboard_canvas_draw(C, region);
    /* Undo only the slide. Keep the canvas's aspect/zoom correction so its
     * pixels, click targets and drop coordinates use the very same View2D. */
    region->v2d.cur.xmin += delta;
    region->v2d.cur.xmax += delta;
    ED_region_pixelspace(region);
    GPU_scissor(panel_xmin, 0, winx - panel_xmin, winy);
    draw_empty_hint(C, region, panel_xmin);

    /* View2D scrollers/inline controls can widen the scissor. Keep the
     * gutter transparent above and below the protruding tab. */
    ED_region_pixelspace(region);
    GPU_scissor(0, 0, panel_xmin, winy);
    clear_tab_gutter(panel_xmin, winy);

    /* Restore the region scissor before painting the tab outside the body. */
    GPU_scissor(scissor_prev[0], scissor_prev[1], scissor_prev[2], scissor_prev[3]);
    ED_region_pixelspace(region);
    draw_grip(grip_right, grip_centre_y);
  }
  else {
    /* Shut, or nearly: the panel has nothing on screen, but the grip does.
     * That handle is the whole way back in, so it is painted in both states. */
    draw_grip(grip_right, grip_centre_y);
  }

  GPU_blend(GPU_BLEND_NONE);
}

}  // namespace blender
