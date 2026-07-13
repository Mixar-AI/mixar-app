/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Agent Bubble — small chat overlay editor for Mixar.
 *
 * Three regions stacked vertically: header (status pill), main
 * (scrollable history), footer (input + send). Modeled on
 * space_mixie_chat / space_texture_sets but trimmed to just what we
 * need for the floating agent bubble use case. Intended to be opened
 * in a small tear-off Blender window so it floats over the user's
 * working area while still being a real editor (native scroll, native
 * input, drag-resize, etc.).
 */

#include <climits>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_string_utf8.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_report.hh"
#include "BKE_screen.hh"

#include "ED_screen.hh"
#include "ED_space_api.hh"

#include "WM_api.hh"
#include "WM_keymap.hh"
#include "WM_types.hh"

#include "BLI_rect.h"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "BLO_read_write.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "DNA_scene_types.h"
#include "DNA_space_types.h"
#include "DNA_userdef_types.h"

#include "agent_bubble_intern.hh"

/* Slim region sizing + bubble window dimensions.
 *
 * Defined up here (rather than next to the operator that consumes
 * them) because agent_bubble_create() — which runs much earlier in
 * the file — needs the footer/header constants too. Moving the
 * defines closer to the usage at the top of the file resolves the
 * "use of undeclared identifier" error the build hit when these
 * lived inside the operator section.
 *
 * Header / footer prefsizey values match what space_agent_bubble's
 * region setup requests; the drag op (bubble_header_drag_op.py)
 * mirrors them in Python so its min-height clamp stays in sync. */
#define AGENT_BUBBLE_HEADER_HEIGHT 18
/* Footer needs room for the multi-line input wrapper (1 line default,
 * up to 4 lines when typing) plus the Mode + Send action row. 90 px
 * fits a 1-line composer + the action row comfortably; the wrapper's
 * internal scroll handles overflow when the input grows. */
#define AGENT_BUBBLE_FOOTER_HEIGHT 90
#define AGENT_BUBBLE_DEFAULT_WIDTH 400
/* Default content height: footer (~90 px) + header (~18 px) + body for
 * chat history. 350 px gives ~240 px of scroll area — a compact bubble
 * the user can grow via drag/expand. This is also the OS resize floor
 * (AGENT_BUBBLE_MIN_HEIGHT below). */
#define AGENT_BUBBLE_DEFAULT_HEIGHT 350
#define AGENT_BUBBLE_MIN_WIDTH AGENT_BUBBLE_DEFAULT_WIDTH
#define AGENT_BUBBLE_MIN_HEIGHT AGENT_BUBBLE_DEFAULT_HEIGHT
#define AGENT_BUBBLE_ATTACHMENT_HEIGHT_DELTA 100
#define AGENT_BUBBLE_EXPANDED_HEIGHT 700
#define AGENT_BUBBLE_BODY_MIN_HEIGHT 120
#define AGENT_BUBBLE_AUTOGROW_SLACK 12
#ifdef _WIN32
#  define AGENT_BUBBLE_ATTACHMENT_AUTOGROW_EXTRA 72
#else
#  define AGENT_BUBBLE_ATTACHMENT_AUTOGROW_EXTRA 48
#endif
#define AGENT_BUBBLE_AUTOGROW_TOP_RESERVE 46

/* Visual corner-rounding for the bubble window — soft floating
 * popup silhouette per the Figma. */
#define AGENT_BUBBLE_CORNER_RADIUS 12.0f

/* Mixar overlay functions — see GHOST_SystemCocoa.mm (macOS) and
 * GHOST_SystemWin32.cc (Windows). Declared here as extern "C" so we
 * don't need a fresh GHOST header just for these (the editor build
 * doesn't include the GHOST internals normally). On Linux the symbols
 * won't exist; guard the call sites with the platform macro. */
#if defined(__APPLE__) || defined(_WIN32)
extern "C" void Mixar_WindowSetChromeless(void *window_handle, bool chromeless);
extern "C" void Mixar_WindowForceSize(void *window_handle, int width, int height);
extern "C" void Mixar_WindowSetCornerRadius(void *window_handle, float radius);
extern "C" void Mixar_WindowSetMinContentSize(void *window_handle,
                                              int width,
                                              int height);
#ifdef __APPLE__
extern "C" void Mixar_WindowSetMaxContentSize(void *window_handle,
                                              int width,
                                              int height);
#endif
extern "C" void Mixar_WindowBeginDrag(void *window_handle);
#ifdef _WIN32
extern "C" void Mixar_WindowUpdateDrag(void *window_handle);
extern "C" void Mixar_WindowEndDrag(void *window_handle);
extern "C" void Mixar_WindowSetParentTracked(void *child_handle, void *parent_handle);
#endif
extern "C" void Mixar_WindowSetParent(void *child_handle, void *parent_handle);
extern "C" void Mixar_WindowPositionAboveParent(void *child_handle,
                                                void *parent_handle,
                                                int offset_x,
                                                int offset_y);
extern "C" bool Mixar_WindowHasChildWindow(void *parent_handle);
extern "C" void Mixar_WindowSetBorderless(void *window_handle);
extern "C" void Mixar_WindowSetFloatingLevel(void *window_handle);
extern "C" void Mixar_WindowSetHidesOnDeactivate(void *window_handle, bool hides);
extern "C" void Mixar_WindowBindToParentSpace(void *window_handle);
extern "C" void Mixar_WindowOrderOut(void *window_handle);
extern "C" void Mixar_WindowOrderFront(void *window_handle);
extern "C" void Mixar_WindowDetachFromParent(void *child_handle, void *parent_handle);
extern "C" void Mixar_WindowSnapToCentreBottom(void *window_handle, int margin_bottom);
extern "C" void Mixar_WindowSetParentPlain(void *child_handle, void *parent_handle);
extern "C" void Mixar_WindowSnapToCentreBottomOfWindow(void *child_handle,
                                                       void *parent_handle,
                                                       int margin_bottom);
extern "C" void Mixar_WindowAnchorAtParentCentreBottom(void *child_handle,
                                                       void *parent_handle,
                                                       int margin_bottom);
extern "C" void Mixar_WindowAnimateFrameToCentreBottomOfWindow(
    void *child_handle, void *parent_handle,
    int new_width, int new_height, int margin_bottom, float duration);
extern "C" void Mixar_WindowAnimateAlphaTo(
    void *window_handle, float target_alpha, float duration);
extern "C" void Mixar_WindowSetAlpha(void *window_handle, float alpha);
extern "C" void Mixar_WindowSetBlurBehind(void *window_handle, bool enable);
extern "C" void Mixar_WindowMakeKey(void *window_handle);
extern "C" void Mixar_WindowMarkAsFloatingDock(void *window_handle);
extern "C" void Mixar_DispatchMainAfter(float delay_seconds,
                                        void (*callback)(void *),
                                        void *user_data);
extern "C" void Mixar_WindowGetContentPixelSize(
    void *window_handle, int *r_width, int *r_height);
extern "C" int Mixar_WindowGetMaxHeightToScreenTop(
    void *window_handle, int reserve_top);
#endif

/* Mixie chat's custom-drawn region callbacks. We reuse them
 * verbatim for the agent bubble's TOOLS (footer) and WINDOW (main /
 * chat history) regions so the bubble looks AND behaves identically
 * to the chat editor — including the dynamic region resize on
 * Shift+Enter that keeps the footer's action row visible, and the
 * native message rendering / scrolling / selection / hover tracking
 * for the chat history.
 *
 * The functions read from scene.mixie_chat_input / mixie_chat_mode
 * / mixie_chat_messages (global Scene properties), so they work
 * outside SPACE_MIXIE_CHAT without modification. Linker resolution
 * comes via bf_editor_space_mixie_chat in CMakeLists.txt LIB list.
 *
 * NOT extern "C" — these are C++ symbols, so the forward
 * declarations below MUST match the original signatures exactly
 * (no defaulted args, no namespace) for name mangling to resolve. */
struct ScrArea;
struct wmWindow;
struct wmRegionListenerParams;
struct SpaceMixieChat;

void mixie_chat_footer_region_init(wmWindowManager *wm, ARegion *region);
void mixie_chat_footer_region_layout(const bContext *C, ARegion *region);
void mixie_chat_footer_region_draw(const bContext *C, ARegion *region);

void mixie_chat_main_region_init(wmWindowManager *wm, ARegion *region);
void mixie_chat_main_region_layout(const bContext *C, ARegion *region);
void mixie_chat_main_region_draw(const bContext *C, ARegion *region);
void mixie_chat_main_region_exit(wmWindowManager *wm, ARegion *region);
void mixie_chat_main_region_listener(const wmRegionListenerParams *params);
void mixie_chat_main_region_cursor(wmWindow *win, ScrArea *area, ARegion *region);

/* Free per-space runtime cache (layout, hover, scroll). Called from
 * agent_bubble_free — safe because SpaceAgentBubble is layout-
 * compatible with SpaceMixieChat (see DNA_space_types.h). */
void mixie_chat_free_runtime(struct SpaceMixieChat *smixie);

/* Static state used by the minimise / restore / expand-toggle ops.
 *
 * We need persistent pointers to the bubble + pill ghost windows
 * so the ops (which can be invoked from either window's header
 * context) can address the right pair. Set when the bubble is
 * opened; cleared lazily on subsequent opens.
 *
 * `g_bubble_minimised` reflects the AppKit hide/show state for
 * convenience — Python and the ops both consult it to skip
 * redundant work (e.g. clicking the pill while not minimised is a
 * no-op). */
static void *g_bubble_ghostwin = nullptr;
static void *g_pill_ghostwin = nullptr;
static bool g_bubble_minimised = false;
static bool g_bubble_expanded = false;
static bool g_bubble_had_pending_attachments = false;
static int g_bubble_last_min_height = 0;

/* The host (main Mixar) window that the agent bubble was opened
 * from. Stashed when the open op runs so the minimise / restore
 * paths can re-parent the pill onto Mixar's main window — that's
 * what makes the pill follow the user's drags instead of staying
 * pinned to a screen coordinate. nullptr until the first open. */
static void *g_host_ghostwin = nullptr;

/* Custom background colour for the agent bubble.  Set via the
 * mixar.bubble_set_bg_color operator.  The override is pushed into
 * the shared mixie_chat draw functions via
 * mixie_chat_set_bg_override / mixie_chat_clear_bg_override —
 * see mixie_chat_main_region.cc and mixie_chat_footer.cc. */
static bool g_bubble_bg_custom = false;
static float g_bubble_bg_color[4] = {0.0f, 0.0f, 0.0f, 1.0f};

void wm_window_close(bContext *C, wmWindowManager *wm, wmWindow *win);

/* Forward declarations for the bg override helpers in mixie_chat. */
void mixie_chat_set_bg_override(const float rgba[4]);
void mixie_chat_clear_bg_override();

/* Wrapper draw callbacks that push the custom bg colour into the
 * shared mixie_chat draw path, then clear it afterwards so the
 * regular mixie_chat editor is unaffected. */
static void agent_bubble_main_region_draw(const bContext *C, ARegion *region)
{
  /* The main body (RGN_TYPE_WINDOW) resolves TH_BACK to
   * space_agent_bubble.back, which is the "Window Background" colour
   * in the Agent Bubble theme.  Push it as an override so the shared
   * mixie_chat draw path uses the agent-bubble colour, not the
   * mixie-chat one. */
  bTheme *btheme = UI_GetTheme();
  const unsigned char *bk = btheme->space_agent_bubble.back;
  float body_bg[4] = {bk[0] / 255.0f, bk[1] / 255.0f, bk[2] / 255.0f, bk[3] / 255.0f};
  mixie_chat_set_bg_override(body_bg);
  mixie_chat_main_region_draw(C, region);
  mixie_chat_clear_bg_override();
}

static int agent_bubble_height_floor_for_attachments(const int attachment_count)
{
  return AGENT_BUBBLE_DEFAULT_HEIGHT +
         ((attachment_count > 0) ? AGENT_BUBBLE_ATTACHMENT_HEIGHT_DELTA : 0);
}

