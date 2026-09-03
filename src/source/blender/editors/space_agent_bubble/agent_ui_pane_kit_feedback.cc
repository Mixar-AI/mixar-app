/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Pane-kit LIVE FEEDBACK — the one answer to "did my click do anything?".
 *
 * The island is its own always-on-top window with no status bar, so the two
 * things the moodboard N-panel relied on are both invisible here:
 *
 *  1. The per-tab `scene.mixie_*_is_generating` flags. Those are set by the
 *     unified queue's `create_scene_flag_listener`, and only for the enqueue
 *     paths that pass a `scene_flag` — the Image Gen tab operator and the
 *     World Labs flow pass none at all, so the Media and Splat panes read a
 *     flag nothing on their path ever writes and their Generate button never
 *     changed. The QUEUE is the real source of truth, and every pane's
 *     Generate ends in `enqueue_generation`, so #pane_active_job_count reads
 *     the same `wm.mixie_queue` mirror the island's Queue tab lists.
 *
 *  2. `self.report(...)`. Operator reports go to the MAIN window's status bar
 *     and Info editor; nothing of either exists in this window. A user who
 *     hits Generate with no reference image selected saw literally nothing.
 *     #pane_report_line_draw paints a message line inside the pane, from the
 *     `mixar_pane_message*` WindowManager properties.
 *
 *     Those are a DEDICATED channel, written only by the panes' own Generate
 *     dispatcher (`moodboard/ui/operators/prompt_generate_ops.py`), and NOT
 *     Blender's global report list. The global list collects reports from the
 *     whole app — Mixar's own agent running sandboxed Blender scripts very
 *     much included — so sourcing the line from it painted unrelated bpy
 *     script output above the user's prompt. Unrelated app activity must
 *     never appear in a generation pane.
 *
 * Both are deliberately READ-ONLY here and both degrade to drawing nothing
 * when the properties they read are absent (an older build, or a Python side
 * that has not registered yet) — a pane must never fail to paint because a
 * feedback surface could not resolve.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "agent_ui_pane_kit.hh"
#include "agent_ui_theme.hh"

namespace {

/**
 * Clamped RNA string read — never the bare `RNA_property_string_get`, which is
 * strcpy-shaped and overflows a fixed buffer on a longer value. Same idiom as
 * the queue pane's `read_item_string`.
 */
void kit_read_string(PointerRNA *ptr, const char *name, char *r_buf, const int buf_len)
{
  r_buf[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return;
  }
  int len = 0;
  char *value = RNA_property_string_get_alloc(ptr, prop, r_buf, buf_len, &len);
  if (value != r_buf) {
    BLI_strncpy(r_buf, value, size_t(buf_len));
    MEM_freeN(value);
  }
  r_buf[buf_len - 1] = '\0';
}

/** \a name as an int, or \a fallback when the property is absent/mistyped. */
int kit_read_int(PointerRNA *ptr, const char *name, const int fallback)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_INT) {
    return fallback;
  }
  return RNA_property_int_get(ptr, prop);
}

/**
 * The queue's NON-TERMINAL states.
 *
 * One vocabulary, two surfaces: these are exactly the strings
 * `agent_ui_queue.cc`'s `state_is` block buckets as running or pending
 * (everything that is not SUCCESS / FAILED / CANCELLED). Do not invent a
 * state here — the mirror writes `JobState`'s own names.
 */
bool queue_state_is_active(const char *state)
{
  return STREQ(state, "PENDING") || STREQ(state, "PAUSED_AUTH") ||
         STREQ(state, "RUNNING_SUBMIT") || STREQ(state, "RUNNING_POLL") ||
         STREQ(state, "RUNNING_DOWNLOAD");
}

/**
 * Does this mirror row belong to \a service_key?
 *
 * A job carries three identities and which one holds the pane's key depends
 * on the feature: `service` is the submitted job_type (`image_gen`,
 * `world_labs`, `model_3d`), `feature_key` is the FeatureQueue's own key
 * (`imagegen`, `image_to_3d_pro`) and `origin_capability_key` is the catalog
 * capability a composite workflow was launched from. A pane knows the service
 * it submits, so any of the three matching is a match — narrowing to one field
 * would silently under-report on the others.
 */
bool queue_row_matches(PointerRNA *item, const char *service_key)
{
  char field[96];
  static const char *IDENT_FIELDS[3] = {"service", "feature_key", "origin_capability_key"};
  for (const char *name : IDENT_FIELDS) {
    kit_read_string(item, name, field, sizeof(field));
    if (field[0] && STREQ(field, service_key)) {
      return true;
    }
  }
  return false;
}

/**
 * Severity levels of the pane-message channel.
 *
 * The Python half's `LEVEL_*` constants
 * (`agent_bubble/ui/properties/pane_message_props.py`) — plain ordinals, NOT
 * `eReportType` bits: this channel is not the report system and must not
 * inherit its flag arithmetic. Pinned on both sides by
 * `tests/test_pane_feedback.py`.
 */
enum PaneMsgLevel {
  PANE_MSG_LEVEL_NONE = 0,
  PANE_MSG_LEVEL_INFO = 1,
  PANE_MSG_LEVEL_WARNING = 2,
  PANE_MSG_LEVEL_ERROR = 3,
};

/* Message freshness, shared by every pane (only one pane draws per frame, and
 * the channel holds one message — so this is one message with one lifetime,
 * not a per-pane one). `g_msg_seen_serial` starts NEGATIVE: the first paint
 * records whatever serial the channel is already at and shows nothing, or a
 * pane opened long after the write would greet the user with a stale line. */
