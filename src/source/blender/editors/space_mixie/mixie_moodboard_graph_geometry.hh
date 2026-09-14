/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

namespace blender {
struct PointerRNA;
struct rctf;
}

namespace blender::ed::mixie {

/** Internal graph geometry shared by cache construction and pointer hit tests. */
bool moodboard_graph_string_prop_equals(PointerRNA *ptr, const char *name, const char *value);
bool moodboard_graph_media_rect(PointerRNA *item, rctf *r_rect);

}  // namespace blender::ed::mixie
