/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "RE_mixar_visibility.hh"
#include "RE_pipeline.h"
#include "DNA_scene_types.h"

#include <map>
#include <mutex>
#include <sstream>

namespace {
/* Only the latest operation is retained. No Blender pointers are dereferenced after rendering. */
struct Capture {
  const Render *render = nullptr;
  uint32_t scene_uid = 0;
  uint64_t generation = 0;
  int frame = 0;
  int samples = 0;
  std::string status = "disabled";
  std::string error;
  std::map<uint32_t, MixarVisibleObject> objects;
};
std::mutex capture_mutex;
Capture capture;

std::string quoted(const std::string &value)
{
  std::string result = "\"";
  constexpr char hex[] = "0123456789abcdef";
  for (unsigned char ch : value) {
    if (ch == '"' || ch == '\\') {
      result += '\\';
      result += char(ch);
    }
    else if (ch < 32) {
      result += "\\u00";
      result += hex[ch >> 4];
      result += hex[ch & 15];
    }
    else {
      result += char(ch);
    }
  }
  return result + '"';
}
}  // namespace

void RE_mixar_visibility_begin(Render *render, const Scene *scene, bool enabled)
{
  std::lock_guard lock(capture_mutex);
  const uint64_t generation = capture.generation + 1;
  capture = {};
  capture.render = render;
  capture.scene_uid = scene->id.session_uid;
  capture.generation = generation;
  capture.frame = scene->r.cfra;
  capture.status = enabled ? "capturing" : "disabled";
}

bool RE_mixar_visibility_enabled(const Render *render)
{
  std::lock_guard lock(capture_mutex);
  return render && capture.render == render && capture.status == "capturing";
}

void RE_mixar_visibility_add(Render *render, const MixarVisibleObject &object)
{
  std::lock_guard lock(capture_mutex);
  if (capture.render == render && capture.status == "capturing") {
    capture.objects.insert_or_assign(object.session_uid, object);
  }
}

void RE_mixar_visibility_sample(Render *render)
{
  std::lock_guard lock(capture_mutex);
  if (capture.render == render && capture.status == "capturing") {
    capture.samples++;
  }
}

void RE_mixar_visibility_fail(Render *render, const char *message)
{
  std::lock_guard lock(capture_mutex);
  if (capture.render == render && capture.status == "capturing") {
    capture.status = "error";
    capture.error = message;
    capture.objects.clear();
  }
}

void RE_mixar_visibility_finish(Render *render, bool cancelled)
{
  RenderResult *rr = RE_AcquireResultRead(render);
  const std::string error = (rr && rr->error) ? rr->error : "";
  const bool missing_result = rr == nullptr;
  RE_ReleaseResult(render);
  std::lock_guard lock(capture_mutex);
  if (capture.render != render || capture.status != "capturing") {
    return;
  }
  if (cancelled || missing_result || !error.empty() || capture.samples == 0) {
    capture.status = cancelled ? "cancelled" : "error";
    capture.error = error.empty() ? "Render did not complete visibility capture" : error;
    capture.objects.clear();
  }
  else {
    capture.status = "complete";
  }
}

std::string RE_mixar_visibility_json(const Scene *scene)
{
  std::lock_guard lock(capture_mutex);
  if (capture.scene_uid != scene->id.session_uid) {
    return "{\"schema_version\":1,\"status\":\"unavailable\",\"objects\":[]}";
  }
  std::ostringstream out;
  out << "{\"schema_version\":1,\"status\":" << quoted(capture.status)
      << ",\"capture_id\":" << capture.generation << ",\"scene_session_uid\":"
      << capture.scene_uid << ",\"frame\":" << capture.frame
      << ",\"error\":" << quoted(capture.error) << ",\"objects\":[";
  bool first = true;
  if (capture.status == "complete") {
    for (const auto &[uid, object] : capture.objects) {
      if (!first) {
        out << ',';
      }
      first = false;
      out << "{\"session_uid\":" << uid << ",\"name\":" << quoted(object.name) << '}';
    }
  }
  out << "]}";
  return out.str();
}