int g_msg_seen_serial = -1;
double g_msg_stamp = 0.0;
bool g_msg_stamp_valid = false;

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Queue-backed busy state
 * \{ */

int pane_active_job_count(const bContext *C, const char *service_key)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return 0;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *queue_prop = RNA_struct_find_property(&wm_ptr, "mixie_queue");
  if (!queue_prop || RNA_property_type(queue_prop) != PROP_POINTER) {
    return 0;
  }
  PointerRNA queue = RNA_property_pointer_get(&wm_ptr, queue_prop);
  PropertyRNA *items = RNA_struct_find_property(&queue, "items");
  if (!items || RNA_property_type(items) != PROP_COLLECTION) {
    return 0;
  }

  /* An empty key means "any active job". A pane that cannot identify its own
   * service (no catalog yet, a placeholder enum) passes one deliberately: a
   * slightly over-broad "something is running" reads far better than a
   * Generate button that never acknowledges the click at all. */
  const bool match_any = (service_key == nullptr) || (service_key[0] == '\0');

  int count = 0;
  char state[32];
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&queue, items, &iter);
  for (; iter.valid; RNA_property_collection_next(&iter)) {
    PointerRNA item = iter.ptr;
    kit_read_string(&item, "state", state, sizeof(state));
    if (!queue_state_is_active(state)) {
      continue;
    }
    if (match_any || queue_row_matches(&item, service_key)) {
      count++;
    }
  }
  RNA_property_collection_end(&iter);
  return count;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Report line
 * \{ */

rctf pane_report_line_rect(const rctf &box, const float u)
{
  /* The kit already leaves PANE_BOX_GAP between the params strip and the
   * prompt box, so the line needs no room of its own and can collide with
   * nothing a pane has laid out. */
  rctf line;
  line.xmin = box.xmin + PANE_BOTTOM_IN_L * u;
  line.xmax = box.xmax - PANE_BOTTOM_IN_R * u;
  line.ymin = box.ymax;
  line.ymax = box.ymax + PANE_BOX_GAP * u;
  return line;
}

bool pane_report_line_draw(const bContext *C, const rctf &box, const float u)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return false;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);

  /* -1 is the "property absent" sentinel: an older build, or a Python side
   * that has not registered these yet. Draw nothing, change no state. */
  const int serial = kit_read_int(&wm_ptr, "mixar_pane_message_serial", -1);
  if (serial < 0) {
    return false;
  }

  const double now = BLI_time_now_seconds();
  if (g_msg_seen_serial < 0) {
    /* First paint: adopt the channel as-is and show NOTHING. */
    g_msg_seen_serial = serial;
    g_msg_stamp_valid = false;
    return false;
  }
  if (serial > g_msg_seen_serial) {
    /* The writer bumps the serial on EVERY write, a repeat of the same text
     * included — pressing Generate again and being refused again is news, and
     * restarts the freshness clock. */
    g_msg_seen_serial = serial;
    g_msg_stamp = now;
    g_msg_stamp_valid = true;
  }
  else if (serial < g_msg_seen_serial) {
    /* The channel was re-registered and reset — resync, resurrect nothing. */
    g_msg_seen_serial = serial;
  }

  if (!g_msg_stamp_valid || (now - g_msg_stamp) > PANE_MSG_TTL_S) {
    return false;
  }

  char message[256];
  kit_read_string(&wm_ptr, "mixar_pane_message", message, sizeof(message));
  if (message[0] == '\0') {
    return false;
  }

  /* Severity from the channel's own ordinal level (PaneMsgLevel above). */
  const int level = kit_read_int(&wm_ptr, "mixar_pane_message_level", PANE_MSG_LEVEL_NONE);
  if (level <= PANE_MSG_LEVEL_NONE) {
    return false;
  }
  const float col_error[4] = PANE_COL_MSG_ERROR;
  const float col_warn[4] = PANE_COL_MSG_WARN;
  const float col_info[4] = AGENT_COL_TEXT_DIM;
  const float *col = col_info;
  if (level >= PANE_MSG_LEVEL_ERROR) {
    col = col_error;
  }
  else if (level == PANE_MSG_LEVEL_WARNING) {
    col = col_warn;
  }

  const rctf line = pane_report_line_rect(box, u);
  if (!pane_prompt_fits(box, u) || BLI_rctf_size_x(&line) <= 0.0f) {
    /* A box squeezed to nothing has had its top clamped, so the gap this line
     * lives in is no longer empty — it is wherever the params strip ended up.
     * Such a pane offers no Generate either (the kit's paid-action rule), so
     * there is nothing to report on and painting over the chips is pure loss. */
    return false;
  }
  const float font = PANE_MSG_FONT * u;
  pane_fit_text(message, BLI_rctf_size_x(&line), font);
  pane_label_left(message, line.xmin, BLI_rctf_cent_y(&line), font, col);
  return true;
}

/** \} */

void pane_queue_label(char *out, const int out_maxncpy, const int active_jobs)
{
  if (active_jobs <= 0) {
    BLI_strncpy(out, "Generate", size_t(out_maxncpy));
    return;
  }
  /* The count is the feedback: it appears the moment the job is queued and
   * ticks down as jobs land, so the user can see their submit took. */
  BLI_snprintf(out, size_t(out_maxncpy), "Queued (%d)", active_jobs);
}
