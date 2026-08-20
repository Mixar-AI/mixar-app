/* SPDX-FileCopyrightText: 2008 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#pragma once

namespace blender {

struct ARegion;
struct ARegionType;
struct bContext;

/* Only called once on startup. storage is global in BKE kernel listbase. */
void ED_spacetypes_init();
void ED_spacemacros_init();

/* The plugin-able API for export to editors. */

/* -------------------------------------------------------------------- */
/** \name Calls for registering default spaces
 *
 * Calls for registering default spaces, only called once, from #ED_spacetypes_init
 * \{ */

void ED_spacetype_outliner();
void ED_spacetype_view3d();
void ED_spacetype_ipo();
void ED_spacetype_image();
void ED_spacetype_node();
void ED_spacetype_buttons();
void ED_spacetype_info();
void ED_spacetype_file();
void ED_spacetype_action();
void ED_spacetype_nla();
void ED_spacetype_script();
void ED_spacetype_text();
void ED_spacetype_console();
void ED_spacetype_userpref();
void ED_spacetype_clip();
void ED_spacetype_statusbar();
void ED_spacetype_topbar();
void ED_spacetype_mixie();  /* Mixie space for Mixar */
void ED_spacetype_mixar_layers();  /* Mixar Layers space */
void ED_spacetype_mixar_properties();  /* Mixar Properties space */
void ED_spacetype_mixar_assets();  /* Mixar Assets space */

void ED_spacetype_baking();  /* Texturing Baking space */
void ED_spacetype_texture_sets();  /* Texture Sets space */
void ED_spacetype_mixie_chat();  /* Mixie Chat space for Mixar */
void ED_spacetype_agent_bubble();  /* Floating Agent Bubble overlay editor for Mixar */

/* Mixar: reset the Agent Bubble's cached native-window pointers (bubble/
 * pill ghost windows, minimised/expanded flags). wm_window_close() calls
 * this itself whenever the window it just destroyed hosted an Agent Bubble
 * space, so every close path (quit, save-pre purge, the purge operator,
 * plain `bpy.ops.wm.window_close()`) is covered automatically — callers
 * don't need to call this directly. Exposed here only because
 * MIXAR_OT_agent_bubble_purge_windows also calls it as a belt-and-suspenders
 * reset for stale flags left behind with no live window to close. Safe to
 * call even when no bubble window was ever opened. */
void ED_agent_bubble_windows_closed();

/* Mixar: notify the Agent Bubble cache that a native GHOST window is being
 * destroyed. Clears whichever cached pointer (bubble / pill / host) matches
 * `ghostwin`, so the cache can never dangle regardless of the teardown path.
 * wm_window_free() calls this for every window it destroys — including the
 * paths that never go through wm_window_close(), e.g. replacing the whole
 * window-manager on file load (#wm_close_and_free) and application exit. */
void ED_agent_bubble_window_freed(const void *ghostwin);

namespace ed::vse {
void ED_spacetype_sequencer();
}

namespace ed::spreadsheet {
void register_spacetype();
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Space-type Static Data
 * Calls for instancing and freeing space-type static data called in #WM_init_exit
 * \{ */

void ED_file_init();
void ED_file_exit();

/** \} */

#define REGION_DRAW_POST_VIEW 0
#define REGION_DRAW_POST_PIXEL 1
#define REGION_DRAW_PRE_VIEW 2
#define REGION_DRAW_BACKDROP 3

void *ED_region_draw_cb_activate(ARegionType *art,
                                 void (*draw)(const bContext *, ARegion *, void *),
                                 void *customdata,
                                 int type);
void ED_region_draw_cb_draw(const bContext *C, ARegion *region, int type);
void ED_region_surface_draw_cb_draw(const bContext *C, ARegionType *art, int type);
bool ED_region_draw_cb_exit(ARegionType *art, void *handle);
void ED_region_draw_cb_remove_by_type(ARegionType *art, void *draw_fn, void (*free)(void *));

}  // namespace blender
