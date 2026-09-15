/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Painting for the Zen Mode sliding moodboard drawer: the panel chrome, the
 * moodboard canvas at its current slide offset, and the labeled tab on its
 * leading edge.
 *
 * Geometry comes from `view3d_moodboard_drawer.hh` and is not re-derived here;
 * nothing here resizes or re-adds a region either, since a draw pass has this
 * region's framebuffer bound and is iterating `area->regionbase` (the Agent
 * Bubble footer crash class).
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLI_math_base.h"
#include "BLI_rect.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"
#include "BLF_api.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_userdef_types.h"

#include "ED_mixar_glass.hh"
#include "ED_screen.hh"

#include "GPU_framebuffer.hh"
#include "GPU_immediate.hh"
#include "GPU_state.hh"
#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_layout.hh"
#include "UI_resources.hh"

#include "WM_api.hh"

#include "mixie_moodboard_canvas.hh"

#include "view3d_moodboard_drawer.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* Match the editor's opaque black canvas, framed as a Mixar overlay.
 * The rim is the moodboard glass row's resting stroke, not brand green. */
constexpr float DRAWER_FILL[4] = {0.0f, 0.0f, 0.0f, 1.0f};
constexpr float DRAWER_FILL_EDGE[4] = {0.0f, 0.0f, 0.0f, 1.0f};
constexpr float DRAWER_BORDER[4] = {0.380f, 0.390f, 0.420f, 0.58f};

constexpr float TAB_LABEL[4] = {0.94f, 0.96f, 0.94f, 1.0f};
constexpr float EMPTY_HINT[4] = {0.55f, 0.56f, 0.58f, 1.0f};

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

void draw_centered_line(const int font,
                        const char *text,
                        const float cx,
                        const float y,
                        const float color[4])
{
  BLF_color4fv(font, color);
  BLF_position(font, cx - 0.5f * BLF_width(font, text, strlen(text)), y, 0.0f);
  BLF_draw(font, text, strlen(text));
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

  /* Empty-canvas LEFTMOUSE still deselects and starts box-select (or
   * passes through to Mixie). Add is drop, the Open Image/Video menu,
   * paste, or Cmd/Ctrl+I — never a click on this hint. Do not paint a
   * plus or "click anywhere" copy; both read as a control that is not
   * there. */
  const float cx = float(offset) + 0.5f * float(region->winx - offset);
  const float cy = 0.5f * float(region->winy);
  const int font = BLF_default();
  BLF_size(font, 13.0f * UI_SCALE_FAC);
  draw_centered_line(font, "Drop references here", cx, cy, EMPTY_HINT);
}

/** Paint the labeled Moodboard tab with its flat inner edge at `x_right`. */
void draw_grip(const float x_right, const float y_centre)
{
  const float scale = UI_SCALE_FAC;
  const float grip_w = VIEW3D_MOODBOARD_DRAWER_GRIP_WIDTH * scale;
  const float grip_h = VIEW3D_MOODBOARD_DRAWER_GRIP_HEIGHT * scale;
  const float x_left = x_right - grip_w;
  const float radius = grip_w * 0.5f;

  rcti pane;
  pane.xmin = int(std::floor(x_left));
  pane.xmax = int(std::ceil(x_right + radius));
  pane.ymin = int(std::floor(y_centre - grip_h * 0.5f));
  pane.ymax = int(std::ceil(y_centre + grip_h * 0.5f));

  int scissor_prev[4];
  GPU_scissor_get(scissor_prev);
  const int clip_w = int(std::ceil(x_right)) - pane.xmin;
  if (clip_w > 0 && BLI_rcti_size_y(&pane) > 0) {
    GPU_scissor(pane.xmin, pane.ymin, clip_w, BLI_rcti_size_y(&pane));
    ui::MixarGlassStyle style;
    style.role = ui::MIXAR_GLASS_MOODBOARD_TAB;
    style.radius = radius;
    style.draw_shadow = false;
    style.draw_specular = false;
    ui::mixar_glass_draw(pane, style);
  }
  GPU_scissor(scissor_prev[0], scissor_prev[1], scissor_prev[2], scissor_prev[3]);

  const int font = BLF_default();
  BLF_size(font, 12.0f * scale);
  const char *label = "Moodboard";
  const size_t label_len = strlen(label);
  const float text_w = BLF_width(font, label, label_len);
  const float text_h = BLF_height_max(font);
  BLF_color4fv(font, TAB_LABEL);
  BLF_enable(font, BLF_ROTATION);
  BLF_rotation(font, float(M_PI_2));
  BLF_position(font,
               0.5f * (x_left + x_right) + text_h * 0.32f,
               y_centre - text_w * 0.5f,
               0.0f);
  BLF_draw(font, label, label_len);
  BLF_rotation(font, 0.0f);
  BLF_disable(font, BLF_ROTATION);
}

/** Host the Python add-media / add-text row on the open drawer.
 *
 * The Mixie T-panel builds those controls in
 * `moodboard_toolbar.draw_moodboard_add_tools`; this path draws the same
 * `VIEW3D_PT_moodboard_drawer_add_tools` panel into a pixel-space block so the
 * drawer View2D (canvas pan/zoom) is never rewritten by `ED_region_panels`. */
void draw_add_tools(const bContext *C, ARegion *region, const int panel_xmin)
{
  if (view3d_moodboard_drawer_display_amount(C) < VIEW3D_MOODBOARD_DRAWER_CANVAS_MIN_AMOUNT) {
    return;
  }
  PanelType *pt = WM_paneltype_find("VIEW3D_PT_moodboard_drawer_add_tools", false);
  if (pt == nullptr || (pt->poll && !pt->poll(C, pt))) {
    return;
  }

  const float scale = UI_SCALE_FAC;
  const int pad = int(std::round(6.0f * scale));
  const int x = panel_xmin + pad;
  const int y = region->winy - pad;
  const int width = int(std::round(40.0f * scale));

  ui::Block *block = ui::block_begin(
      C, region, "moodboard_drawer_add_tools", ui::EmbossType::Emboss);
  ui::Layout &layout = ui::block_layout(block,
                                        ui::LayoutDirection::Vertical,
                                        ui::LayoutType::Panel,
                                        x,
                                        y,
                                        width,
                                        0,
                                        0,
                                        ui::style_get_dpi());
  ui::UI_paneltype_draw(const_cast<bContext *>(C), pt, &layout);
  ui::block_layout_resolve(block);
  ui::block_end(C, block);
  ui::block_draw(C, block);
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
    draw_add_tools(C, region, panel_xmin);

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
