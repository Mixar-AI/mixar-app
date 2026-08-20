/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Chat message drawing orchestrator.
 * Coordinates layout building, View2D management, auto-scroll, and
 * rendering. Layout and render passes are split into separate files:
 *   - mixie_chat_messages_layout.cc: layout cache builder
 *   - mixie_chat_messages_render.cc: message render loop
 */

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_time.h"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"
#include "BKE_main.hh"

#include "BLF_api.hh"

#include "ED_screen.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "GPU_state.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"
#include "UI_view2d.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Animation Registry
 *
 * Modular animation system for chat UI elements.
 * Each animation type defines a sequence of UTF-8 frames.
 * To add a new animation: add an enum entry + array entry.
 * \{ */

struct ChatAnimation {
  const char *frames[8]; /* Up to 8 frames per animation */
  int frame_count;
};

static const ChatAnimation g_animations[CHAT_ANIM_COUNT] = {
    /* CHAT_ANIM_SPINNER */   {{"\u25D0", "\u25D3", "\u25D1", "\u25D2"}, 4},
    /* CHAT_ANIM_PULSE_DOT */ {{"\xe2\x97\x8f", "\xe2\x97\x8b"}, 2},
};

const char *chat_anim_frame(ChatAnimationType type, int frame_index)
{
  const ChatAnimation &anim = g_animations[type];
  return anim.frames[frame_index % anim.frame_count];
}

/* Glyph advance rate for the wall-clock spinner (frames per second). The
 * animation pump redraws at 30 fps; 8 glyph steps/s reads as a smooth spin
 * without strobing. */
#define CHAT_SPINNER_GLYPH_FPS 8.0

int chat_ui_spinner_frame()
{
  /* BLI_time_now_seconds is gettimeofday-based (seconds since the Unix
   * epoch, ~1.8e9): multiplied up it exceeds int range and the double->int
   * conversion SATURATES to a constant on ARM — the spinner freezes. Fold
   * to the cycle length BEFORE the cast. */
  return int(fmod(BLI_time_now_seconds() * CHAT_SPINNER_GLYPH_FPS, 4.0));
}

/** \} */

/* Empty prompt data and drawing moved to mixie_chat_empty_state.cc */

/* -------------------------------------------------------------------- */
/** \name Layout Cache
 * \{ */

/* Layout cache, scroll tracking, and empty prompts now live in MixieChatRuntime. */

MixieChatRuntime *mixie_chat_ensure_runtime(SpaceMixieChat *smixie)
{
  if (smixie->runtime == nullptr) {
    MixieChatRuntime *rt = MEM_new<MixieChatRuntime>(__func__);
    rt->prev_total_height = 0.0f;
    rt->prev_winy = -1;
    rt->empty_prompts_visible = false;
    smixie->runtime = rt;
  }
  return static_cast<MixieChatRuntime *>(smixie->runtime);
}

void mixie_chat_free_runtime(SpaceMixieChat *smixie)
{
  if (smixie->runtime) {
    MixieChatRuntime *rt = static_cast<MixieChatRuntime *>(smixie->runtime);
    /* Free all allocated text buffers in layout cache */
    for (MessageLayoutData &layout : rt->layout_cache) {
      if (layout.todo_combined_text) {
        MEM_freeN(layout.todo_combined_text);
        layout.todo_combined_text = nullptr;
      }
      if (layout.copy_text) {
        MEM_freeN(layout.copy_text);
        layout.copy_text = nullptr;
      }
      if (layout.content_text) {
        MEM_freeN(layout.content_text);
        layout.content_text = nullptr;
      }
      if (layout.ephemeral_text) {
        MEM_freeN(layout.ephemeral_text);
        layout.ephemeral_text = nullptr;
      }
    }
    MEM_delete(rt);
    smixie->runtime = nullptr;
  }
}

const blender::Vector<MessageLayoutData> &mixie_chat_get_layout_cache(SpaceMixieChat *smixie) {
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  return rt->layout_cache;
}

void mixie_chat_clear_layout_cache(SpaceMixieChat *smixie) {
  if (smixie->runtime == nullptr) {
    return;
  }
  MixieChatRuntime *rt = static_cast<MixieChatRuntime *>(smixie->runtime);
  /* Free any allocated todo_combined_text before clearing */
  for (MessageLayoutData &layout : rt->layout_cache) {
    if (layout.todo_combined_text) {
      MEM_freeN(layout.todo_combined_text);
      layout.todo_combined_text = nullptr;
    }
    /* Free cached copy text */
    if (layout.copy_text) {
      MEM_freeN(layout.copy_text);
      layout.copy_text = nullptr;
    }
    /* Free slot-based text buffers */
    if (layout.content_text) {
      MEM_freeN(layout.content_text);
      layout.content_text = nullptr;
    }
    if (layout.ephemeral_text) {
      MEM_freeN(layout.ephemeral_text);
      layout.ephemeral_text = nullptr;
    }
  }
  rt->layout_cache.clear_and_shrink();
  rt->prev_total_height = 0.0f;
  /* Reset tracking state so next draw triggers a full rebuild */
  rt->prev_msg_count = 0;
  rt->prev_winx = 0;
  rt->prev_had_active_stream = false;
  rt->cached_total_height = 0.0f;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name View2D Dimension Updates
 * \{ */

/**
 * Update View2D dimensions and mask to match current region size.
 * Must be called BEFORE ui::view2d_view_ortho() to ensure correct
 * coordinate transformations for scrollbar interactions.
 */
static void mixie_chat_region_set_view2d(MixieChatRuntime *rt,
                                         ARegion *region) {
  View2D *v2d = &region->v2d;

  int winx = BLI_rcti_size_x(&region->winrct) + 1;
  int winy = BLI_rcti_size_y(&region->winrct) + 1;

  bool window_size_changed = (rt->prev_winy != winy);

  v2d->winx = winx;
  v2d->winy = winy;

  /* Update mask for correct coordinate transforms */
  v2d->mask.xmin = 0;
  v2d->mask.ymin = 0;
  v2d->mask.xmax = winx;
  v2d->mask.ymax = winy;

  if (window_size_changed) {
    const float scroll_threshold = 20.0f;
    bool was_at_bottom = (v2d->cur.ymin <= v2d->tot.ymin + scroll_threshold);

    float cur_height_target = float(winy);

    if (was_at_bottom) {
      v2d->cur.xmin = 0.0f;
      v2d->cur.xmax = float(winx);
      v2d->cur.ymin = v2d->tot.ymin;
      v2d->cur.ymax = v2d->cur.ymin + cur_height_target;
    } else {
      float center_y = (v2d->cur.ymin + v2d->cur.ymax) / 2.0f;
      v2d->cur.xmin = 0.0f;
      v2d->cur.xmax = float(winx);
      v2d->cur.ymin = center_y - cur_height_target / 2.0f;
      v2d->cur.ymax = center_y + cur_height_target / 2.0f;
    }

    rt->prev_winy = winy;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Main Drawing Function
 * \{ */

void mixie_chat_draw_messages(const bContext *C, ARegion *region) {
  /* Set GPU blend mode once for entire UI drawing session */
  GPU_blend(GPU_BLEND_ALPHA);
  GPU_line_smooth(false);

  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return;
  }

  ScrArea *area = CTX_wm_area(C);
  SpaceMixieChat *smixie = nullptr;
  /* SPACE_AGENT_BUBBLE has a layout-compatible spacedata struct
   * (see DNA_space_types.h), so the same cast is valid for both. */
  if (area && area->spacedata.first &&
      (area->spacetype == SPACE_MIXIE_CHAT ||
       area->spacetype == SPACE_AGENT_BUBBLE))
  {
    smixie = static_cast<SpaceMixieChat *>(area->spacedata.first);
  }

  Main *bmain = CTX_data_main(C);
  if (!bmain || !smixie) {
    return;
  }

  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  View2D *v2d = &region->v2d;

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop =
      RNA_struct_find_property(&scene_ptr, "mixie_chat_messages");

  if (!prop) {
    return;
  }

  ChatLayoutMetrics metrics = chat_ui_get_layout_metrics();
  ChatImageStyle image_style = chat_ui_get_image_style(&metrics);

  int winx = BLI_rcti_size_x(&region->winrct) + 1;
  int winy = BLI_rcti_size_y(&region->winrct) + 1;

  /* Check if collection is empty */
  int msg_count = RNA_property_collection_length(&scene_ptr, prop);
  int layout_epoch = 0;
  {
    PropertyRNA *epoch_prop =
        RNA_struct_find_property(&scene_ptr, "mixie_chat_layout_epoch");
    if (epoch_prop) {
      layout_epoch = RNA_property_int_get(&scene_ptr, epoch_prop);
    }
  }
  if (msg_count == 0) {
    /* Empty-state "Hi I'm Mixie" greeting only shows for a truly
     * fresh chat. Once the user has sent a message (or otherwise
     * engaged with the composer), we stop showing it even if the
     * message list is later cleared transiently — the height-based
     * gating in mixie_chat_draw_empty_state on its own caused the
     * greeting to pop back into view whenever an attachment grew
     * the bubble. The engagement flag is SKIP_SAVE so it resets
     * with each Blender launch; new_session also flips it back to
     * False so a manual chat reset re-shows the greeting. */
    bool user_has_engaged = false;
    PropertyRNA *engaged_prop =
        RNA_struct_find_property(&scene_ptr, "mixie_chat_user_has_engaged");
    if (engaged_prop) {
      user_has_engaged = RNA_property_boolean_get(&scene_ptr, engaged_prop);
    }
    /* Suppress preset-prompt overlay in the agent bubble — the tiny floating
     * window doesn't have enough room for the animated bubbles, and they
     * clutter the compact composer UI. */
    const bool is_bubble = (area && area->spacetype == SPACE_AGENT_BUBBLE);
    if (!user_has_engaged && !is_bubble) {
      mixie_chat_draw_empty_state(C, region, smixie, metrics, winx, winy);
    }
    /* Invalidate the runtime layout cache so the next non-empty draw
     * is forced to rebuild from scratch. Without this, the cached
     * MessageLayoutData entries from the previous chat survive
     * `messages.clear()` (which only touches the Python-side
     * collection) — and when the user sends a follow-up message
     * after a new_session, `msg_count` can coincidentally match the
     * previous `prev_msg_count`, no rebuild trigger fires, and the
     * new placeholder gets drawn at the OLD agent reply's height
     * and position (the "huge empty bubble on new-chat send" bug).
     * Clearing here resets prev_msg_count/prev_winx/etc to 0 so
     * the next draw with msg_count > 0 always rebuilds. */
    mixie_chat_clear_layout_cache(smixie);
    GPU_blend(GPU_BLEND_NONE);
    return;
  }

  /* Chat has messages - hide empty prompts and mark animation for reset */
  rt->empty_prompts_visible = false;
  rt->empty_anim_reset = true;

  /* Incremental layout cache: only rebuild when content has actually changed */
  bool needs_layout_rebuild = false;
  bool slide_just_triggered = false;
  if (msg_count != rt->prev_msg_count) {
    needs_layout_rebuild = true;
    /* Trigger slide-in animation for the newest message */
    if (msg_count > rt->prev_msg_count && rt->prev_msg_count > 0) {
      rt->slide_anim_start = BLI_time_now_seconds();
      slide_just_triggered = true;
      /* Bounce the scroll indicator if user is scrolled up */
      mixie_chat_trigger_scroll_bounce(smixie);
    }
  } else if (winx != rt->prev_winx) {
    needs_layout_rebuild = true;
  } else if (rt->prev_had_active_stream) {
    needs_layout_rebuild = true;
  } else if (rt->layout_cache.is_empty()) {
    needs_layout_rebuild = true;
  } else if (layout_epoch != rt->prev_layout_epoch) {
    needs_layout_rebuild = true;
  } else if (!g_msg_props.initialized) {
    /* The global RNA property cache was cleared while our layout cache
     * stayed populated. This happens whenever ANY SpaceMixieChat is freed —
     * mixie_chat_free() clears the process-global caches — including the
     * spaces inside the temp Main that the workspace "+" menu / append
     * reads from startup.blend and immediately frees
     * (BKE_blendfile_workspace_config_data_free -> BKE_main_free -> space
     * free callback). Without this trigger the render path null-guards
     * every g_msg_props access, silently drawing zero-length text: the
     * bubble/chat goes blank until a resize changes winx and forces a
     * rebuild. Rebuilding re-runs init_message_property_cache(), healing
     * the cache on the very next draw. */
    needs_layout_rebuild = true;
  }

  /* Check if feedback state changed (visibility, rating, or expansion) on any
   * cached message. Uses message_index stored in layout entries to look up the
   * right RNA item. */
  if (!needs_layout_rebuild && !rt->layout_cache.is_empty() &&
      g_msg_props.feedback_visible && g_msg_props.feedback_rating)
  {
    for (int i = rt->layout_cache.size() - 1; i >= 0; i--) {
      const MessageLayoutData &cached = rt->layout_cache[i];
      if (!cached.has_feedback && !cached.is_slot_based) {
        continue;  /* Only slot-based messages can have feedback */
      }
      PointerRNA msg_ptr;
      if (!RNA_property_collection_lookup_int(
              &scene_ptr, prop, cached.message_index, &msg_ptr)) {
        continue;
      }
      bool rna_fb = RNA_property_boolean_get(&msg_ptr, g_msg_props.feedback_visible);
      int rna_rating = RNA_property_int_get(&msg_ptr, g_msg_props.feedback_rating);
      bool rna_expanded = g_msg_props.feedback_comment_expanded ?
          RNA_property_boolean_get(&msg_ptr, g_msg_props.feedback_comment_expanded) :
          false;
      int rna_status = g_msg_props.feedback_status ?
          RNA_property_int_get(&msg_ptr, g_msg_props.feedback_status) : 0;
      /* Compare submitted-comment lengths clamped to the display buffer so a
       * server-accepted comment longer than the cached copy can't trigger a
       * rebuild on every draw. */
      int rna_submitted_len = g_msg_props.feedback_submitted_comment ?
          RNA_property_string_length(&msg_ptr, g_msg_props.feedback_submitted_comment) : 0;
      const int display_max = FEEDBACK_COMMENT_DISPLAY_MAX - 1;
      rna_submitted_len = std::min(rna_submitted_len, display_max);
      const int cached_submitted_len = int(strlen(cached.feedback_submitted_comment));
      if (rna_fb != cached.has_feedback || rna_rating != cached.feedback_rating ||
          rna_expanded != cached.feedback_comment_expanded ||
          rna_status != cached.feedback_status ||
          rna_submitted_len != cached_submitted_len)
      {
        needs_layout_rebuild = true;
        break;
      }
    }
  }

  /* Build or reuse layout cache */
  static const bool chat_prof = getenv("MIXAR_CHAT_PROFILE") != nullptr;
  const double prof_t0 = chat_prof ? BLI_time_now_seconds() : 0.0;

  float total_height;
  if (needs_layout_rebuild) {
    total_height = mixie_chat_build_layout_cache(
        smixie, bmain, &scene_ptr, prop, metrics, image_style, winx, msg_count);
  } else {
    total_height = rt->cached_total_height;
  }

  if (slide_just_triggered) {
    /* The render pass indexes the layout cache, which holds RENDERABLE
     * messages only — an all-messages `msg_count - 1` index never matches
     * when metadata-only messages exist and the slide silently skipped.
     * Point at the newest cache entry instead (the message that was just
     * appended, since the cache is built in collection order). */
    rt->slide_anim_msg_index =
        rt->layout_cache.is_empty() ? -1 : int(rt->layout_cache.size()) - 1;
  }

  if (chat_prof) {
    const double prof_now = BLI_time_now_seconds();
    fprintf(stderr,
            "[CHATPROF] t=%.4f rebuild=%d ms=%.2f msgs=%d cache=%d slide_idx=%d\n",
            prof_now,
            needs_layout_rebuild ? 1 : 0,
            (prof_now - prof_t0) * 1000.0,
            msg_count,
            int(rt->layout_cache.size()),
            rt->slide_anim_msg_index);
  }

  /* Auto-scroll detection: check BEFORE updating tot bounds */
  const float scroll_threshold = 20.0f;
  bool is_uninitialized = (v2d->cur.ymax <= 0.0f || v2d->cur.ymin < 0.0f);
  bool was_at_bottom = (v2d->cur.ymin <= v2d->tot.ymin + scroll_threshold);

  /* Update View2D total bounds */
  v2d->tot.xmin = 0;
  v2d->tot.xmax = float(winx);
  v2d->tot.ymin = 0;
  v2d->tot.ymax = total_height;

  /* Update View2D dimensions and mask BEFORE auto-scroll */
  mixie_chat_region_set_view2d(rt, region);

  float view_height = BLI_rctf_size_y(&v2d->cur);

  /* Auto-scroll to show new messages when user is at bottom */
  if (is_uninitialized || was_at_bottom) {
    v2d->cur.ymin = v2d->tot.ymin;
    v2d->cur.ymax = v2d->cur.ymin + view_height;
  }
  else if (rt->prev_total_height > 0.0f && total_height != rt->prev_total_height) {
    /* User is scrolled up: anchor the view to the content, not to the
     * bottom. Layout coordinates are bottom-anchored (the newest message
     * ends at y=0), so whenever streamed content grows, every existing
     * message shifts up by the growth delta. Shift cur by the same delta,
     * otherwise the text being read slides out from under the view on
     * every streaming rebuild and scrolling up appears not to work while
     * the agent is replying. (The prev_total_height > 0 guard skips the
     * first draw after a cache clear, where no valid baseline exists.) */
    const float growth = total_height - rt->prev_total_height;
    v2d->cur.ymin += growth;
    v2d->cur.ymax += growth;
  }

  rt->prev_total_height = total_height;

  /* Clamp viewport to prevent scrolling beyond content bounds */
  if (v2d->cur.ymax > v2d->tot.ymax) {
    float offset = v2d->cur.ymax - v2d->tot.ymax;
    v2d->cur.ymax = v2d->tot.ymax;
    v2d->cur.ymin -= offset;
  }

  if (v2d->cur.ymin < v2d->tot.ymin) {
    float offset = v2d->tot.ymin - v2d->cur.ymin;
    v2d->cur.ymin = v2d->tot.ymin;
    v2d->cur.ymax += offset;
  }

  /* When content fits in view, show newest messages */
  if (view_height >= BLI_rctf_size_y(&v2d->tot)) {
    v2d->cur.ymin = v2d->tot.ymin;
    v2d->cur.ymax = v2d->cur.ymin + view_height;
  } else {
    if (v2d->cur.ymax > v2d->tot.ymax) {
      v2d->cur.ymax = v2d->tot.ymax;
      v2d->cur.ymin = v2d->cur.ymax - view_height;
    }
    if (v2d->cur.ymin < v2d->tot.ymin) {
      v2d->cur.ymin = v2d->tot.ymin;
      v2d->cur.ymax = v2d->cur.ymin + view_height;
    }
  }

  /* Setup View2D for drawing */
  ui::view2d_view_ortho(v2d);

  /* Delegate rendering to mixie_chat_messages_render.cc */
  mixie_chat_render_messages(
      C, region, smixie, bmain, &scene_ptr, prop, metrics, image_style);

  /* Cleanup: restore GPU state and View2D */
  GPU_blend(GPU_BLEND_NONE);
  GPU_line_smooth(false);

  ui::view2d_view_restore(C);

  /* Scroll-to-bottom indicator (drawn in screen-space after view restore) */
  mixie_chat_update_scroll_indicator(smixie, region, msg_count);
  mixie_chat_draw_scroll_indicator(smixie, region);

  ui::view2d_scrollers_draw(v2d, nullptr);

  /* Keep frames coming while anything on this surface animates: streaming
   * loader/ephemeral content (spinner + live status), a bubble slide-in, or
   * the scroll-indicator bounce. The pump self-removes shortly after all
   * animations settle (see mixie_chat_anim_pump_request). */
  const bool anim_active = rt->prev_had_active_stream ||
                           rt->slide_anim_msg_index >= 0 ||
                           rt->scroll_indicator_bounce_start > 0.0;
  mixie_chat_anim_pump_request(C, anim_active);
}

/** \} */
}  // namespace blender