#if defined(__APPLE__) || defined(_WIN32)
static void bubble_set_min_content_size(void *ghostwin, const int min_height)
{
  if (ghostwin == nullptr) {
    return;
  }
  /* Skip the AppKit/Win32 calls when the constraints are already in
   * effect. This function runs from the footer's layout AND draw
   * callbacks (agent_bubble_sync_footer_window_size), i.e. twice per
   * frame while the bubble repaints — two cross-runtime window calls
   * per frame for values that almost never change.
   *
   * The cache MUST be invalidated whenever Mixar_WindowForceSize runs:
   * force-size clears both contentMinSize and contentMaxSize to allow
   * free resizing, so the limits need re-applying afterwards. Every
   * force-size on the bubble goes through bubble_force_size_and_refresh
   * below, which resets g_bubble_last_min_height to 0 (an impossible
   * height) before restoring the constraints. */
  if (min_height == g_bubble_last_min_height) {
    return;
  }
  g_bubble_last_min_height = min_height;
  Mixar_WindowSetMinContentSize(ghostwin, AGENT_BUBBLE_MIN_WIDTH, min_height);
#ifdef __APPLE__
  /* Cap the maximum height so the bubble can't grow taller than the
   * expanded size.  Width is unconstrained (like Windows) so the user
   * can widen the bubble freely. */
  const int max_h = (min_height > AGENT_BUBBLE_EXPANDED_HEIGHT) ? min_height
                                                                 : AGENT_BUBBLE_EXPANDED_HEIGHT;
  Mixar_WindowSetMaxContentSize(ghostwin, 0, max_h);
#endif
}

static void bubble_force_size_and_refresh(bContext *C, void *ghostwin, int width, int height)
{
  if (ghostwin == nullptr) {
    return;
  }

  Mixar_WindowForceSize(ghostwin, width, height);
  /* Force-size cleared the OS min/max constraints — invalidate the
   * cache so the next bubble_set_min_content_size re-applies them. */
  g_bubble_last_min_height = 0;
  bubble_set_min_content_size(ghostwin, AGENT_BUBBLE_MIN_HEIGHT);

  int pixel_width = width;
  int pixel_height = height;
  Mixar_WindowGetContentPixelSize(ghostwin, &pixel_width, &pixel_height);
  if (pixel_width <= 0 || pixel_height <= 0) {
    pixel_width = width;
    pixel_height = height;
  }

  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return;
  }
  LISTBASE_FOREACH (wmWindow *, w, &wm->windows) {
    if (w->ghostwin != ghostwin) {
      continue;
    }
    w->sizex = pixel_width;
    w->sizey = pixel_height;
    bScreen *screen = WM_window_get_active_screen(w);
    if (screen == nullptr) {
      break;
    }
    ScrArea *area = static_cast<ScrArea *>(screen->areabase.first);
    if (area == nullptr) {
      break;
    }
    if (area->v1 != nullptr) {
      area->v1->vec.x = 0;
      area->v1->vec.y = 0;
    }
    if (area->v2 != nullptr) {
      area->v2->vec.x = 0;
      area->v2->vec.y = pixel_height - 1;
    }
    if (area->v3 != nullptr) {
      area->v3->vec.x = pixel_width - 1;
      area->v3->vec.y = pixel_height - 1;
    }
    if (area->v4 != nullptr) {
      area->v4->vec.x = pixel_width - 1;
      area->v4->vec.y = 0;
    }
    ED_screen_refresh(C, wm, w);
    ED_area_tag_redraw(area);
    break;
  }
}
#endif

static int agent_bubble_pending_attachment_count(const bContext *C)
{
  Scene *scene = CTX_data_scene(C);
  if (scene == nullptr) {
    return 0;
  }

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *attachments_prop = RNA_struct_find_property(
      &scene_ptr, "mixie_chat_pending_attachments");
  if (attachments_prop == nullptr) {
    return 0;
  }
  return RNA_property_collection_length(&scene_ptr, attachments_prop);
}

static int agent_bubble_collapsed_height_for_current_attachments(const bContext *C)
{
  return agent_bubble_height_floor_for_attachments(agent_bubble_pending_attachment_count(C));
}

static void agent_bubble_sync_footer_window_size(const bContext *C, ARegion *region)
{
#if defined(__APPLE__) || defined(_WIN32)
  wmWindow *win = CTX_wm_window(C);
  ARegion *sync_region = region;
  if (win == nullptr || win->ghostwin == nullptr || win->ghostwin != g_bubble_ghostwin) {
    wmWindowManager *wm = CTX_wm_manager(C);
    if (wm != nullptr) {
      LISTBASE_FOREACH (wmWindow *, candidate, &wm->windows) {
        if (candidate->ghostwin != g_bubble_ghostwin) {
          continue;
        }
        win = candidate;
        sync_region = nullptr;
        bScreen *screen = WM_window_get_active_screen(win);
        if (screen != nullptr && BLI_listbase_is_single(&screen->areabase)) {
          ScrArea *area = static_cast<ScrArea *>(screen->areabase.first);
          if (area != nullptr && area->spacetype == SPACE_AGENT_BUBBLE) {
            LISTBASE_FOREACH (ARegion *, candidate_region, &area->regionbase) {
              if (candidate_region->regiontype == RGN_TYPE_TOOLS) {
                sync_region = candidate_region;
                break;
              }
            }
          }
        }
        break;
      }
    }
  }
  if (win == nullptr || win->ghostwin == nullptr || win->ghostwin != g_bubble_ghostwin ||
      g_bubble_minimised)
  {
    return;
  }

  const int attachment_count = agent_bubble_pending_attachment_count(C);
  const int height_floor = agent_bubble_height_floor_for_attachments(attachment_count);
  bubble_set_min_content_size(win->ghostwin, height_floor);

  const bool has_attachments = (attachment_count > 0);
  const bool was_had_pending = g_bubble_had_pending_attachments;

  if (!has_attachments) {
    g_bubble_had_pending_attachments = false;
  }

  /* Compute required height from the footer's actual sizey so that
   * multi-line text input grows the window even without attachments. */
  int required_height = height_floor;
  if (sync_region != nullptr) {
    required_height = sync_region->sizey + AGENT_BUBBLE_HEADER_HEIGHT +
                      AGENT_BUBBLE_BODY_MIN_HEIGHT + AGENT_BUBBLE_AUTOGROW_SLACK;
  }

  if (has_attachments) {
    g_bubble_had_pending_attachments = true;
    required_height += AGENT_BUBBLE_ATTACHMENT_AUTOGROW_EXTRA;
  }

  /* Already big enough — skip resize. */
  if (required_height <= win->sizey + AGENT_BUBBLE_AUTOGROW_SLACK &&
      win->sizey >= height_floor) {
    return;
  }

  int target_height = (required_height > height_floor) ? required_height : height_floor;

  /* Clamp to screen boundary. */
  const int max_height = Mixar_WindowGetMaxHeightToScreenTop(
      win->ghostwin, AGENT_BUBBLE_AUTOGROW_TOP_RESERVE);
  if (max_height > 0 && target_height > max_height) {
    target_height = max_height;
  }

  if (target_height > win->sizey ||
      (has_attachments && !was_had_pending && !g_bubble_expanded))
  {
    bubble_force_size_and_refresh(
        const_cast<bContext *>(C), win->ghostwin, AGENT_BUBBLE_DEFAULT_WIDTH, target_height);
    bubble_set_min_content_size(win->ghostwin, height_floor);
  }
#else
  (void)C;
  (void)region;
#endif
}

static void agent_bubble_footer_region_draw(const bContext *C, ARegion *region)
{
  agent_bubble_sync_footer_window_size(C, region);

  /* Read footer background from the Agent Bubble theme.  The colour is
   * stored as uchar[4] (0-255) and the override API expects float (0-1).
   * If the theme field is still at its zero-init default (alpha == 0),
   * fall back to the space's main `back` colour. */
  bTheme *btheme = UI_GetTheme();
  const unsigned char *fb = btheme->space_agent_bubble.chat_footer_bg;
  float footer_bg[4];
  if (fb[3] == 0) {
    const unsigned char *bk = btheme->space_agent_bubble.back;
    footer_bg[0] = bk[0] / 255.0f;
    footer_bg[1] = bk[1] / 255.0f;
    footer_bg[2] = bk[2] / 255.0f;
    footer_bg[3] = bk[3] / 255.0f;
  }
  else {
    footer_bg[0] = fb[0] / 255.0f;
    footer_bg[1] = fb[1] / 255.0f;
    footer_bg[2] = fb[2] / 255.0f;
    footer_bg[3] = fb[3] / 255.0f;
  }
  mixie_chat_set_bg_override(footer_bg);

  mixie_chat_footer_region_draw(C, region);
  mixie_chat_clear_bg_override();
}

static void agent_bubble_footer_region_layout(const bContext *C, ARegion *region)
{
  mixie_chat_footer_region_layout(C, region);
  agent_bubble_sync_footer_window_size(C, region);
}


/* Resize the pill window AND keep Blender's wmWindow / area / region
 * dimensions in sync IMMEDIATELY (don't wait for the GHOST resize
 * event to arrive next frame).
 *
 * Why this matters: Mixar_WindowForceSize resizes the NSWindow at
 * the AppKit layer. Blender catches the resize via GHOST_kEventWindowSize
 * and updates wmWindow::sizex/sizey + recomputes area & region
 * winrct on the NEXT event-loop iteration. Until that happens, the
 * header region still has its OLD width — and the separator_spacer
 * sandwich in header.py centres content within the old width, not
 * the new one, so the user sees the icon+text horizontally
 * off-centre. By writing the new sizes onto the wmWindow and
 * calling ED_area_init right here, the header re-lays out at the
 * new dimensions in the very next draw. */
static void pill_set_size(bContext *C, int width, int height, float radius)
{
  if (g_pill_ghostwin == nullptr) {
    return;
  }
#if defined(__APPLE__) || defined(_WIN32)
  Mixar_WindowForceSize(g_pill_ghostwin, width, height);
  Mixar_WindowSetCornerRadius(g_pill_ghostwin, radius);
#else
  (void)width;
  (void)height;
  (void)radius;
#endif

  /* Walk the WM looking for the pill's wmWindow so we can push the
   * new dimensions through Blender's layout pass synchronously.
   *
   * IMPORTANT: NSWindow frames are in POINTS but Blender's
   * wmWindow.sizex/sizey + screen verts are in PIXELS (set from
   * convertRectToBacking under the hood). On Retina the scale is 2,
   * so writing the raw point values here gives Blender HALF the
   * actual width — the HEADER region's winrct then lands at the
   * wrong width and the separator_spacer sandwich centres content
   * against the wrong axis. Reading the actual backing-store size
   * via Mixar_WindowGetContentPixelSize matches what GHOST reports
   * to Blender on real resize events, regardless of monitor scale. */
  int pixel_width = width;
  int pixel_height = height;
#if defined(__APPLE__) || defined(_WIN32)
  Mixar_WindowGetContentPixelSize(g_pill_ghostwin, &pixel_width, &pixel_height);
  if (pixel_width <= 0 || pixel_height <= 0) {
    pixel_width = width;
    pixel_height = height;
  }
#endif

  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return;
  }
  LISTBASE_FOREACH (wmWindow *, w, &wm->windows) {
    if (w->ghostwin != g_pill_ghostwin) {
      continue;
    }
    w->sizex = pixel_width;
    w->sizey = pixel_height;
    bScreen *screen = WM_window_get_active_screen(w);
    if (screen == nullptr) {
      break;
    }
    ScrArea *area = static_cast<ScrArea *>(screen->areabase.first);
    if (area == nullptr) {
      break;
    }
    /* Push the new dimensions through to the screen layout AND
     * the area's totrct.
     *
     * area->totrct.xmax comes from area->v4->vec.x — a screen
     * vertex set during screen layout. Just calling ED_area_init
     * isn't enough: it reads totrct from existing verts, and
     * those verts still hold the OLD width. So the header lays
     * out at the OLD width and content centres against that —
     * looking visibly off-centre against the freshly-resized
     * NSWindow (the user's "not centered when minimised"
     * report).
     *
     * Update the four screen verts directly to span (0,0) to
     * (width-1, height-1), then call ED_screen_refresh which
     * recomputes every area's totrct + every region's winrct
     * from those verts. Match the order Blender uses internally:
     *   v1 = bottom-left, v2 = top-left, v3 = top-right, v4 = bottom-right.
     * Update HEADER region->sizey at the same time so our
     * area.cc overlay patch knows to use the full pill height.
     */
    /* Verts are in PIXEL space (matching wmWindow.sizex/sizey). */
    if (area->v1 != nullptr) {
      area->v1->vec.x = 0;
      area->v1->vec.y = 0;
    }
    if (area->v2 != nullptr) {
      area->v2->vec.x = 0;
      area->v2->vec.y = pixel_height - 1;
    }
    if (area->v3 != nullptr) {
      area->v3->vec.x = pixel_width - 1;
      area->v3->vec.y = pixel_height - 1;
    }
    if (area->v4 != nullptr) {
      area->v4->vec.x = pixel_width - 1;
      area->v4->vec.y = 0;
    }
    /* region->sizey is in unscaled units (Blender multiplies by
     * UI_SCALE_FAC internally) — pass the point value here, not
     * the pixel value. */
    LISTBASE_FOREACH (ARegion *, region, &area->regionbase) {
      if (region->regiontype == RGN_TYPE_HEADER) {
        region->sizey = height;
        break;
      }
    }
    ED_screen_refresh(C, wm, w);
    ED_area_tag_redraw(area);
    break;
  }
}

