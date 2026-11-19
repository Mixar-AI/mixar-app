// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
// SPDX-License-Identifier: GPL-2.0-or-later
// Minimal collaborators around the actual stroke_lost_session definition.
#include <cassert>
#include <cstdio>
#include <string>

enum eObjectMode {
  OB_MODE_OBJECT = 0,
  OB_MODE_EDIT = 1 << 0,
  OB_MODE_SCULPT = 1 << 1,
  OB_MODE_VERTEX_PAINT = 1 << 2,
  OB_MODE_WEIGHT_PAINT = 1 << 3,
  OB_MODE_TEXTURE_PAINT = 1 << 4,
};
struct StrokeCache {};
struct SculptSession { StrokeCache *cache = nullptr; };
struct ObjectRuntime { SculptSession *sculpt_session = nullptr; };
struct Object { ObjectRuntime *runtime; short mode = OB_MODE_SCULPT; };
struct SculptPaintStroke {
  Object *object;
  StrokeCache *cache_ = nullptr;
};

// PRODUCTION_FUNCTION

int main(int argc, char **argv)
{
  assert(argc == 2);
  const std::string scenario = argv[1];
  StrokeCache started_cache, other_cache;
  SculptSession session;
  ObjectRuntime object_runtime{&session};
  Object object{&object_runtime};
  SculptPaintStroke stroke{&object, &started_cache};
  session.cache = &started_cache;
  if (scenario == "missing") {
    object_runtime.sculpt_session = nullptr;
  }
  else if (scenario == "object_mode") {
    object.mode = OB_MODE_OBJECT;
  }
  else if (scenario == "texture_paint") {
    object_runtime.sculpt_session = nullptr;
    object.mode = OB_MODE_TEXTURE_PAINT;
  }
  else if (scenario == "vertex_paint" || scenario == "weight_paint") {
    session.cache = nullptr;
    object.mode = scenario == "vertex_paint" ? OB_MODE_VERTEX_PAINT : OB_MODE_WEIGHT_PAINT;
  }
  else if (scenario == "round_trip") {
    session.cache = nullptr;
  }
  else if (scenario == "round_trip_unstarted") {
    stroke.cache_ = nullptr;
    session.cache = nullptr;
  }
  else if (scenario == "other_cache") {
    session.cache = &other_cache;
  }
  else if (scenario == "unstarted") {
    stroke.cache_ = nullptr;
  }
  else {
    assert(scenario == "same");
  }
  std::printf("%s", stroke_lost_session(stroke) ? "lost" : "kept");
  return 0;
}
