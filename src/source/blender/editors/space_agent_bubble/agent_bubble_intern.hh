/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Internal header for the Agent Bubble editor space.
 */

#pragma once

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct bContext;
struct wmOperatorType;
struct wmWindowManager;

/* -------------------------------------------------------------------- */
/** \name Header Region (status pill)
 * \{ */

void agent_bubble_header_region_init(wmWindowManager *wm, ARegion *region);
void agent_bubble_header_region_draw(const bContext *C, ARegion *region);

/** \} */

/* Main + footer regions reuse mixie chat's custom-drawn callbacks
 * (see space_agent_bubble.cc). SpaceAgentBubble is layout-identical
 * to SpaceMixieChat, so the cast inside those callbacks is valid. */

/* -------------------------------------------------------------------- */
/** \name Operators
 * \{ */

/* Opens the Agent Bubble in a small chrome-less TEMP window via
 * WM_window_open_temp. Python idname: mixar.agent_bubble_show_window. */
void MIXAR_OT_agent_bubble_show_window(wmOperatorType *ot);

/* Resizes the Agent Bubble floating window via the platform-specific
 * Mixar_WindowForceSize helper (Cocoa / Win32). Python idname:
 * mixar.bubble_set_size(width, height). */
void MIXAR_OT_bubble_set_size(wmOperatorType *ot);

/* Sync collapsed bubble height and resize floor with pending image attachments.
 * Python idname: mixar.bubble_sync_attachment_size. */
void MIXAR_OT_bubble_sync_attachment_size(wmOperatorType *ot);

/* Hands off window-drag tracking to the native platform code path
 * via Mixar_WindowBeginDrag (AppKit on macOS, WM_NCLBUTTONDOWN on
 * Win32). Python idname: mixar.bubble_window_begin_drag. Called once
 * by the Python drag op; the OS handles per-frame tracking from
 * there until the user releases the mouse. */
void MIXAR_OT_bubble_window_begin_drag(wmOperatorType *ot);
void MIXAR_OT_bubble_window_update_drag(wmOperatorType *ot);
void MIXAR_OT_bubble_window_end_drag(wmOperatorType *ot);

/* Yellow traffic-light click: hides the bubble window (orderOut on
 * macOS, ShowWindow SW_HIDE on Win32), detaches the pill so it
 * survives the cascade, and snaps the pill to the centre-bottom.
 * Python idname: mixar.bubble_minimise. */
void MIXAR_OT_bubble_minimise(wmOperatorType *ot);

/* Pill click while minimised: shows the bubble again and re-attaches
 * the pill above its top-left. No-op when not minimised. Python
 * idname: mixar.bubble_restore. */
void MIXAR_OT_bubble_restore(wmOperatorType *ot);

/* Green traffic-light click: toggles the bubble between collapsed
 * and expanded heights via Mixar_WindowForceSize. Python idname:
 * mixar.bubble_toggle_expand. */
void MIXAR_OT_bubble_toggle_expand(wmOperatorType *ot);

/* Set custom background colour (RGBA) for the bubble.  Alpha 0
 * disables the override and falls back to the theme.  Python idname:
 * mixar.bubble_set_bg_color(r, g, b, a). */
void MIXAR_OT_bubble_set_bg_color(wmOperatorType *ot);

/** \} */

}  // namespace blender