/* Margin (px) between the pill's bottom and the screen's visible
 * frame bottom when the bubble is minimised and the pill snaps to
 * the centre-bottom of the screen. */
#define AGENT_BUBBLE_PILL_BOTTOM_MARGIN 24

/* Bottom margin used when snapping the FULL bubble window to the
 * centre-bottom of the screen at first open (and on subsequent
 * shows). Larger than the pill margin because the bubble is taller
 * — we want a similar visual gap from the screen's bottom edge in
 * both states, not a margin measured to the window's bottom edge. */
#define AGENT_BUBBLE_BOTTOM_MARGIN 60

/* Floating status pill (child window) dimensions. Small chip that
 * sits just above the bubble's top-left and tracks its position via
 * the macOS child-window relationship (see Mixar_WindowSetParent).
 *
 * The pill is its own AGENT_BUBBLE editor window, but with the
 * WINDOW (body) and TOOLS (footer) regions hidden so only the
 * HEADER region renders. The header drawer (header.py) detects
 * "I'm in a pill window" by the small width and renders just the
 * status pill, no drag handle. The pill window itself is set
 * borderless (see Mixar_WindowSetBorderless) so its content view
 * fills the entire frame with no chrome — eliminates the "two
 * background colours" issue that titled+transparent caused on the
 * small pill window.
 *
 * 80 wide × 26 tall fits "● Idle" / "● Running" snugly. The corner
 * radius is set to 13 (half the height) to give a true pill shape
 * with fully rounded ends rather than a small rounded rectangle. */
/* 110 wide accommodates "● Running" without clipping (80 was too
 * tight — "Idle" fit but "Running" overflowed). 28 tall gives the
 * dot icon a few extra pixels of breathing room; corner radius is
 * exactly half the height so left + right ends are fully rounded
 * (true pill shape, not a small rounded rectangle). */
/* Pill has TWO sizes that swap based on bubble state:
 *
 *   * SMALL (110×28, radius 14) — when the bubble is OPEN. The pill
 *     is a child window above the bubble's top-left and only shows
 *     the live status; it should be a quiet status indicator, not
 *     compete with the chat for attention.
 *   * LARGE (160×44, radius 22) — when the bubble is MINIMISED. The
 *     pill is the only thing the user sees, anchored at the host's
 *     centre-bottom; it doubles as the click target to restore the
 *     bubble, so it needs a substantial size + readable text.
 *
 * The pill is created at SMALL size on first open, then resized
 * via Mixar_WindowForceSize + Mixar_WindowSetCornerRadius on every
 * minimise / restore transition (including the start_minimised
 * branch of the open op). */
#define AGENT_BUBBLE_PILL_WIDTH 148
#define AGENT_BUBBLE_PILL_HEIGHT 28
#define AGENT_BUBBLE_PILL_CORNER_RADIUS 14.0f

#define AGENT_BUBBLE_PILL_WIDTH_LARGE 184
#define AGENT_BUBBLE_PILL_HEIGHT_LARGE 44
#define AGENT_BUBBLE_PILL_CORNER_RADIUS_LARGE 22.0f

/* Duration (seconds) of the minimise glide animation — pill slides
 * + grows from above-bubble to centre-bottom while the bubble
 * fades out. ~0.28 s is the upper end of "responsive" UI motion;
 * shorter feels jumpy, longer feels sluggish. */
#define AGENT_BUBBLE_MINIMISE_ANIM_DURATION 0.28f
/* Gap (px) between the bottom of the pill and the top of the
 * bubble — small visual separation matching the Figma where the
 * pill floats slightly above the main bubble. */
#define AGENT_BUBBLE_PILL_GAP 6

#if defined(__APPLE__) || defined(_WIN32)
/* Saved .mixar files can restore the agent bubble's wmWindow instances
 * before this operator runs. Those windows did not pass through the
 * live create path, so their OS window styles can come back as regular
 * titled windows with min/max/close controls. Re-apply the native bubble
 * policy to any restored SPACE_AGENT_BUBBLE windows before deciding
 * whether a new bubble needs to be opened. */
static bool agent_bubble_repair_existing_windows(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return false;
  }

  bool found_bubble = false;
  void *repaired_bubble = nullptr;
  void *repaired_pill = nullptr;

  LISTBASE_FOREACH (wmWindow *, win, &wm->windows) {
    if (win->ghostwin == nullptr) {
      continue;
    }

    bScreen *screen = WM_window_get_active_screen(win);
    if (screen == nullptr || !BLI_listbase_is_single(&screen->areabase)) {
      continue;
    }

    ScrArea *area = static_cast<ScrArea *>(screen->areabase.first);
    if (area == nullptr || area->spacetype != SPACE_AGENT_BUBBLE) {
      continue;
    }

    bool has_body_or_footer = false;
    LISTBASE_FOREACH (ARegion *, region, &area->regionbase) {
      if (ELEM(region->regiontype, RGN_TYPE_WINDOW, RGN_TYPE_TOOLS)) {
        has_body_or_footer = true;
        break;
      }
    }

    if (has_body_or_footer) {
#ifdef __APPLE__
      Mixar_WindowMarkAsFloatingDock(win->ghostwin);
#endif
      Mixar_WindowSetChromeless(win->ghostwin, true);
      Mixar_WindowSetFloatingLevel(win->ghostwin);
      Mixar_WindowSetHidesOnDeactivate(win->ghostwin, true);
      Mixar_WindowSetCornerRadius(win->ghostwin, AGENT_BUBBLE_CORNER_RADIUS);
      const int collapsed_height = agent_bubble_collapsed_height_for_current_attachments(C);
      bubble_force_size_and_refresh(
          C, win->ghostwin, AGENT_BUBBLE_DEFAULT_WIDTH, collapsed_height);
      bubble_set_min_content_size(win->ghostwin, collapsed_height);
#ifdef _WIN32
      if (g_host_ghostwin != nullptr) {
        Mixar_WindowSetParentTracked(win->ghostwin, g_host_ghostwin);
      }
#endif
#ifdef __APPLE__
      if (g_host_ghostwin != nullptr) {
        Mixar_WindowSetParentPlain(win->ghostwin, g_host_ghostwin);
      }
      Mixar_WindowOrderFront(win->ghostwin);
#endif
      /* Snap the bubble back to the host's centre-bottom so the
       * "Open Agent" button always brings it to a predictable location
       * — even if the user previously dragged it off-screen or onto
       * another monitor. Mirrors the first-open and restore paths. */
      if (g_host_ghostwin != nullptr) {
        Mixar_WindowSnapToCentreBottomOfWindow(win->ghostwin,
                                               g_host_ghostwin,
                                               AGENT_BUBBLE_BOTTOM_MARGIN);
      }
      g_bubble_ghostwin = win->ghostwin;
      g_bubble_minimised = false;
      repaired_bubble = win->ghostwin;
      found_bubble = true;
    }
    else {
#ifdef __APPLE__
      Mixar_WindowMarkAsFloatingDock(win->ghostwin);
#endif
      Mixar_WindowSetBorderless(win->ghostwin);
      Mixar_WindowSetFloatingLevel(win->ghostwin);
      Mixar_WindowSetHidesOnDeactivate(win->ghostwin, true);
      Mixar_WindowSetCornerRadius(win->ghostwin, AGENT_BUBBLE_PILL_CORNER_RADIUS);
      Mixar_WindowSetMinContentSize(win->ghostwin, 40, 20);
      g_pill_ghostwin = win->ghostwin;
      repaired_pill = win->ghostwin;
    }
  }

  if (repaired_bubble != nullptr && repaired_pill != nullptr) {
    Mixar_WindowSetParent(repaired_pill, repaired_bubble);
    Mixar_WindowPositionAboveParent(repaired_pill,
                                    repaired_bubble,
                                    /*offset_x=*/0,
                                    /*offset_y=*/AGENT_BUBBLE_PILL_GAP);
  }

  return found_bubble;
}
#endif

static bool agent_bubble_window_contains_space(const wmWindow *win)
{
  if (win == nullptr) {
    return false;
  }

  bScreen *screen = WM_window_get_active_screen(win);
  if (screen == nullptr) {
    return false;
  }

  LISTBASE_FOREACH (ScrArea *, area, &screen->areabase) {
    if (area->spacetype == SPACE_AGENT_BUBBLE) {
      return true;
    }
  }
  return false;
}

/**
 * Reset the cached bubble/pill ghost-window pointers and minimise/expand
 * flags. Every consumer (bubble_force_size_and_refresh, pill_set_size, the
 * minimise/restore/expand ops) gates purely on `!= nullptr` and then
 * dereferences the underlying GHOST_WindowWin32 object, so once a bubble/
 * pill wmWindow is destroyed, leaving these set is a use-after-free the
 * next time one of those consumers runs.
 *
 * `wm_window_close()` (wm_window.cc) calls this itself whenever it
 * destroys a window hosting an Agent Bubble space, which is the single
 * choke point every close path funnels through (quit, save-pre purge, this
 * operator, plain `bpy.ops.wm.window_close()`, and the recursive
 * child-window close for the pill) — so callers don't need to call this
 * directly. #agent_bubble_close_all_windows below still calls it explicitly
 * too, as a belt-and-suspenders reset for stale flags when there was no
 * live window left to close.
 */
void ED_agent_bubble_windows_closed()
{
  g_bubble_ghostwin = nullptr;
  g_pill_ghostwin = nullptr;
  g_bubble_minimised = false;
  g_bubble_expanded = false;
}

void ED_agent_bubble_window_freed(const void *ghostwin)
{
  if (ghostwin == nullptr) {
    return;
  }
  /* Match by GHOST pointer, not by space type: this runs from
   * wm_window_free() for EVERY window, including teardown paths that never
   * pass through wm_window_close() — replacing the window-manager on file
   * load (#wm_close_and_free) frees the previous session's bubble, pill AND
   * host windows directly. Any cached pointer equal to the dying GHOST
   * window is about to dangle; clear exactly those. */
  if (ghostwin == g_bubble_ghostwin) {
    g_bubble_ghostwin = nullptr;
    g_bubble_minimised = false;
    g_bubble_expanded = false;
  }
  if (ghostwin == g_pill_ghostwin) {
    g_pill_ghostwin = nullptr;
  }
  if (ghostwin == g_host_ghostwin) {
    g_host_ghostwin = nullptr;
  }
}

static int agent_bubble_close_all_windows(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return 0;
  }

  /* Save the context window — wm_window_close sets CTX_wm_window to the
   * window being closed (for handler teardown), then wm_window_free nulls
   * it.  Callers (Python save_pre, quit-dialog callback) expect a valid
   * context window after this function returns. */
  wmWindow *ctx_win = CTX_wm_window(C);

  /* Save the host handle before destruction — we need to restore focus
   * afterwards because DestroyWindow on Windows transfers activation to
   * the next window in Z-order (often another application). */
  void *host_ghost = g_host_ghostwin;

  int closed = 0;
  bool closed_one = true;
  while (closed_one) {
    closed_one = false;
    LISTBASE_FOREACH (wmWindow *, win, &wm->windows) {
      if (!agent_bubble_window_contains_space(win)) {
        continue;
      }
      /* Avoid restoring a freed context window. */
      if (win == ctx_win) {
        ctx_win = nullptr;
      }
      wm_window_close(C, wm, win);
      closed++;
      closed_one = true;
      break;
    }
  }

  ED_agent_bubble_windows_closed();

#ifdef _WIN32
  /* Restore focus to the host window so the OS doesn't activate a
   * background application after the bubble HWNDs were destroyed. */
  if (closed > 0) {
    if (host_ghost != nullptr) {
      Mixar_WindowMakeKey(host_ghost);
    }
    else {
      /* Fallback: pick the first remaining window. */
      wmWindow *first = static_cast<wmWindow *>(wm->windows.first);
      if (first != nullptr && first->ghostwin != nullptr) {
        Mixar_WindowMakeKey(first->ghostwin);
      }
    }
  }
