/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

#include <cstdint>
#include <string>

struct Render;
struct Scene;

/** Object identity is session-local, never a GPU handle or name-derived hash. */
struct MixarVisibleObject {
  uint32_t session_uid;
  std::string name;
};

void RE_mixar_visibility_begin(Render *render, const Scene *scene, bool enabled);
bool RE_mixar_visibility_enabled(const Render *render);
void RE_mixar_visibility_add(Render *render, const MixarVisibleObject &object);
void RE_mixar_visibility_sample(Render *render);
void RE_mixar_visibility_fail(Render *render, const char *message);
void RE_mixar_visibility_finish(Render *render, bool cancelled);
std::string RE_mixar_visibility_json(const Scene *scene);
