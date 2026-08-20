/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spimage
 *
 * Mixar UV panels for the IMAGE_EDITOR sidebar.
 */

#pragma once

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct ARegionType;
struct bContext;

/* Panel registration functions for IMAGE_EDITOR sidebar.
 * The Tool panel (Snapping / Round to Pixels / Align / Align Rotation)
 * is now implemented in Python (see uv_editor/ui/uv_tool/panels.py). */
void mixar_uv_transform_panel_register(ARegionType *art);
void mixar_uv_redo_panel_register(ARegionType *art);

/* Shared helper: get WINDOW region from current IMAGE_EDITOR area. */
ARegion *mixar_uv_find_window_region(const bContext *C);

/* Shared callback for UV transform operations. */
void do_mixar_uvedit_transform(bContext *C, void *arg, int event);

/* Event IDs for transform callback. */
#define B_MIXAR_UVEDIT_VERTEX 4
#define B_MIXAR_UVEDIT_ROTATE 5
#define B_MIXAR_UVEDIT_SCALE 6
#define B_MIXAR_UVEDIT_PIVOT 7
#define B_MIXAR_UVEDIT_CURSOR 8
#define B_MIXAR_UVEDIT_ARRANGE 9
#define B_MIXAR_UVEDIT_MOVE_AXIS 10

/* Shared state for UV transform operations. */
extern float mixar_uv_vertex_old_center[2];
extern float mixar_uv_vertex_old_angle;
extern float mixar_uv_vertex_applied_angle;
extern float mixar_uv_size_target[2];
extern int mixar_uv_pivot_point;
extern float mixar_uv_cursor_edit[2];
extern float mixar_uv_arrange_margin;

}  // namespace blender
