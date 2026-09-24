/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include <algorithm>
#include <string>
#include <vector>

#include "../interface/interface_qa_inspect.hh"
#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_main.hh"
#include "BKE_screen.hh"
#include "BLI_listbase.h"
#include "BLI_time.h"
#include "BLI_timer.h"
#include "DNA_image_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_userdef_types.h"
#include "DNA_windowmanager_types.h"
#include "ED_moodboard_attachment.hh"
#include "GPU_immediate.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"
#include "RNA_access.hh"
#include "UI_mixar_motion.hh"
#include "RNA_define.hh"
#include "WM_api.hh"
#include "WM_types.hh"
#include "mixie_attachment_geometry.hh"

namespace blender::ed::mixie {
gpu::Texture *mixie_moodboard_srgb_texture(Image *image, ImageUser *image_user);
}
namespace blender {
namespace {
using namespace ed::mixie;
constexpr int STRIPS = 32;
char timer_identity;
struct WindowIdentity {
  wmWindow *window = nullptr;
  void *ghost = nullptr;
  short x = 0, y = 0, width = 0, height = 0;
  explicit WindowIdentity(wmWindow *win = nullptr)
  {
    if (win) {
      window = win;
      ghost = win->runtime->ghostwin;
      x = win->posx;
      y = win->posy;
      width = win->sizex;
      height = win->sizey;
    }
  }
  wmWindow *live() const
  {
    if (G_MAIN) {
      for (wmWindowManager &wm : G_MAIN->wm) {
        for (wmWindow &win : wm.windows) {
          if (&win == window && win.runtime->ghostwin == ghost) {
            return &win;
          }
        }
      }
    }
    return nullptr;
  }
  bool stationary() const
  {
    const wmWindow *win = live();
    return attachment_window_visible(win) && win->posx == x && win->posy == y &&
           win->sizex == width && win->sizey == height;
  }
};
struct Flight {
  std::string image_name;
  uint32_t image_uid = 0, scene_uid = 0;
  WindowIdentity source_window, target_window;
  FlightQuad source{}, target{};
  double queued = 0, start = 0, delay = 0;
};
struct Overlay {
  WindowIdentity window;
  void *handle;
};
std::vector<Flight> flights;
std::vector<Overlay> overlays;

uintptr_t timer_id()
{
  return uintptr_t(&timer_identity);
}
Image *live_image(const Flight &flight)
{
  wmWindow *source = flight.source_window.live();
  if (!source || !source->scene || source->scene->id.session_uid != flight.scene_uid || !G_MAIN) {
    return nullptr;
  }
  /* Removal/send/deselection cancels immediately, including while waiting for
   * layout. */
  PointerRNA scene = RNA_id_pointer_create(&source->scene->id);
  if (!RNA_struct_find_property(&scene, "mixie_chat_pending_attachments")) {
    return nullptr;
  }
  bool attached = false;
  RNA_BEGIN (&scene, item, "mixie_chat_pending_attachments") {
    if (RNA_string_get(&item, "image_path") == flight.image_name &&
        RNA_boolean_get(&item, "is_moodboard"))
    {
      attached = true;
      break;
    }
  }
  RNA_END;
  if (attached) {
    for (Image &image : G_MAIN->images) {
      if (image.id.session_uid == flight.image_uid) {
        return &image;
      }
    }
  }
  return nullptr;
}
float progress(const Flight &f)
{
  /* Reduce Motion: report the flight already past its end. It is retired on the
   * next tick without ever being drawn, which is the same end state -- the
   * attachment was registered by the operator, not by the animation -- reached
   * without an image flying across the screen. */
  if (f.start && blender::ui::mixar_motion_reduced()) {
    return 2.0f;
  }
  return float((BLI_time_now_seconds() - f.start) / ATTACHMENT_FLIGHT_SECONDS);
}

void draw_flights(const wmWindow *win, void * /*data*/)
{
  const float scale = attachment_pixel_scale(win);
  for (const Flight &f : flights) {
    if (!f.start || (win != f.source_window.window && win != f.target_window.window) ||
        !f.source_window.stationary() || !f.target_window.stationary())
    {
      continue;
    }
    const float t = progress(f);
    Image *image = live_image(f);
    if (t < 0 || t >= 1 || !image) {
      continue;
    }
    gpu::Texture *texture = mixie_moodboard_srgb_texture(image, nullptr);
    if (!texture) {
      continue;
    }
    const GPUBlend blend = GPU_blend_get();
    GPU_blend(GPU_BLEND_ALPHA_PREMULT);
    GPU_texture_filter_mode(texture, true);
    GPU_texture_bind(texture, 0);
    GPUVertFormat *format = immVertexFormat();
    const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
    const uint uv = GPU_vertformat_attr_add(format, "texCoord", gpu::VertAttrType::SFLOAT_32_32);
    immBindBuiltinProgram(GPU_SHADER_3D_IMAGE_COLOR);
    const float alpha = attachment_flight_alpha(t);
    immUniformColor4f(alpha, alpha, alpha, alpha);
    immBegin(GPU_PRIM_TRIS, STRIPS * 6);
    auto vertex = [&](float x, float y) {
      const auto p = attachment_flight_vertex(f.source, f.target, x, y, t);
      immAttr2f(uv, x, y);
      immVertex2f(pos, (p[0] - win->posx) * scale, (p[1] - win->posy) * scale);
    };
    for (int row = 0; row < STRIPS; row++) {
      const float a = float(row) / STRIPS, b = float(row + 1) / STRIPS;
      vertex(0, a);
      vertex(1, a);
      vertex(1, b);
      vertex(0, a);
      vertex(1, b);
      vertex(0, b);
    }
    immEnd();
    immUnbindProgram();
    GPU_texture_unbind(texture);
    GPU_blend(blend);
  }
}

void cleanup(uintptr_t /*id*/, void * /*data*/)
{
  /* BLI runs this on expiry, file-load and shutdown, before freeing Main.
   * Closed windows are resolved by identity; never dereference a stale host. */
  for (const Overlay &overlay : overlays) {
    if (wmWindow *win = overlay.window.live()) {
      WM_draw_cb_exit(win, overlay.handle);
      if (bScreen *screen = WM_window_get_active_screen(win)) {
        screen->do_draw = true;
      }
    }
  }
  overlays.clear();
  flights.clear();
}
void ensure_overlay(wmWindow *win)
{
  for (const Overlay &overlay : overlays) {
    if (overlay.window.live() == win) {
      return;
    }
  }
  overlays.push_back({WindowIdentity(win), WM_draw_cb_activate(win, draw_flights, nullptr)});
}

double tick(uintptr_t /*id*/, void * /*data*/)
{
  const double now = BLI_time_now_seconds();
  for (Flight &f : flights) {
    if (!f.source_window.stationary() || !live_image(f)) {
      continue;
    }
    if (!f.start && !f.target_window.window && G_MAIN) {
      for (wmWindowManager &wm : G_MAIN->wm) {
        for (wmWindow &win : wm.windows) {
          if (win.scene && win.scene->id.session_uid == f.scene_uid &&
              attachment_window_visible(&win) && attachment_resting_target(&win, f.target))
          {
            f.target_window = WindowIdentity(&win);
            break;
          }
        }
      }
    }
    if (!f.start && f.target_window.stationary()) {
      f.start = now + f.delay;
      ensure_overlay(f.source_window.live());
      ensure_overlay(f.target_window.live());
    }
  }
  flights.erase(std::remove_if(flights.begin(),
                               flights.end(),
                               [&](const Flight &f) {
                                 return !f.source_window.stationary() || !live_image(f) ||
                                        (f.start ?
                                             (!f.target_window.stationary() || progress(f) > 1) :
                                             now - f.queued > 0.35);
                               }),
                flights.end());
  for (const Overlay &overlay : overlays) {
    if (wmWindow *win = overlay.window.live()) {
      WM_window_get_active_screen(win)->do_draw = true;
    }
  }
  return flights.empty() ? -1.0 : 1.0 / 60.0;
}

wmOperatorStatus start_flight(bContext *C, wmOperator *op)
{
  if (G.background || !CTX_data_scene(C)) {
    return OPERATOR_CANCELLED;
  }
  const std::string name = RNA_string_get(op->ptr, "image_name");
  Image *image = nullptr;
  for (Image &candidate : CTX_data_main(C)->images) {
    if (name == candidate.id.name + 2) {
      image = &candidate;
      break;
    }
  }
  if (!image || image->source == IMA_SRC_MOVIE || flights.size() >= 5) {
    return OPERATOR_CANCELLED;
  }
  for (const Flight &f : flights) {
    if (f.image_uid == image->id.session_uid) {
      return OPERATOR_CANCELLED;
    }
  }
  wmWindow *source = nullptr;
  Flight f;
  if (!attachment_source(C, image, &source, f.source)) {
    return OPERATOR_CANCELLED;
  }
  f.source_window = WindowIdentity(source);
  f.image_uid = image->id.session_uid;
  f.scene_uid = CTX_data_scene(C)->id.session_uid;
  f.image_name = name;
  f.queued = BLI_time_now_seconds();
  f.delay = RNA_float_get(op->ptr, "delay");
  flights.push_back(std::move(f));
  if (!BLI_timer_is_registered(timer_id())) {
    BLI_timer_register(timer_id(), tick, nullptr, cleanup, 0.025, false);
  }
  return OPERATOR_FINISHED;
}

void qa_targets(const wmWindow *win,
                const ScrArea * /*area*/,
                const ARegion *region,
                std::vector<MixarQATarget> &targets)
{
  if (region->regiontype != RGN_TYPE_WINDOW) {
    return;
  }
  for (const Flight &f : flights) {
    if (win != f.source_window.window || !f.start) {
      continue;
    }
    const float t = progress(f);
    if (t < 0 || t >= 1) {
      continue;
    }
    rctf bounds{1e20f, -1e20f, 1e20f, -1e20f};
    const float scale = attachment_pixel_scale(win);
    for (int row = 0; row <= STRIPS; row++) {
      for (int x = 0; x <= 1; x++) {
        auto p = attachment_flight_vertex(f.source, f.target, x, float(row) / STRIPS, t);
        p[0] = (p[0] - win->posx) * scale;
        p[1] = (p[1] - win->posy) * scale;
        BLI_rctf_do_minmax_v(&bounds, p.data());
      }
    }
    MixarQATarget target;
    target.surface = "moodboard_attachment_flight";
    target.text = f.image_name;
    target.value = std::to_string(t);
    target.enabled = false;
    BLI_rcti_rctf_copy(&target.rect_win, &bounds);
    targets.push_back(std::move(target));
  }
}
}  // namespace

void ED_moodboard_attachment_target(const bContext *C,
                                    ARegion *region,
                                    const char *image_name,
                                    const rctf &rect)
{
  for (Flight &f : flights) {
    if (f.start || f.image_name != image_name || !CTX_data_scene(C) ||
        CTX_data_scene(C)->id.session_uid != f.scene_uid)
    {
      continue;
    }
    wmWindow *win = CTX_wm_window(C);
    if (!attachment_window_visible(win)) {
      continue;
    }
    /* Shrink into the center of the actual painted thumbnail slot. */
    const float half = std::min(16 * attachment_pixel_scale(win),
                                std::min(BLI_rctf_size_x(&rect), BLI_rctf_size_y(&rect)) / 2);
    const float x = region->winrct.xmin + BLI_rctf_cent_x(&rect);
    const float y = region->winrct.ymin + BLI_rctf_cent_y(&rect);
    f.target = attachment_desktop_quad(win, {x - half, x + half, y - half, y + half});
    f.target_window = WindowIdentity(win);
  }
}

void MIXIE_OT_moodboard_attachment_flight(wmOperatorType *ot)
{
  ot->name = "Animate Moodboard Attachment";
  ot->idname = "MIXIE_OT_moodboard_attachment_flight";
  ot->description = "Show a newly attached reference flying into Mixie Chat";
  ot->exec = start_flight;
  ot->flag = OPTYPE_INTERNAL;
  RNA_def_property_flag(RNA_def_string(ot->srna, "image_name", nullptr, 0, "Image", ""),
                        PROP_SKIP_SAVE);
  RNA_def_property_flag(RNA_def_float(ot->srna, "delay", 0, 0, 0.3, "Delay", "", 0, 0.3),
                        PROP_SKIP_SAVE);
}
void mixie_attachment_qa_register()
{
  Mixar_qa_register_target_provider(SPACE_MIXIE, qa_targets);
  Mixar_qa_register_target_provider(SPACE_VIEW3D, qa_targets);
}

bool ED_moodboard_attachment_incoming(const wmWindow *target, MixieAttachmentIncoming &r_incoming)
{
  int best = -1;
  double best_arrival = 0.0;
  for (int i = 0; i < int(flights.size()); i++) {
    const Flight &f = flights[size_t(i)];
    if (!target || !f.start || f.target_window.window != target || !live_image(f)) {
      continue;
    }
    const float t = progress(f);
    if (t > 1.0f) {
      continue;
    }
    const double arrival = f.start + ed::mixie::ATTACHMENT_FLIGHT_SECONDS;
    if (best < 0 || arrival < best_arrival) {
      best = i;
      best_arrival = arrival;
    }
  }
  if (best < 0) {
    return false;
  }
  const Flight &f = flights[size_t(best)];
  const float t = std::clamp(progress(f), 0.0f, 1.0f);
  const ed::mixie::FlightPoint pos = ed::mixie::attachment_flight_vertex(
      f.source, f.target, 0.5f, 0.5f, t);
  const ed::mixie::FlightPoint land = ed::mixie::attachment_flight_vertex(
      f.source, f.target, 0.5f, 0.5f, 1.0f);
  r_incoming.progress = progress(f);
  r_incoming.position[0] = pos[0];
  r_incoming.position[1] = pos[1];
  r_incoming.target[0] = land[0];
  r_incoming.target[1] = land[1];
  r_incoming.start = f.start;
  r_incoming.arrival = best_arrival;
  return true;
}
}  // namespace blender