#endif

  /* Restore the context window so callers (Python save_pre, the quit
   * dialog callback, wm_exit_schedule_delayed) still see a valid context
   * window.
   *
   * ctx_win can be freed even when it was not the window the loop selected:
   * wm_window_close() recursively closes child windows (the pill window is a
   * WM child of the bubble window via dialog=true), so closing one bubble
   * window can free another that happened to be the context window — the
   * `win == ctx_win` guard above only catches the directly-selected case.
   * Verify ctx_win is still a live window before restoring it, and fall back
   * to the first surviving non-bubble window so we never dereference a freed
   * pointer in CTX_wm_window_set. */
  bool ctx_win_alive = false;
  LISTBASE_FOREACH (wmWindow *, win, &wm->windows) {
    if (win == ctx_win) {
      ctx_win_alive = true;
      break;
    }
  }
  if (!ctx_win_alive) {
    ctx_win = nullptr;
    LISTBASE_FOREACH (wmWindow *, win, &wm->windows) {
      if (!agent_bubble_window_contains_space(win)) {
        ctx_win = win;
        break;
      }
    }
  }
  if (ctx_win != nullptr) {
    CTX_wm_window_set(C, ctx_win);
  }

  return closed;
}

/* -------------------------------------------------------------------- */
/** \name Space Callbacks
 * \{ */

static SpaceLink *agent_bubble_create(const ScrArea * /*area*/, const Scene * /*scene*/)
{
  ARegion *region;
  SpaceAgentBubble *sbubble = MEM_callocN<SpaceAgentBubble>("initagentbubble");
  sbubble->spacetype = SPACE_AGENT_BUBBLE;
  /* Mirror SpaceMixieChat init — sel_message_index = -1 means no
   * active selection. The struct is laid out identically to
   * SpaceMixieChat so mixie chat's main region C++ code can read
   * these fields safely via reinterpret_cast. */
  sbubble->sel_message_index = -1;
  sbubble->sel_start = 0;
  sbubble->sel_end = 0;

  /* Header — top.
   *
   * Hosts the status pill (Idle / Running) on the right and acts as
   * the user-visible drag-to-expand affordance: the boundary at the
   * bottom of the header is what the user grabs to grow the body
   * region and reveal chat history. Kept visible by default. */
  region = BKE_area_region_new();
  BLI_addtail(&sbubble->regionbase, region);
  region->regiontype = RGN_TYPE_HEADER;
  region->alignment = RGN_ALIGN_TOP;

  /* Footer — bottom — input field + send button.
   * Use RGN_TYPE_TOOLS instead of RGN_TYPE_FOOTER because footer regions
   * are size-clamped to ~52 px by Blender's layout system (same fix the
   * mixie chat editor uses). TOOLS regions honor sizey requests.
   *
   * 200 px fits the multi-line input grown to its max (4 lines ≈ 120 px)
   * + the action row with mode dropdown and send button (~40 px) +
   * padding. The user can still drag-resize the region if they want
   * more or less space. */
  region = BKE_area_region_new();
  BLI_addtail(&sbubble->regionbase, region);
  region->regiontype = RGN_TYPE_TOOLS;
  region->alignment = RGN_ALIGN_BOTTOM;
  region->sizey = AGENT_BUBBLE_FOOTER_HEIGHT;

  /* Main — scrollable chat history.
   *
   * Always visible (NO RGN_FLAG_HIDDEN). The hide/un-hide approach
   * via screen.region_toggle was tried multiple times and consistently
   * broke things: panel system not re-initialised after un-hide,
   * streaming stopped working, occasionally double-rendered headers
   * across windows. Keeping the region always visible avoids all of
   * that — the small remaining body-slack (≈ 30 px Blender minimum)
   * is a worthwhile trade for streaming staying intact. */
  region = BKE_area_region_new();
  BLI_addtail(&sbubble->regionbase, region);
  region->regiontype = RGN_TYPE_WINDOW;

  return (SpaceLink *)sbubble;
}

static void agent_bubble_free(SpaceLink *sl)
{
  /* SpaceAgentBubble is layout-identical to SpaceMixieChat — see
   * DNA_space_types.h. Free the per-space MixieChatRuntime via mixie
   * chat's helper (clears layout cache, hover state, etc.). Cast is
   * safe: same field offsets. */
  SpaceMixieChat *smixie = reinterpret_cast<SpaceMixieChat *>(sl);
  mixie_chat_free_runtime(smixie);

  /* NOTE: Do NOT clear g_bubble_ghostwin / g_pill_ghostwin /
   * g_host_ghostwin here. This callback fires for EVERY
   * AGENT_BUBBLE space that gets freed — including the pill window's
   * space and the bubble's space when hidden (on some platforms the
   * WM tears down + rebuilds spaces during hide/show). Clearing
   * unconditionally would nuke the pill pointer when the bubble
   * space is freed, then the restore path finds null pointers and
   * the autoshow creates a duplicate.
   *
   * This is safe ONLY because every path that actually destroys the
   * underlying bubble/pill wmWindow (not just frees this SpaceLink)
   * is required to call ED_agent_bubble_windows_closed() itself —
   * see that function's docstring. A stale-but-not-yet-reset pointer
   * here is fine; a stale pointer some consumer still dereferences
   * after the window is gone is a use-after-free, not "harmless". */
}

static void agent_bubble_init(wmWindowManager * /*wm*/, ScrArea * /*area*/)
{
  /* Phase 1: nothing. The footer's sizey was set in create(); regions
   * stay at their initial sizes. */
}

