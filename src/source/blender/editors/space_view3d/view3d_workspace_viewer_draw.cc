/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include <algorithm>
#include <cmath>
#include "BLF_api.hh"
#include "BKE_context.hh"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "GPU_framebuffer.hh"
#include "GPU_immediate.hh"
#include "GPU_state.hh"
#include "GPU_viewport.hh"
#include "ED_screen.hh"
#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "../interface/interface_qa_inspect.hh"
#include "../space_agent_bubble/agent_ui_pill_cat.hh"
#include "view3d_agent_panel.hh"
#include "view3d_workspace_viewer.hh"

namespace blender {
namespace {
void corner_masks(const rctf &rect, const float radius, const float top[4], const float bottom[4])
{
  constexpr int segments = 8;
  uint pos = GPU_vertformat_attr_add(
      immVertexFormat(), "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  const struct {
    float cx, cy; /* The square corner. */
    float ax, ay; /* The arc centre. */
    float a0;     /* Arc start angle; it sweeps a quarter turn. */
    const float *col;
  } corners[4] = {
      {rect.xmin, rect.ymin, rect.xmin + radius, rect.ymin + radius, float(M_PI), bottom},
      {rect.xmax, rect.ymin, rect.xmax - radius, rect.ymin + radius, float(M_PI * 1.5), bottom},
      {rect.xmax, rect.ymax, rect.xmax - radius, rect.ymax - radius, 0.0f, top},
      {rect.xmin, rect.ymax, rect.xmin + radius, rect.ymax - radius, float(M_PI * 0.5), top},
  };
  for (const auto &corner : corners) {
    const float col[4] = {corner.col[0], corner.col[1], corner.col[2], 1.0f};
    immUniformColor4fv(col);
    immBegin(GPU_PRIM_TRI_FAN, segments + 2);
    immVertex2f(pos, corner.cx, corner.cy);
    for (int i = 0; i <= segments; i++) {
      const float angle = corner.a0 + float(M_PI * 0.5) * float(i) / float(segments);
      immVertex2f(pos, corner.ax + radius * cosf(angle), corner.ay + radius * sinf(angle));
    }
    immEnd();
  }
  immUnbindProgram();
}

void fill(const rcti &rect, float radius, const float color[4])
{
  rctf box = {float(rect.xmin), float(rect.xmax), float(rect.ymin), float(rect.ymax)};
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&box, true, radius, color);
}
void label(const std::string &text, float x, float y, float width, const float color[4])
{
  const int font = BLF_default();
  BLF_size(font, 12 * UI_SCALE_FAC);
  std::string shown = text;
  if (BLF_width(font, text.c_str(), text.size()) > width) {
    float measured;
    const size_t fit = BLF_width_to_strlen(font, text.c_str(), text.size(),
        std::max(0.0f, width - BLF_width(font, "…", 3)), &measured);
    shown = text.substr(0, fit) + "…";
  }
  BLF_color4fv(font, color);
  BLF_position(font, x, y, 0);
  BLF_draw(font, shown.c_str(), shown.size());
}
void layout(WorkspaceViewer &v)
{
  const float u = UI_SCALE_FAC;
  const int w = v.region->winx, h = v.region->winy;
  const float width = std::max(160.0f * u, std::min(w * .70f, 960.0f * u));
  const float height = std::min(width * .54f, h * .66f);
  const int left = int((w-width)*.5f), bottom = int((h-height-56*u)*.5f);
  BLI_rcti_init(&v.image, left, int(left+width), bottom, int(bottom+height));
  const int top = int(v.image.ymax+54*u), low = int(v.image.ymax+18*u);
  BLI_rcti_init(&v.close, int(left+width-32*u), int(left+width), low, top);
  const int available = int(width-42*u);
  const float tab_w = std::max(150*u, (available-72*u)/3.0f);
  const float step = tab_w+12*u;
  const bool overflow = int(v.tabs.size())*step-12*u > available;
  const int inset = overflow ? int(24*u) : 0;
  BLI_rcti_init(&v.bar, left+inset, left+available-inset, low, top);
  v.previous = v.next = {};
  if (overflow) {
    BLI_rcti_init(&v.previous, left, v.bar.xmin-1, low, top);
    BLI_rcti_init(&v.next, v.bar.xmax+1, left+available, low, top);
  }
  v.scroll_max = std::max(0.0f, int(v.tabs.size())*step-12*u-BLI_rcti_size_x(&v.bar));
  if (v.reveal_selection) {
    for (int i=0; i<v.tabs.size(); ++i) {
      if (v.tabs[i].task_id == v.task_id) { v.scroll = i*step; break; }
    }
    v.reveal_selection = false;
  }
  v.scroll = std::clamp(v.scroll, 0.0f, v.scroll_max);
  for (int i=0; i<v.tabs.size(); ++i) {
    const int x = int(v.bar.xmin+i*step-v.scroll);
    BLI_rcti_init(&v.tabs[i].rect, x, int(x+tab_w), low, top);
  }
}
void targets(const wmWindow *, const ScrArea *, const ARegion *region,
             std::vector<MixarQATarget> &out)
{
  auto *v = view3d_workspace_viewer_active();
  if (!v || v->region != region) { return; }
  auto push = [&](const rcti &rect, const char *surface, const std::string &text,
                  const std::string &value) {
    MixarQATarget t;
    t.rect_win = rect;
    BLI_rcti_translate(&t.rect_win, region->winrct.xmin, region->winrct.ymin);
    t.surface = surface; t.text = text; t.value = value;
    out.push_back(std::move(t));
  };
  push(v->image, "workspace_viewer_scene", v->task_id,
       v->has_render ? std::to_string(v->frame_count) : "unavailable");
  push(v->bar, "workspace_viewer_bar", "Agents", "");
  push(v->close, "workspace_viewer_close", "Close preview", "");
  if (v->scroll_max > 0) {
    push(v->previous, "workspace_viewer_previous", "Previous agents", "");
    push(v->next, "workspace_viewer_next", "More agents", "");
  }
  for (const auto &tab : v->tabs) {
    rcti clipped;
    if (BLI_rcti_isect(&tab.rect, &v->bar, &clipped)) {
      push(clipped, "workspace_viewer_agent", tab.task_id,
           !tab.available ? "unavailable" : tab.task_id == v->task_id ? "selected" : "available");
    }
  }
}
}  // namespace
void view3d_workspace_viewer_draw(const bContext *C, ARegion *region, void *data)
{
  auto &v = *static_cast<WorkspaceViewer *>(data);
  if (v.region != region) { return; }
  layout(v);
  Scene *scene = view3d_workspace_scene(CTX_data_main(C), CTX_data_scene(C), v.task_id);
  if (!scene) { v.has_render = false; }
  else { view3d_workspace_viewer_render(C, v, scene); }
  ED_region_pixelspace(region);
  GPU_blend(GPU_BLEND_ALPHA);
  const float u = UI_SCALE_FAC;
  const float dim[4] = {.012f,.016f,.014f,.87f};
  const float bed[4] = {.035f,.042f,.039f,1};
  const float white[4] = {.82f,.85f,.83f,1};
  const float muted[4] = {.39f,.43f,.40f,1};
  const float green[4] = {.025f,.16f,.075f,1};
  rcti full = {0, region->winx, 0, region->winy};
  fill(full, 0, dim);
  fill(v.image, 18*u, bed);
  if (v.has_render) {
    GPU_viewport_draw_to_screen_ex(v.viewport, 0, &v.image, true, true);
    const rctf image = {float(v.image.xmin), float(v.image.xmax),
                        float(v.image.ymin), float(v.image.ymax)};
    corner_masks(image, 18*u, dim, dim);
  }
  else {
    const char *message = !scene ? "This workspace is no longer available" :
                          v.render_failed ? "Preview unavailable. Close and reopen to retry." :
                                            "Waiting for the workspace preview…";
    label(message, v.image.xmin+24*u, BLI_rcti_cent_y(&v.image),
          BLI_rcti_size_x(&v.image)-48*u, muted);
  }
  // Use exactly the layout's clipping rectangle for drawing, hit tests and QA.
  int old_scissor[4]; GPU_scissor_get(old_scissor);
  GPU_scissor_test(true);
  GPU_scissor(v.bar.xmin, v.bar.ymin, BLI_rcti_size_x(&v.bar)+1, BLI_rcti_size_y(&v.bar)+1);
  for (const auto &tab : v.tabs) {
    rcti visible;
    if (!BLI_rcti_isect(&tab.rect, &v.bar, &visible)) { continue; }
    const bool selected = tab.task_id == v.task_id;
    fill(tab.rect, 9*u, selected ? green : bed);
    GPU_blend(GPU_BLEND_ALPHA);
    rctf cat = {float(tab.rect.xmin+3*u), float(tab.rect.xmin+35*u),
                 float(tab.rect.ymin+2*u), float(tab.rect.ymax-2*u)};
    agent_ui_draw_cat(cat, 1.0, false, tab.ordinal, tab.available ? 1 : .45f);
    label(tab.name, tab.rect.xmin+40*u, tab.rect.ymin+12*u,
          BLI_rcti_size_x(&tab.rect)-72*u, tab.available ? white : muted);
    if (tab.available) {
      rcti eye = {int(tab.rect.xmax-25*u), int(tab.rect.xmax-9*u),
                   int(tab.rect.ymin+10*u), int(tab.rect.ymax-10*u)};
      view3d_agent_panel_glyph_eye(eye, u, white);
    }
  }
  GPU_scissor(old_scissor[0], old_scissor[1], old_scissor[2], old_scissor[3]);
  GPU_scissor_test(false);
  rcti close_glyph = v.close;
  BLI_rcti_pad(&close_glyph, -9*u, -9*u);
  view3d_agent_panel_glyph_cross(close_glyph, u, white);
  if (v.scroll_max > 0) {
    label("‹", v.previous.xmin+5*u, v.previous.ymin+11*u, 18*u, v.scroll > 0 ? white : muted);
    label("›", v.next.xmin+5*u, v.next.ymin+11*u, 18*u, v.scroll < v.scroll_max ? white : muted);
  }
  GPU_blend(GPU_BLEND_NONE);
}
void view3d_workspace_viewer_qa_register()
{
  Mixar_qa_register_target_provider(SPACE_VIEW3D, targets);
}
}  // namespace blender
