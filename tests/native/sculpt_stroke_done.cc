// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
// SPDX-License-Identifier: GPL-2.0-or-later
// Minimal collaborators around the actual SculptPaintStroke::done definition.
#include <cassert>
#include <string>

namespace bke { struct PaintRuntime { bool draw_inverted = true; }; }
struct Brush { int sculpt_brush_type = 0; };
struct Paint { bke::PaintRuntime *runtime; Brush *brush; };
struct Sculpt { Paint paint; };
struct StrokeCache {
  struct { bool alt_smooth = false, alt_mask = false; } toggle_settings;
};
struct SculptSession { StrokeCache *cache = nullptr; };
struct ObjectRuntime { SculptSession *sculpt_session = nullptr; };
struct Object { ObjectRuntime *runtime; };
struct ViewContext { void *rv3d = nullptr; };
struct PaintModeSettings {};
enum class UpdateType { Mask, Image, Color, Position };
constexpr int SCULPT_BRUSH_TYPE_MASK = 1, SCULPT_BRUSH_TYPE_PAINT = 2;
constexpr int NC_OBJECT = 1, ND_DRAW = 2;
int textures = 0, modifiers = 0, freed = 0, undos = 0, flushes = 0, notifiers = 0;
void brush_exit_tex(Sculpt &) { ++textures; }
Brush *BKE_paint_brush(Paint *p) { return p->brush; }
void stroke_modifiers_check(int &, void *, Sculpt &, Object &, Brush *) { ++modifiers; }
void smooth_brush_toggle_off(Paint *, StrokeCache *) {}
void mask_brush_toggle_off(Paint *, StrokeCache *) {}
void MEM_delete(StrokeCache *p) { ++freed; delete p; }
void stroke_undo_end(PaintModeSettings &, Object &, Brush *) { ++undos; }
bool SCULPT_use_image_paint_brush(PaintModeSettings &, Object &) { return false; }
void flush_update_done(ViewContext &, int &, Object &, UpdateType) { ++flushes; }
void WM_event_add_notifier(void *, int, Object *) { ++notifiers; }
struct SculptPaintStroke {
  Object *object;
  Sculpt *sculpt_;
  int *depsgraph;
  ViewContext vc;
  PaintModeSettings *paint_mode_settings_;
  int *wm_;
  void *evil_C = nullptr;
  void done(bool is_cancel, bool stroke_started);
};

// PRODUCTION_FUNCTION

int main(int argc, char **argv)
{
  assert(argc == 2);
  const std::string scenario = argv[1];
  bke::PaintRuntime runtime;
  Brush brush;
  Sculpt sculpt{{&runtime, &brush}};
  SculptSession session;
  ObjectRuntime object_runtime;
  Object object{&object_runtime};
  PaintModeSettings settings;
  int context = 0;
  SculptPaintStroke stroke{&object, &sculpt, &context, {}, &settings, &context};
  const bool missing = scenario == "missing" || scenario == "missing_cancel";
  const bool empty = scenario == "empty";
  const bool cancel = scenario == "cancel" || scenario == "missing_cancel";
  const bool started = scenario != "unstarted";
  if (!missing) {
    object_runtime.sculpt_session = &session;
    if (!empty) {
      session.cache = new StrokeCache;
      session.cache->toggle_settings.alt_smooth = scenario == "smooth";
      session.cache->toggle_settings.alt_mask = scenario == "mask";
    }
  }
  stroke.done(cancel, started);
  assert(textures == 1);
  assert(session.cache == nullptr);
  const int complete = !missing && !empty;
  assert(modifiers == complete && freed == complete);
  assert(flushes == complete && notifiers == complete);
  assert(undos == (complete && !cancel && started));
  if (complete) { assert(!runtime.draw_inverted); }
}