static SpaceLink *agent_bubble_duplicate(SpaceLink *sl)
{
  SpaceAgentBubble *new_sbubble = static_cast<SpaceAgentBubble *>(MEM_dupallocN(sl));
  new_sbubble->runtime = nullptr;
  return (SpaceLink *)new_sbubble;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Header Region — status pill
 * \{ */

void agent_bubble_header_region_init(wmWindowManager * /*wm*/, ARegion *region)
{
  ED_region_header_init(region);
}

void agent_bubble_header_region_draw(const bContext *C, ARegion *region)
{
  /* Header TH_BACK resolves to ts->header from the Agent Bubble theme,
   * so no manual override is needed here. */
  ED_region_header(C, region);
}

/** \} */

/* Main + footer regions are wired to mixie chat's custom-drawn
 * callbacks in spacetype registration below. SpaceAgentBubble is
 * layout-identical to SpaceMixieChat, so the chat history renders
 * with full markdown / message bubbles / scroll-to-bottom and the
 * composer renders with auto-grow / attachments / send button. */


/* -------------------------------------------------------------------- */
/** \name Operator and Keymap Registration
 * \{ */

/* (Mixar_* extern declarations and AGENT_BUBBLE_* dimension defines
 * live near the top of this file — moved up there so
 * agent_bubble_create() can reference the region heights it needs to
 * set on the regions it constructs.) */

/* -------------------------------------------------------------------- */
/** \name Show Agent Bubble Window Operator
 *
 * Opens the AGENT_BUBBLE editor in a small chrome-less TEMP window via
 * WM_window_open_temp — same code path Blender uses for the
 * Preferences / Drivers Editor / Info Log popups. The result is a
 * dedicated window with a single AGENT_BUBBLE area, no workspace tabs
 * or topbar — visually a popup, not a second main window.
 *
 * Two extra steps on top of the upstream pattern:
 *   1. dialog=true so the window is created as a child of the parent
 *      and stays above it (NSWindowAbove on macOS) when the user
 *      clicks back on the main window. Without this the bubble drops
 *      behind the main window the moment focus leaves.
 *   2. Mixar_WindowSetChromeless to strip the macOS title bar and
 *      traffic-light buttons. dialog=true alone hides the minimize
 *      button but leaves close + zoom + the title bar visible.
 *
 * The Python wrapper (mixar.agent_bubble_open_window) calls this op,
 * and the Window menu hook in the agent_bubble_module bootstrap also
 * invokes it directly.
 * \{ */

static wmOperatorStatus agent_bubble_show_window_exec(bContext *C, wmOperator *op)
{
  const bool start_minimised = RNA_boolean_get(op->ptr, "start_minimised");

  /* Stash the window the op was invoked from BEFORE WM_window_open
   * runs (which switches CTX_wm_window to the new bubble window).
   * Used later by the minimise / restore paths to re-parent the
   * pill onto Mixar's main NSWindow so it tracks the user's drags
   * instead of staying pinned to a screen coordinate.
   *
   * Skip this when the op is invoked WITH the bubble already as the
   * active context (e.g. workspace-change autoshow firing while the
   * bubble has focus) — we only want a "main" window pointer here. */
  {
    wmWindow *invoker = CTX_wm_window(C);
    if (invoker != nullptr && invoker->ghostwin != nullptr &&
        invoker->ghostwin != g_bubble_ghostwin &&
        invoker->ghostwin != g_pill_ghostwin)
    {
      g_host_ghostwin = invoker->ghostwin;
    }
  }

#if defined(__APPLE__) || defined(_WIN32)
  if (!start_minimised && agent_bubble_repair_existing_windows(C)) {
    return OPERATOR_FINISHED;
  }

  /* If the bubble already exists but is currently MINIMISED (the
   * user clicked the yellow traffic light, then asked to "Open
   * Agent Bubble Window" again from the Window menu), restore the
   * existing bubble instead of spawning a duplicate. WM_window_open's
   * temp-reuse dedup misses this case because the bubble window was
   * orderOut'd — it's still alive but hidden, and the dedup loop
   * doesn't always see hidden temp windows.
   *
   * Mirrors mixar_bubble_restore_exec: snap the bubble to the host's
   * current centre-bottom, orderFront, detach the pill from the
   * host, re-attach it to the bubble. */
  if (g_bubble_ghostwin != nullptr && g_bubble_minimised) {
    if (start_minimised) {
      if (g_pill_ghostwin != nullptr) {
        pill_set_size(C,
                      AGENT_BUBBLE_PILL_WIDTH_LARGE,
                      AGENT_BUBBLE_PILL_HEIGHT_LARGE,
                      AGENT_BUBBLE_PILL_CORNER_RADIUS_LARGE);
      }
      if (g_pill_ghostwin != nullptr && g_host_ghostwin != nullptr) {
        Mixar_WindowAnchorAtParentCentreBottom(
            g_pill_ghostwin, g_host_ghostwin, AGENT_BUBBLE_PILL_BOTTOM_MARGIN);
#ifdef __APPLE__
        Mixar_WindowOrderFront(g_pill_ghostwin);
#endif
      }
      return OPERATOR_FINISHED;
    }

    if (g_host_ghostwin != nullptr) {
      Mixar_WindowSnapToCentreBottomOfWindow(g_bubble_ghostwin,
                                             g_host_ghostwin,
                                             AGENT_BUBBLE_BOTTOM_MARGIN);
    }
    const int collapsed_height = agent_bubble_collapsed_height_for_current_attachments(C);
    bubble_force_size_and_refresh(
        C, g_bubble_ghostwin, AGENT_BUBBLE_DEFAULT_WIDTH, collapsed_height);
    bubble_set_min_content_size(g_bubble_ghostwin, collapsed_height);
    /* Re-arm hidesOnDeactivate AND re-attach to host BEFORE showing
     * (mirrors restore_exec) — avoids Win32 Alt+Tab race. */
    Mixar_WindowSetHidesOnDeactivate(g_bubble_ghostwin, true);
    if (g_host_ghostwin != nullptr) {
#ifdef _WIN32
      Mixar_WindowSetParentTracked(g_bubble_ghostwin, g_host_ghostwin);
#else
      Mixar_WindowSetParentPlain(g_bubble_ghostwin, g_host_ghostwin);
#endif
    }
    Mixar_WindowOrderFront(g_bubble_ghostwin);
    /* Re-parent pill directly from host → bubble (no detach step)
     * so it's never an unowned visible window. */
    if (g_pill_ghostwin != nullptr) {
      pill_set_size(C,
                    AGENT_BUBBLE_PILL_WIDTH,
                    AGENT_BUBBLE_PILL_HEIGHT,
                    AGENT_BUBBLE_PILL_CORNER_RADIUS);
      Mixar_WindowSetParent(g_pill_ghostwin, g_bubble_ghostwin);
      Mixar_WindowPositionAboveParent(g_pill_ghostwin,
                                      g_bubble_ghostwin,
                                      /*offset_x=*/0,
                                      /*offset_y=*/AGENT_BUBBLE_PILL_GAP);
    }
    g_bubble_minimised = false;
    return OPERATOR_FINISHED;
  }
#endif

  /* WM_window_open with temp=true dedupes against existing temp
   * windows of the same space type (see the temp-reuse loop in
   * WM_window_open), so repeated invocations focus the existing
   * bubble rather than spawning another. */
  rcti rect;
  rect.xmin = 0;
  rect.ymin = 0;
  rect.xmax = AGENT_BUBBLE_DEFAULT_WIDTH;
  rect.ymax = agent_bubble_collapsed_height_for_current_attachments(C);

  wmWindow *win = WM_window_open(C,
                                 "Agent Bubble",
                                 &rect,
                                 SPACE_AGENT_BUBBLE,
                                 /*toplevel=*/false,
                                 /*dialog=*/true,
                                 /*temp=*/true,
                                 WIN_ALIGN_PARENT_CENTER,
                                 /*area_setup_fn=*/nullptr,
                                 /*area_setup_user_data=*/nullptr);
  if (win == nullptr) {
    BKE_report(op->reports, RPT_ERROR, "Failed to open Agent Bubble window");
    return OPERATOR_CANCELLED;
  }

#if defined(__APPLE__) || defined(_WIN32)
  if (win->ghostwin != nullptr) {
#ifdef __APPLE__
    /* Tag this NSWindow as a non-blocking floating dock so
     * hasDialogWindow() exempts it from the modal-dialog gate.
     * Without this tag, BlenderWindow.canBecomeKeyWindow blocks the
     * main Mixar window from becoming the macOS key window while the
     * bubble is open — meaning viewport shortcuts and mixie chat
     * typing receive no keystrokes. Must be set BEFORE any user
     * interaction (clicking back on the main window). */
    Mixar_WindowMarkAsFloatingDock(win->ghostwin);

    /* Pin the bubble to its parent's Space so it doesn't leak onto
     * another Space when the user swipes away from a full-screen
     * Mixar (the three-finger gesture / Mission Control). Without
     * this the floating bubble surfaces on top of whatever window is
     * in the Space the user switched to. See Mixar_WindowBindToParentSpace. */
    Mixar_WindowBindToParentSpace(win->ghostwin);
#endif

    /* Strip traffic lights + title bar. Safe to call on the dedup-
     * reused window too — chromeless state persists. */
    Mixar_WindowSetChromeless(win->ghostwin, true);

    /* Pin the bubble to NSFloatingWindowLevel so it stays visible
     * above the rest of Mixar's interface no matter where the user
     * clicks. The dialog=true child-window relationship was supposed
     * to do this but kept losing the bubble behind the main window
     * across various click scenarios — Floating level is the
     * reliable OS-level mechanism. */
    Mixar_WindowSetFloatingLevel(win->ghostwin);

    /* Hide the bubble when Mixar deactivates (user alt-tabs to
     * another app). Without this, the floating level keeps the
     * bubble visible above other apps' windows too — the
     * cross-app leak the user reported. AppKit handles the
     * orderOut/orderFront automatically based on app activation. */
    Mixar_WindowSetHidesOnDeactivate(win->ghostwin, true);

    /* Round the window corners to match the Figma's soft popup look.
     * Done after Chromeless so the title-bar style mask is already
     * settled — corner-rounding sets opaque=NO + clearColor which
     * doesn't play nicely with subsequent style-mask changes. */
    Mixar_WindowSetCornerRadius(win->ghostwin, AGENT_BUBBLE_CORNER_RADIUS);

    /* Force the actual NSWindow size to our requested dimensions.
     * Without this, WM_window_open's std::max-with-{200,150} clamping
     * and the OS contentMinSize floor can compose to leave the
     * window at unpredictable sizes (often much smaller than what we
     * asked for, causing the footer to collapse). */
    const int collapsed_height = agent_bubble_collapsed_height_for_current_attachments(C);
    bubble_force_size_and_refresh(
        C, win->ghostwin, AGENT_BUBBLE_DEFAULT_WIDTH, collapsed_height);
    bubble_set_min_content_size(win->ghostwin, collapsed_height);

    /* Anchor the bubble at the centre-bottom of Mixar's HOST
     * window (not the screen). WM_window_open used
     * WIN_ALIGN_PARENT_CENTER which centres on the parent window's
     * geometric centre — fine for an editor popup but the wrong
     * rest position for a chat dock. The Figma spec, the pill's
     * minimised position, and the user's mental model all sit the
     * bubble near the bottom of Mixar's window. Anchoring to the
     * host's frame (instead of the screen) keeps the bubble inside
     * Mixar even when Mixar is small/non-fullscreen — earlier
     * builds that snapped to the screen put the bubble visually
     * "below Mixar" if Mixar didn't fill the screen. */
    if (g_host_ghostwin != nullptr) {
      Mixar_WindowSnapToCentreBottomOfWindow(win->ghostwin,
                                             g_host_ghostwin,
                                             AGENT_BUBBLE_BOTTOM_MARGIN);
    }
    else {
      Mixar_WindowSnapToCentreBottom(win->ghostwin,
                                     AGENT_BUBBLE_BOTTOM_MARGIN);
    }

    /* Pin the OS-level minimum to the current collapsed bubble size so the
     * attachment-aware layout is also the smallest manually resizable layout. */
    bubble_set_min_content_size(win->ghostwin, collapsed_height);

    /* Stash the bubble's ghostwin pointer so the
     * minimise / restore / expand ops can address it later
     * regardless of which window the user invokes them from. Reset
     * the minimised flag because a freshly-opened bubble starts
     * visible. */
    g_bubble_ghostwin = win->ghostwin;
    g_bubble_minimised = false;
    g_bubble_expanded = false;
    g_bubble_had_pending_attachments = false;
    g_bubble_last_min_height = 0;

#ifdef _WIN32
    /* On Win32, GWLP_HWNDPARENT only controls Z-order — it does NOT
     * auto-track position like macOS child windows.  Install a
     * SetWinEventHook that maintains the bubble's relative offset
     * to the host, so it follows when the host moves between screens. */
    if (g_host_ghostwin != nullptr) {
      Mixar_WindowSetParentTracked(g_bubble_ghostwin, g_host_ghostwin);
    }
#else
    /* Match the restore path on macOS: make the bubble a child of
     * the main Mixar window immediately after first open. Without
     * this initial parent relationship AppKit treats the bubble as a
     * separate floating window until the user minimises/restores it,
     * which can hide it when focus returns to another Mixar editor. */
    if (g_host_ghostwin != nullptr) {
      Mixar_WindowSetParentPlain(g_bubble_ghostwin, g_host_ghostwin);
    }
#endif

    /* Floating status-pill child window.
     *
     * Only create one if this bubble doesn't already have a child
     * pill — otherwise repeated open calls (e.g. user clicks Window
     * menu twice) would spawn duplicate pills that all stack above
     * the bubble. The bubble itself dedups via WM_window_open's
     * temp-reuse loop; we mirror the dedup for the pill via
     * Mixar_WindowHasChildWindow.
     *
     * The pill is opened with temp=false so its own AGENT_BUBBLE
     * area doesn't get caught by the temp-reuse dedup that returned
     * the bubble window above. After creation:
     *   1. Hide WINDOW + TOOLS regions so only HEADER renders (the
     *      header drawer detects pill-mode by window width and
     *      renders just the status text, no drag handle).
     *   2. Apply chromeless + rounded corners + small forced size
     *      + tiny content-min to allow the small dimensions.
     *   3. Position above the bubble's top-left.
     *   4. Attach as macOS child window of the bubble so the pill
     *      tracks the bubble's position automatically when the user
     *      drags the bubble around the screen, and closes when the
     *      bubble closes. */
    if (!Mixar_WindowHasChildWindow(win->ghostwin)) {
      rcti pill_rect;
      pill_rect.xmin = 0;
      pill_rect.ymin = 0;
      pill_rect.xmax = AGENT_BUBBLE_PILL_WIDTH;
      pill_rect.ymax = AGENT_BUBBLE_PILL_HEIGHT;

      wmWindow *pill_win = WM_window_open(C,
                                          "Agent Bubble Status",
                                          &pill_rect,
                                          SPACE_AGENT_BUBBLE,
                                          /*toplevel=*/false,
                                          /*dialog=*/true,
                                          /*temp=*/false,
                                          WIN_ALIGN_PARENT_CENTER,
                                          /*area_setup_fn=*/nullptr,
                                          /*area_setup_user_data=*/nullptr);

      if (pill_win != nullptr) {
        /* Hide the WINDOW (body) and TOOLS (footer) regions on the
         * pill — only the HEADER region should render content. The
         * header.py drawer recognises pill-mode by checking the
         * window width (small ≈ pill, large ≈ main bubble). */
        bScreen *pill_screen = WM_window_get_active_screen(pill_win);
        if (pill_screen != nullptr) {
          ScrArea *pill_area = static_cast<ScrArea *>(
              pill_screen->areabase.first);
          if (pill_area != nullptr) {
            /* DELETE (don't just hide) the WINDOW + TOOLS regions on
             * the pill area.
             *
             * RGN_FLAG_HIDDEN keeps the region in the area's
             * regionbase and Blender draws a small click-to-expand
             * arrow at the region's edge so the user can re-show it.
             * Inside the pill that arrow rendered as a sharp-cornered
             * notch poking through the rounded contentView — visible
             * to the user as a stray "^" in the bottom-right of the
             * pill plus a darker rectangle behind the label.
             *
             * Removing the regions outright means there's nothing
             * for Blender to draw an azone on, and the HEADER region
             * (made dynamically tall by our area.cc patch + the
             * sizey assignment below) covers the entire pill with a
             * single consistent background. */
            SpaceType *st = BKE_spacetype_from_id(SPACE_AGENT_BUBBLE);
            ARegion *region = static_cast<ARegion *>(pill_area->regionbase.first);
            while (region != nullptr) {
              ARegion *next = region->next;
              if (region->regiontype == RGN_TYPE_WINDOW ||
                  region->regiontype == RGN_TYPE_TOOLS)
              {
                ED_region_exit(C, region);
                BLI_remlink(&pill_area->regionbase, region);
                BKE_area_region_free(st, region);
                MEM_freeN(region);
              }
              else if (region->regiontype == RGN_TYPE_HEADER) {
                /* Stretch the HEADER to fill the entire pill window.
                 * Our area.cc overlay patch honours region->sizey for
                 * SPACE_AGENT_BUBBLE headers (default Blender clamps
                 * every header to ED_area_headersize). */
                region->sizey = AGENT_BUBBLE_PILL_HEIGHT;
                region->flag &= ~RGN_FLAG_DYNAMIC_SIZE;
              }
              region = next;
            }
            /* ED_area_init signature: (bContext *C, const wmWindow *win,
             * ScrArea *area). Pass C directly — earlier versions
             * passed CTX_wm_manager(C) here which doesn't compile. */
            ED_area_init(C, pill_win, pill_area);
          }
        }

        if (pill_win->ghostwin != nullptr) {
#ifdef __APPLE__
          /* Tag the pill as a non-blocking floating dock too — same
           * reason as the bubble: keeps hasDialogWindow() from
           * blocking the main window's key-window eligibility. */
          Mixar_WindowMarkAsFloatingDock(pill_win->ghostwin);

          /* Pin the pill to its parent's Space too — when the bubble
           * is minimised the pill is detached and re-parented onto the
           * host window, so it must carry the same Space-binding to
           * avoid leaking onto another Space in full-screen Mixar. */
          Mixar_WindowBindToParentSpace(pill_win->ghostwin);
#endif

          /* Borderless (NOT chromeless): chromeless leaves the
           * styleMask with TITLED + transparent title bar, which on
           * the small pill window rendered as a darker band across
           * the top (the "two background colours" the user
           * reported). Borderless removes the title bar entirely so
           * the pill's contentView fills the frame with a single
           * solid colour. */
          Mixar_WindowSetBorderless(pill_win->ghostwin);

          /* Pin the pill to floating level too. As a child window of
           * the bubble it'd inherit the bubble's level, but when the
           * user minimises the bubble we detach the pill and need
           * it to stay above other windows on its own. */
          Mixar_WindowSetFloatingLevel(pill_win->ghostwin);

          /* Pill also hides when Mixar deactivates — same anti-leak
           * treatment as the bubble. */
          Mixar_WindowSetHidesOnDeactivate(pill_win->ghostwin, true);

          /* Half-height corner radius gives a true pill silhouette
           * (fully rounded left + right ends) rather than a small
           * rounded rectangle. */
          Mixar_WindowSetCornerRadius(pill_win->ghostwin,
                                      AGENT_BUBBLE_PILL_CORNER_RADIUS);

          /* Override macOS contentMinSize so setFrame can shrink to
           * the small pill dimensions. 40×20 is well below our 80×26
           * target so the resize isn't clamped. */
          Mixar_WindowSetMinContentSize(pill_win->ghostwin, 40, 20);
          Mixar_WindowForceSize(pill_win->ghostwin,
                                AGENT_BUBBLE_PILL_WIDTH,
                                AGENT_BUBBLE_PILL_HEIGHT);

          /* Position pill above bubble's top-left, with the gap. */
          Mixar_WindowPositionAboveParent(pill_win->ghostwin,
                                          win->ghostwin,
                                          /*offset_x=*/0,
                                          /*offset_y=*/AGENT_BUBBLE_PILL_GAP);

          /* Attach as macOS child window — pill follows bubble's
           * frame automatically and closes with it. */
          Mixar_WindowSetParent(pill_win->ghostwin, win->ghostwin);

          /* Stash the pill ghostwin too — needed by the minimise /
           * restore ops which detach + re-attach the pill from the
           * bubble. */
          g_pill_ghostwin = pill_win->ghostwin;
        }
      }
    }

#ifdef __APPLE__
    /* Force a full Blender redraw so the bubble doesn't show stale
     * framebuffer content on its first visible frame. Must happen
     * AFTER all setup (size, parent, pill) and BEFORE the optional
     * start-minimised path which hides the bubble again. */
    if (!start_minimised) {
      Mixar_WindowOrderFront(g_bubble_ghostwin);
    }
#endif

    /* Optional: start in minimised (pill-only) state.
     *
     * Used by the workspace-change-after-explicit-close autoshow path
     * (see _on_workspace_change in agent_bubble_module.py): the user
     * closed the bubble on purpose, but flipping workspaces should
     * still surface the agent's status without forcing the full
     * window back. We do the minimise here, before AppKit pumps the
     * run loop and renders a frame, so there's no visible flash of
     * the full bubble appearing-then-vanishing.
     *
     * Mirrors mixar_bubble_minimise_exec exactly: detach the pill,
     * orderOut the bubble, anchor the pill at the centre-bottom of
     * Mixar's host window (so it tracks the user's drags), set the
     * minimised flag. */
    if (start_minimised) {
      Mixar_WindowSetHidesOnDeactivate(g_bubble_ghostwin, false);
      pill_set_size(C,
                    AGENT_BUBBLE_PILL_WIDTH_LARGE,
                    AGENT_BUBBLE_PILL_HEIGHT_LARGE,
                    AGENT_BUBBLE_PILL_CORNER_RADIUS_LARGE);
#ifdef _WIN32
      /* Win32: re-parent pill directly bubble→host so it's never
       * an unowned visible window (avoids Alt+Tab race).  Then
       * detach bubble from host and hide it. */
      if (g_pill_ghostwin != nullptr && g_host_ghostwin != nullptr) {
        Mixar_WindowAnchorAtParentCentreBottom(
            g_pill_ghostwin, g_host_ghostwin, AGENT_BUBBLE_PILL_BOTTOM_MARGIN);
      }
      if (g_host_ghostwin != nullptr) {
        Mixar_WindowDetachFromParent(g_bubble_ghostwin, g_host_ghostwin);
      }
#else
      /* macOS: detach pill from bubble first (AppKit cascades hide
       * to children), then detach bubble from host. */
      if (g_pill_ghostwin != nullptr) {
        Mixar_WindowDetachFromParent(g_pill_ghostwin, g_bubble_ghostwin);
      }
      if (g_host_ghostwin != nullptr) {
        Mixar_WindowDetachFromParent(g_bubble_ghostwin, g_host_ghostwin);
      }
#endif
      Mixar_WindowOrderOut(g_bubble_ghostwin);
      if (g_pill_ghostwin != nullptr) {
        if (g_host_ghostwin != nullptr) {
          /* Same anchor helper as the manual minimise path — installs
           * Move + Resize observers on the host so the pill stays
           * pinned to the host's centre-bottom across drags (within
           * a monitor, across monitors) and host resizes. */
          Mixar_WindowAnchorAtParentCentreBottom(
              g_pill_ghostwin,
              g_host_ghostwin,
              AGENT_BUBBLE_PILL_BOTTOM_MARGIN);
        }
        else {
          /* No host window known (e.g. opened from an unusual context):
           * fall back to screen-relative snapping so the pill is at
           * least visible somewhere predictable. */
          Mixar_WindowSnapToCentreBottom(g_pill_ghostwin,
                                         AGENT_BUBBLE_PILL_BOTTOM_MARGIN);
        }
      }
      g_bubble_minimised = true;
    }

    /* Return keyboard focus to the host so viewport shortcuts keep
     * working.  WM_window_open calls makeKeyAndOrderFront which steals
     * focus — we undo that here. */
    if (g_host_ghostwin != nullptr) {
      Mixar_WindowMakeKey(g_host_ghostwin);
    }
  }
#endif

  return OPERATOR_FINISHED;
}

void MIXAR_OT_agent_bubble_show_window(wmOperatorType *ot)
{
  ot->name = "Show Agent Bubble Window";
  /* C-style idname; Blender exposes it to Python as
   * bpy.ops.mixar.agent_bubble_show_window. Using the dotted form
   * here would silently break Python lookup (same gotcha
   * mixie_chat_agent_bubble.cc warns about). */
  ot->idname = "MIXAR_OT_agent_bubble_show_window";
  ot->description =
      "Open the Agent Bubble chat in a small floating Blender window";

  ot->exec = agent_bubble_show_window_exec;
  /* No poll — universally callable. The exec handles the no-context
   * failure case via WM_window_open_temp returning nullptr. */

  /* start_minimised: open in pill-only state (full bubble window
   * hidden, pill snapped to centre-bottom). Used by the workspace-
   * change autoshow when the user has explicitly closed the bubble:
   * we still want the agent's status surfaced but not the full chat.
   * Default false so all existing call sites get the unchanged
   * "open the full bubble" behaviour. */
  RNA_def_boolean(ot->srna,
                  "start_minimised",
                  false,
                  "Start Minimised",
                  "Open with the full bubble window hidden and only the "
                  "status pill visible at the centre-bottom");
}

static wmOperatorStatus agent_bubble_purge_windows_exec(bContext *C, wmOperator *op)
{
  const int closed = agent_bubble_close_all_windows(C);
  RNA_int_set(op->ptr, "closed_count", closed);
  return OPERATOR_FINISHED;
}

void MIXAR_OT_agent_bubble_purge_windows(wmOperatorType *ot)
{
  ot->name = "Purge Agent Bubble Windows";
  ot->idname = "MIXAR_OT_agent_bubble_purge_windows";
  ot->description = "Close all transient Agent Bubble overlay windows";

  ot->exec = agent_bubble_purge_windows_exec;

  RNA_def_int(ot->srna,
              "closed_count",
              0,
              0,
              INT_MAX,
              "Closed Count",
              "Number of Agent Bubble windows closed",
              0,
              INT_MAX);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Set Agent Bubble Window Size Operator
 *
 * Python-callable wrapper around Mixar_WindowForceSize. The
 * mixar.bubble_toggle_history operator invokes this from Python to
 * grow/shrink the bubble window in lockstep with the body region's
 * hidden state. Width/height are Blender pixel dimensions; the Cocoa
 * helper converts to AppKit points before applying the frame-rect
 * conversion and contentMinSize override that lets us shrink below
 * macOS's normal floor.
 * \{ */

static wmOperatorStatus mixar_bubble_set_size_exec(bContext *C, wmOperator *op)
{
  wmWindow *win = CTX_wm_window(C);
  if (win == nullptr || win->ghostwin == nullptr) {
    return OPERATOR_CANCELLED;
  }

  const int width = RNA_int_get(op->ptr, "width");
  const int height = RNA_int_get(op->ptr, "height");

#if defined(__APPLE__) || defined(_WIN32)
  bubble_force_size_and_refresh(C, win->ghostwin, width, height);
#  ifdef __APPLE__
  Mixar_WindowOrderFront(win->ghostwin);
#  endif
#else
  /* Non-macOS: best-effort no-op for now. Windows / Linux GHOST
   * doesn't have the same chrome-stripping pipeline as Cocoa, so
   * resize would need its own platform implementation. */
  (void)width;
  (void)height;
#endif

  return OPERATOR_FINISHED;
}

void MIXAR_OT_bubble_set_size(wmOperatorType *ot)
{
  ot->name = "Set Agent Bubble Window Size";
  ot->idname = "MIXAR_OT_bubble_set_size";
  ot->description = "Internal: resize the Agent Bubble floating window";

  ot->exec = mixar_bubble_set_size_exec;

  RNA_def_int(ot->srna,
              "width",
              AGENT_BUBBLE_DEFAULT_WIDTH,
              100,
              4000,
              "Width",
              "Target window width in Blender pixels",
              100,
              4000);
  RNA_def_int(ot->srna,
              "height",
              AGENT_BUBBLE_DEFAULT_HEIGHT,
              100,
              4000,
              "Height",
              "Target window height in Blender pixels",
              100,
              4000);
}

/**
 * Force a refresh of the bubble window — same proven path used by
 * minimize / restore / expand.  This is the only reliable way on
 * Windows to make a temp window repaint; Python's area.tag_redraw()
 * sets internal flags but doesn't generate a GHOST event to wake the
 * draw loop for non-focused windows.
 */
static void agent_bubble_force_redraw(bContext *C)
{
  if (g_bubble_ghostwin == nullptr || g_bubble_minimised) {
    return;
  }
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return;
  }
  LISTBASE_FOREACH (wmWindow *, w, &wm->windows) {
    if (w->ghostwin != g_bubble_ghostwin) {
      continue;
    }
    bScreen *screen = WM_window_get_active_screen(w);
    if (screen == nullptr) {
      break;
    }
    ED_screen_refresh(C, wm, w);
    ScrArea *area = static_cast<ScrArea *>(screen->areabase.first);
    if (area != nullptr) {
      ED_area_tag_redraw(area);
    }
    break;
  }
}

static wmOperatorStatus mixar_bubble_sync_attachment_size_exec(bContext *C, wmOperator *op)
{
#if defined(__APPLE__) || defined(_WIN32)
  const bool force_attachment_height = RNA_boolean_get(op->ptr, "force_attachment_height");
  if (force_attachment_height && g_bubble_ghostwin != nullptr && !g_bubble_minimised &&
      !g_bubble_expanded)
  {
    /* Use 1 (not the actual count) because this fires before the
     * pending attachment list is updated — we just need the "has
     * attachments" height floor to pre-size the bubble. */
    const int height = agent_bubble_height_floor_for_attachments(1);
    bubble_force_size_and_refresh(C, g_bubble_ghostwin, AGENT_BUBBLE_DEFAULT_WIDTH, height);
    bubble_set_min_content_size(g_bubble_ghostwin, height);
    g_bubble_had_pending_attachments = true;
    return OPERATOR_FINISHED;
  }
  agent_bubble_sync_footer_window_size(C, CTX_wm_region(C));
  /* Always force a redraw — agent_bubble_sync_footer_window_size
   * may early-return without tagging when the bubble is already the
   * right size, but the footer thumbnails still need rendering. */
  agent_bubble_force_redraw(C);
  return OPERATOR_FINISHED;
#else
  (void)C;
  return OPERATOR_CANCELLED;
#endif
}

void MIXAR_OT_bubble_sync_attachment_size(wmOperatorType *ot)
{
  ot->name = "Sync Agent Bubble Attachment Size";
  ot->idname = "MIXAR_OT_bubble_sync_attachment_size";
  ot->description = "Internal: sync Agent Bubble size with pending image attachments";

  ot->exec = mixar_bubble_sync_attachment_size_exec;

  RNA_def_boolean(ot->srna,
                  "force_attachment_height",
                  false,
                  "Force Attachment Height",
                  "Force the visible bubble to the attachment collapsed height");
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Begin Window-Drag Operator
 *
 * Python-callable wrapper around Mixar_WindowBeginDrag. The Python
 * drag modal calls this once on mouse-down — AppKit's
 * performWindowDragWithEvent: takes over from there and tracks the
 * drag natively until the user releases the mouse. Eliminates the
 * per-frame Python / bpy.ops overhead that made the previous
 * delta-based implementation laggy.
 * \{ */

static wmOperatorStatus mixar_bubble_window_begin_drag_exec(bContext *C, wmOperator * /*op*/)
{
  wmWindow *win = CTX_wm_window(C);
  if (win == nullptr || win->ghostwin == nullptr) {
    return OPERATOR_CANCELLED;
  }

#if defined(__APPLE__) || defined(_WIN32)
  Mixar_WindowBeginDrag(win->ghostwin);
#endif

  return OPERATOR_FINISHED;
}

void MIXAR_OT_bubble_window_begin_drag(wmOperatorType *ot)
{
  ot->name = "Begin Agent Bubble Window Drag";
  ot->idname = "MIXAR_OT_bubble_window_begin_drag";
  ot->description = "Internal: start Agent Bubble window drag";
  ot->exec = mixar_bubble_window_begin_drag_exec;
}

static wmOperatorStatus mixar_bubble_window_update_drag_exec(bContext *C,
                                                             wmOperator * /*op*/)
{
  wmWindow *win = CTX_wm_window(C);
  if (win == nullptr || win->ghostwin == nullptr) {
    return OPERATOR_CANCELLED;
  }
#ifdef _WIN32
  Mixar_WindowUpdateDrag(win->ghostwin);
#endif
  return OPERATOR_FINISHED;
}

void MIXAR_OT_bubble_window_update_drag(wmOperatorType *ot)
{
  ot->name = "Update Agent Bubble Window Drag";
  ot->idname = "MIXAR_OT_bubble_window_update_drag";
  ot->description = "Internal: update Agent Bubble window position during drag";
  ot->exec = mixar_bubble_window_update_drag_exec;
}

static wmOperatorStatus mixar_bubble_window_end_drag_exec(bContext *C,
                                                          wmOperator * /*op*/)
{
  wmWindow *win = CTX_wm_window(C);
  if (win == nullptr || win->ghostwin == nullptr) {
    return OPERATOR_CANCELLED;
  }
#ifdef _WIN32
  Mixar_WindowEndDrag(win->ghostwin);
#endif
  return OPERATOR_FINISHED;
}

void MIXAR_OT_bubble_window_end_drag(wmOperatorType *ot)
{
  ot->name = "End Agent Bubble Window Drag";
  ot->idname = "MIXAR_OT_bubble_window_end_drag";
  ot->description = "Internal: end Agent Bubble window drag";
  ot->exec = mixar_bubble_window_end_drag_exec;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Minimise / Restore / Toggle-Expand Operators
 *
 * Drive the yellow + green "traffic light" buttons in the bubble's
 * header and the pill window's click-to-restore handler.
 *
 *   * MIXAR_OT_bubble_minimise — yellow click. Detach the pill from
 *     the bubble (so it survives the parent's hide), orderOut the
 *     bubble, snap the now-orphan pill to the centre-bottom of the
 *     screen. Sets g_bubble_minimised = true.
 *   * MIXAR_OT_bubble_restore — invoked by clicking the pill while
 *     minimised. orderFront the bubble (it remembers its frame),
 *     re-attach the pill as a child window (Mixar_WindowSetParent
 *     also re-positions it above the parent's top-left). Clears
 *     g_bubble_minimised. No-op when not minimised.
 *   * MIXAR_OT_bubble_toggle_expand — green click. Toggles the
 *     bubble between the collapsed default (AGENT_BUBBLE_DEFAULT_HEIGHT) and the
 *     expanded chat-history view. State tracked in
 *     g_bubble_expanded.
 *
 * All three ops gracefully no-op when the static window pointers
 * are null (e.g. the bubble was never opened in this session).
 * \{ */

#if defined(__APPLE__) || defined(_WIN32)
/* Tail of the minimise glide animation: hide the bubble, reset its
 * alpha for next time, and install the live host→pill anchor.
 * Scheduled by Mixar_DispatchMainAfter at the end of the
 * NSAnimationContext duration so it runs exactly when the slide
 * finishes. user_data is unused — we read the static window
 * pointers directly. Defined as a plain C function (not a lambda
 * with capture) because Mixar_DispatchMainAfter takes a function
 * pointer. */
static void minimise_anim_finish(void * /*user_data*/)
{
  if (g_pill_ghostwin != nullptr && g_host_ghostwin != nullptr) {
#ifdef _WIN32
    Mixar_WindowSetCornerRadius(g_pill_ghostwin, AGENT_BUBBLE_PILL_CORNER_RADIUS_LARGE);
    Mixar_WindowAnimateFrameToCentreBottomOfWindow(
        g_pill_ghostwin,
        g_host_ghostwin,
        AGENT_BUBBLE_PILL_WIDTH_LARGE,
        AGENT_BUBBLE_PILL_HEIGHT_LARGE,
        AGENT_BUBBLE_PILL_BOTTOM_MARGIN,
        /*duration=*/0.0f);
    Mixar_WindowAnchorAtParentCentreBottom(
        g_pill_ghostwin, g_host_ghostwin, AGENT_BUBBLE_PILL_BOTTOM_MARGIN);
#else
    Mixar_WindowAnchorAtParentCentreBottom(
        g_pill_ghostwin, g_host_ghostwin, AGENT_BUBBLE_PILL_BOTTOM_MARGIN);
#endif
  }
  if (g_bubble_ghostwin != nullptr) {
    Mixar_WindowOrderOut(g_bubble_ghostwin);
    Mixar_WindowSetAlpha(g_bubble_ghostwin, 1.0f);
  }
}
#endif

static wmOperatorStatus mixar_bubble_minimise_exec(bContext *C, wmOperator * /*op*/)
{
#if defined(__APPLE__) || defined(_WIN32)
  if (g_bubble_ghostwin == nullptr || g_bubble_minimised) {
    return OPERATOR_CANCELLED;
  }

  /* Disarm AppKit's hidesOnDeactivate so the bubble stays hidden
   * across alt-tab cycles (macOS). */
  Mixar_WindowSetHidesOnDeactivate(g_bubble_ghostwin, false);

#ifdef _WIN32
  /* Win32: the finish helper resizes, moves, and anchors the pill to
   * the host in one native step before hiding the bubble. */
  if (g_host_ghostwin != nullptr) {
    Mixar_WindowDetachFromParent(g_bubble_ghostwin, g_host_ghostwin);
  }
#else
  if (g_pill_ghostwin != nullptr) {
    pill_set_size(C,
                  AGENT_BUBBLE_PILL_WIDTH_LARGE,
                  AGENT_BUBBLE_PILL_HEIGHT_LARGE,
                  AGENT_BUBBLE_PILL_CORNER_RADIUS_LARGE);
  }
  /* macOS: detach pill from bubble first (AppKit cascades hide to
   * child windows — the pill must be detached before the bubble
   * hides or it will vanish too). */
  if (g_pill_ghostwin != nullptr) {
    Mixar_WindowDetachFromParent(g_pill_ghostwin, g_bubble_ghostwin);
  }
  if (g_host_ghostwin != nullptr) {
    Mixar_WindowDetachFromParent(g_bubble_ghostwin, g_host_ghostwin);
  }
#endif

#ifdef _WIN32
  /* On Windows the "animate" helpers are instant (no CoreAnimation),
   * so just hide the bubble and finish synchronously. The pill was
   * already re-parented to host above, so minimise_anim_finish
   * just hides the bubble and resets alpha. */
  minimise_anim_finish(nullptr);
#else
  /* macOS: animate the pill glide + bubble fade, then schedule the
   * finish callback via dispatch_after. */
  if (g_pill_ghostwin != nullptr && g_host_ghostwin != nullptr) {
    Mixar_WindowAnimateFrameToCentreBottomOfWindow(
        g_pill_ghostwin,
        g_host_ghostwin,
        AGENT_BUBBLE_PILL_WIDTH_LARGE,
        AGENT_BUBBLE_PILL_HEIGHT_LARGE,
        AGENT_BUBBLE_PILL_BOTTOM_MARGIN,
        AGENT_BUBBLE_MINIMISE_ANIM_DURATION);
  }
  Mixar_WindowAnimateAlphaTo(g_bubble_ghostwin, 0.0f,
                             AGENT_BUBBLE_MINIMISE_ANIM_DURATION);
  Mixar_DispatchMainAfter(AGENT_BUBBLE_MINIMISE_ANIM_DURATION,
                          minimise_anim_finish,
                          /*user_data=*/nullptr);
#endif

  g_bubble_minimised = true;
  return OPERATOR_FINISHED;
#else
  return OPERATOR_CANCELLED;
#endif
}

void MIXAR_OT_bubble_minimise(wmOperatorType *ot)
{
  /* Both name and description are single short words on purpose.
   * Blender renders operator tooltips inside the host NSWindow's
   * bounds; when the host is the tiny pill window (~110 px wide)
   * or the narrow bubble header, anything longer than a single word
   * gets clipped to a leading fragment ("Restore the…", "Minimise
   * the…") that looks like a UI bug. Single-word strings always fit,
   * so the tooltip — when it does pop — reads cleanly. */
  ot->name = "Minimise";
  ot->idname = "MIXAR_OT_bubble_minimise";
  ot->description = "Minimise";
  ot->exec = mixar_bubble_minimise_exec;
}


static wmOperatorStatus mixar_bubble_restore_exec(bContext *C, wmOperator * /*op*/)
{
#if defined(__APPLE__) || defined(_WIN32)
  if (g_bubble_ghostwin == nullptr || !g_bubble_minimised) {
    return OPERATOR_FINISHED;
  }

  /* Snap the bubble to the host's centre-bottom BEFORE bringing it
   * forward. orderFront alone restores the bubble at its old frame
   * origin — fine when the host hasn't moved, but if the user
   * dragged Mixar to another monitor between minimise and restore,
   * the bubble pops back on the original monitor while the pill is
   * sitting on the new one. Snapping first makes the bubble appear
   * wherever the host currently lives. */
  if (g_host_ghostwin != nullptr) {
    Mixar_WindowSnapToCentreBottomOfWindow(g_bubble_ghostwin,
                                           g_host_ghostwin,
                                           AGENT_BUBBLE_BOTTOM_MARGIN);
  }

  /* Reset attachment state so the auto-resize fires again on restore
   * if images are already attached (e.g. user attached, minimised, restored). */
  g_bubble_had_pending_attachments = false;
  g_bubble_last_min_height = 0;

  /* Ensure the bubble is fully opaque — minimise may have set alpha
   * to 0 (macOS fade animation or Win32 immediate alpha set). */
  bubble_force_size_and_refresh(
      C,
      g_bubble_ghostwin,
      AGENT_BUBBLE_DEFAULT_WIDTH,
      agent_bubble_collapsed_height_for_current_attachments(C));
  bubble_set_min_content_size(
      g_bubble_ghostwin, agent_bubble_collapsed_height_for_current_attachments(C));
  Mixar_WindowSetAlpha(g_bubble_ghostwin, 1.0f);

  /* Re-arm hidesOnDeactivate so the bubble hides/shows with the
   * app on alt-tab (macOS).  Do this before showing. */
  Mixar_WindowSetHidesOnDeactivate(g_bubble_ghostwin, true);

  /* CRITICAL: set the owner (GWLP_HWNDPARENT) BEFORE showing the
   * bubble.  On Win32 the shell decides Alt+Tab membership at
   * ShowWindow time — if the window is visible with no owner and
   * WS_EX_TOOLWINDOW somehow got stripped, it appears as a
   * separate Alt+Tab entry.  Setting the owner first avoids the
   * "visible + no owner" intermediate state entirely. */
  if (g_host_ghostwin != nullptr) {
#ifdef _WIN32
    Mixar_WindowSetParentTracked(g_bubble_ghostwin, g_host_ghostwin);
#else
    Mixar_WindowSetParentPlain(g_bubble_ghostwin, g_host_ghostwin);
#endif
  }

  /* Show the bubble (now it already has an owner). */
  Mixar_WindowOrderFront(g_bubble_ghostwin);

  /* Re-parent the pill directly from host → bubble.  This changes
   * GWLP_HWNDPARENT atomically (host→bubble) so the pill is NEVER
   * a visible window with no owner — avoiding the Alt+Tab race.
   * The old host tracking hook is overwritten by the new one. */
  if (g_pill_ghostwin != nullptr) {
    pill_set_size(C,
                  AGENT_BUBBLE_PILL_WIDTH,
                  AGENT_BUBBLE_PILL_HEIGHT,
                  AGENT_BUBBLE_PILL_CORNER_RADIUS);
    Mixar_WindowSetParent(g_pill_ghostwin, g_bubble_ghostwin);
    Mixar_WindowPositionAboveParent(g_pill_ghostwin,
                                    g_bubble_ghostwin,
                                    /*offset_x=*/0,
                                    /*offset_y=*/AGENT_BUBBLE_PILL_GAP);
  }

  g_bubble_minimised = false;
  return OPERATOR_FINISHED;
#else
  return OPERATOR_CANCELLED;
#endif
}

void MIXAR_OT_bubble_restore(wmOperatorType *ot)
{
  /* See MIXAR_OT_bubble_minimise — single-word strings to keep
   * tooltips inside the pill window's tight bounds. */
  ot->name = "Restore";
  ot->idname = "MIXAR_OT_bubble_restore";
  ot->description = "Restore";
  ot->exec = mixar_bubble_restore_exec;
}


static wmOperatorStatus mixar_bubble_toggle_expand_exec(bContext *C, wmOperator * /*op*/)
{
#if defined(__APPLE__) || defined(_WIN32)
  if (g_bubble_ghostwin == nullptr) {
    return OPERATOR_CANCELLED;
  }
  /* Toggle between the default (collapsed) and expanded sizes.
   * Mixar_WindowForceSize is bottom-anchored, so growing extends
   * the bubble's TOP edge upward; the pill child window's resize
   * observer (in Mixar_WindowSetParent) repositions it above the
   * new top automatically.
   *
   * If the bubble is near the screen TOP (e.g. the user dragged it
   * up there), naively growing to AGENT_BUBBLE_EXPANDED_HEIGHT
   * would push the bubble's top edge past the screen — and the
   * floating pill (which sits above that top) would either get
   * clipped or end up overlapping the bubble's chrome. Cap the
   * growth so the bubble's top stays at least
   * (pill height + pill gap + safety) below the visible screen
   * top. The capped height still respects the user's expand
   * intent — they just get whatever room is actually available. */
  const int collapsed_height = agent_bubble_collapsed_height_for_current_attachments(C);
  int target_height = collapsed_height;
  if (!g_bubble_expanded) {
    /* Reserve room above the bubble for the pill + a small gap so
     * neither overlaps the menu bar or notch. */
    const int reserve_top = AGENT_BUBBLE_PILL_HEIGHT +
                            AGENT_BUBBLE_PILL_GAP + 8;
    int max_height = Mixar_WindowGetMaxHeightToScreenTop(
        g_bubble_ghostwin, reserve_top);
    target_height = AGENT_BUBBLE_EXPANDED_HEIGHT;
    if (max_height > 0 && max_height < target_height) {
      target_height = max_height;
    }
    /* Don't shrink below the default — better to give the user
     * NO expansion than a confusingly-tiny one. */
    if (target_height < collapsed_height) {
      target_height = collapsed_height;
    }
  }
  bubble_force_size_and_refresh(
      C, g_bubble_ghostwin, AGENT_BUBBLE_DEFAULT_WIDTH, target_height);
  bubble_set_min_content_size(g_bubble_ghostwin, collapsed_height);
#ifdef __APPLE__
  Mixar_WindowOrderFront(g_bubble_ghostwin);
#endif
  g_bubble_expanded = !g_bubble_expanded;
  return OPERATOR_FINISHED;
#else
  return OPERATOR_CANCELLED;
#endif
}

void MIXAR_OT_bubble_toggle_expand(wmOperatorType *ot)
{
  /* See MIXAR_OT_bubble_minimise — single-word strings to keep
   * tooltips inside the bubble window's narrow header. */
  ot->name = "Expand";
  ot->idname = "MIXAR_OT_bubble_toggle_expand";
  ot->description = "Expand";
  ot->exec = mixar_bubble_toggle_expand_exec;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Set Background Colour Operator
 *
 * Python: `bpy.ops.mixar.bubble_set_bg_color(r=0.1, g=0.1, b=0.1, a=1.0)`
 * Passing a=0 disables the custom colour and falls back to the theme.
 * \{ */

static wmOperatorStatus mixar_bubble_set_bg_color_exec(bContext * /*C*/, wmOperator *op)
{
  float r = RNA_float_get(op->ptr, "r");
  float g = RNA_float_get(op->ptr, "g");
  float b = RNA_float_get(op->ptr, "b");
  float a = RNA_float_get(op->ptr, "a");

  if (a <= 0.0f) {
    /* Alpha 0 disables the custom bg — fall back to theme. */
    g_bubble_bg_custom = false;
  }
  else {
    g_bubble_bg_custom = true;
    g_bubble_bg_color[0] = r;
    g_bubble_bg_color[1] = g;
    g_bubble_bg_color[2] = b;
    g_bubble_bg_color[3] = a;
  }
  return OPERATOR_FINISHED;
}

void MIXAR_OT_bubble_set_bg_color(wmOperatorType *ot)
{
  ot->name = "Set Agent Bubble Background Colour";
  ot->idname = "MIXAR_OT_bubble_set_bg_color";
  ot->description = "Set the background colour (RGBA) of the Agent Bubble window";
  ot->exec = mixar_bubble_set_bg_color_exec;

  RNA_def_float(ot->srna, "r", 0.0f, 0.0f, 1.0f, "Red", "", 0.0f, 1.0f);
  RNA_def_float(ot->srna, "g", 0.0f, 0.0f, 1.0f, "Green", "", 0.0f, 1.0f);
  RNA_def_float(ot->srna, "b", 0.0f, 0.0f, 1.0f, "Blue", "", 0.0f, 1.0f);
  RNA_def_float(ot->srna, "a", 1.0f, 0.0f, 1.0f, "Alpha", "", 0.0f, 1.0f);
}

/** \} */

static void agent_bubble_operatortypes()
{
  WM_operatortype_append(MIXAR_OT_agent_bubble_show_window);
  WM_operatortype_append(MIXAR_OT_agent_bubble_purge_windows);
  WM_operatortype_append(MIXAR_OT_bubble_set_size);
  WM_operatortype_append(MIXAR_OT_bubble_sync_attachment_size);
  WM_operatortype_append(MIXAR_OT_bubble_window_begin_drag);
  WM_operatortype_append(MIXAR_OT_bubble_window_update_drag);
  WM_operatortype_append(MIXAR_OT_bubble_window_end_drag);
  WM_operatortype_append(MIXAR_OT_bubble_minimise);
  WM_operatortype_append(MIXAR_OT_bubble_restore);
  WM_operatortype_append(MIXAR_OT_bubble_toggle_expand);
  WM_operatortype_append(MIXAR_OT_bubble_set_bg_color);
}

static void agent_bubble_keymap(wmKeyConfig *keyconf)
{
  /* Ensure all three region keymap categories exist on the default
   * keyconfig so the Python addon-keyconfig registrations in
   * mixar.bootstrap.agent_bubble_module attach to keymaps Blender's
   * event dispatcher actually consults. Without the HEADER ensure,
   * the addon-side "Agent Bubble Header" keymap was effectively
   * orphaned — clicks in the header region weren't matching it. */
  wmKeyMap *km = WM_keymap_ensure(
      keyconf, "Agent Bubble", SPACE_AGENT_BUBBLE, RGN_TYPE_WINDOW);

  /* Ctrl+V / Cmd+V: paste image from clipboard — reuses the Mixie Chat
   * paste operator which writes to the shared pending-attachments collection. */
  KeyMapItem_Params paste_params{};
  paste_params.type = EVT_VKEY;
  paste_params.value = KM_PRESS;
#ifdef __APPLE__
  paste_params.modifier = KM_OSKEY;
#else
  paste_params.modifier = KM_CTRL;
#endif
  WM_keymap_add_item(km, "MIXIE_CHAT_OT_paste_image", &paste_params);

  /* Also register on the footer (TOOLS) region so paste works when the
   * text input has focus. */
  wmKeyMap *km_footer = WM_keymap_ensure(
      keyconf, "Agent Bubble", SPACE_AGENT_BUBBLE, RGN_TYPE_TOOLS);
  WM_keymap_add_item(km_footer, "MIXIE_CHAT_OT_paste_image", &paste_params);

  WM_keymap_ensure(
      keyconf, "Agent Bubble Header", SPACE_AGENT_BUBBLE, RGN_TYPE_HEADER);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Blend File I/O
 * \{ */

static void agent_bubble_space_blend_write(BlendWriter *writer, SpaceLink *sl)
{
  SpaceAgentBubble *sbubble = (SpaceAgentBubble *)sl;
  /* Don't save runtime pointer — regenerated on load. */
  void *runtime_backup = sbubble->runtime;
  sbubble->runtime = nullptr;
  BLO_write_struct(writer, SpaceAgentBubble, sl);
  sbubble->runtime = runtime_backup;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Space Type Registration
 * \{ */

void ED_spacetype_agent_bubble()
{
  std::unique_ptr<SpaceType> st = std::make_unique<SpaceType>();
  ARegionType *art;

  st->spaceid = SPACE_AGENT_BUBBLE;
  STRNCPY_UTF8(st->name, "Agent Bubble");
  st->iconid = ICON_OUTLINER_OB_LIGHT;  /* placeholder icon — replace in Phase 6 */

  st->create = agent_bubble_create;
  st->free = agent_bubble_free;
  st->init = agent_bubble_init;
  st->duplicate = agent_bubble_duplicate;
  st->operatortypes = agent_bubble_operatortypes;
  st->keymap = agent_bubble_keymap;
  st->blend_write = agent_bubble_space_blend_write;

  /* Main region — REUSES MIXIE CHAT'S CUSTOM-DRAWN MESSAGE LIST.
   *
   * Identical chat-history rendering to mixie chat: markdown, code
   * blocks, message selection, scroll-to-bottom indicator, hover
   * effects on action chips, the lot.
   *
   * Why this is safe (we previously had a crash from this exact
   * wiring): SpaceAgentBubble is now layout-identical to
   * SpaceMixieChat (see DNA_space_types.h), so the
   * `reinterpret_cast<SpaceMixieChat *>(area->spacedata.first)`
   * inside mixie chat's callbacks reads valid memory and the
   * per-space MixieChatRuntime is allocated fresh on first
   * `mixie_chat_ensure_runtime` call.
   *
   * The chat MESSAGES live on Scene (mixie_chat_messages collection
   * property), not in the space struct, so the bubble and the full
   * mixie chat editor see the same conversation.
   *
   * keymapflag = 0 mirrors mixie chat exactly. ED_KEYMAP_UI would
   * install a ui_region_handler + "User Interface" keymap that
   * consumes LEFTMOUSE before our text-selection / option-chip
   * keymap can see it. The custom region's init function attaches
   * the appropriate handlers itself. */
  art = MEM_callocN<ARegionType>("spacetype agent_bubble main region");
  art->regionid = RGN_TYPE_WINDOW;
  art->keymapflag = 0;
  art->init = mixie_chat_main_region_init;
  art->layout = mixie_chat_main_region_layout;
  art->draw = agent_bubble_main_region_draw;
  art->exit = mixie_chat_main_region_exit; /* Stop the animation frame pump */
  art->listener = mixie_chat_main_region_listener;
  art->cursor = mixie_chat_main_region_cursor;
  /* Per-mousemove cursor callback — hover highlights (history overlay rows,
   * option bubbles) redraw from it; see the same flag in space_mixie_chat.cc. */
  art->event_cursor = true;
  BLI_addhead(&st->regiontypes, art);

  /* Header region (status pill). */
  art = MEM_callocN<ARegionType>("spacetype agent_bubble header region");
  art->regionid = RGN_TYPE_HEADER;
  art->prefsizey = AGENT_BUBBLE_HEADER_HEIGHT;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_HEADER;
  art->init = agent_bubble_header_region_init;
  art->draw = agent_bubble_header_region_draw;
  BLI_addhead(&st->regiontypes, art);

  /* Footer region — REUSES MIXIE CHAT'S CUSTOM-DRAWN FOOTER.
   *
   * The Python panel-based footer (AGENT_BUBBLE_PT_footer) was
   * limited to a static prefsizey, so multi-line input grown via
   * Shift+Enter pushed the action row (Mode + paperclip + send) off
   * the bottom. Mixie chat's footer region has its own
   * region->sizey-recalculation logic in mixie_chat_footer_region_layout
   * that grows the region as input lines grow, keeping the action
   * row pinned to the bottom. Reusing the same callbacks gives the
   * agent bubble the identical behaviour AND look (custom GPU draw,
   * attachment thumbnails, send-button glow, plan-mode toggle, …).
   *
   * The Python AGENT_BUBBLE_PT_footer registration becomes inert —
   * mixie_chat_footer_region_init does NOT call ED_region_panels_init,
   * so the panel system isn't set up for this region; Python panels
   * registered for AGENT_BUBBLE TOOLS never get a draw call. */
  art = MEM_callocN<ARegionType>("spacetype agent_bubble footer region");
  art->regionid = RGN_TYPE_TOOLS;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_FOOTER;
  art->init = mixie_chat_footer_region_init;
  art->layout = agent_bubble_footer_region_layout;
  art->draw = agent_bubble_footer_region_draw;
  /* No prefsizey — mixie chat's layout callback computes the height
   * dynamically based on input line count + pending attachments, so
   * a static prefsizey would be overridden every layout pass. */
  BLI_addhead(&st->regiontypes, art);

  BKE_spacetype_register(std::move(st));
}

/** \} */
