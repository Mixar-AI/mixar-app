/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "BLI_string.h"
#include "BLI_utildefines.h"
#include "DNA_windowmanager_types.h"
#include "MEM_guardedalloc.h"
#include "RNA_access.hh"
#include "agent_ui_queue_intern.hh"

namespace blender::agent_queue {

bool state_is(const char *state, const char *name)
{
  return STREQ(state, name);
}

/** C++ mirror of the UIList's `_status_word` — one vocabulary, two surfaces. */
void status_word(const char *state, const char *substate, char r_out[64])
{
  const char *word = "";
  if (state_is(state, "SUCCESS")) {
    word = "Done";
  }
  else if (state_is(state, "FAILED")) {
    word = "Failed";
  }
  else if (state_is(state, "CANCELLED")) {
    word = "Cancelled";
  }
  else if (state_is(state, "PAUSED_AUTH")) {
    word = "Waiting for sign-in";
  }
  else if (state_is(state, "RUNNING_SUBMIT") || state_is(state, "RUNNING_POLL") ||
           state_is(state, "RUNNING_DOWNLOAD"))
  {
    word = (substate && substate[0]) ? substate : "Processing";
  }
  else if (state_is(state, "PENDING")) {
    word = (substate && substate[0]) ? substate : "Queued";
  }
  else {
    word = (substate && substate[0]) ? substate : "";
  }
  BLI_strncpy(r_out, word, 64);
}

void read_item_string(PointerRNA *item, const char *name, char *r_buf, const int buf_len)
{
  r_buf[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(item, name);
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return;
  }
  /* Never the bare RNA_property_string_get — it is strcpy-shaped and a value
   * longer than the buffer overflows it. The alloc form clamps to the fixed
   * buffer and only heap-allocates past it. */
  int len = 0;
  char *value = RNA_property_string_get_alloc(item, prop, r_buf, buf_len, &len);
  if (value != r_buf) {
    BLI_strncpy(r_buf, value, size_t(buf_len));
    MEM_delete(value);
  }
  r_buf[buf_len - 1] = '\0';
}

/** Whole unix seconds. The epoch is an IntProperty because a float32 cannot
 * hold one: its ULP at 1.79e9 is 128 s, which had the elapsed clock reading up
 * to a minute wrong and ticking in ~2-minute jumps. */
int read_item_int(PointerRNA *item, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(item, name);
  if (!prop || RNA_property_type(prop) != PROP_INT) {
    return 0;
  }
  return RNA_property_int_get(item, prop);
}

float read_item_float(PointerRNA *item, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(item, name);
  if (!prop || RNA_property_type(prop) != PROP_FLOAT) {
    return 0.0f;
  }
  return RNA_property_float_get(item, prop);
}

/** m:ss, or h:mm:ss past the hour — mirrors labels.py format_elapsed. */
void format_elapsed(double seconds, char r_out[32])
{
  if (seconds < 0.0) {
    seconds = 0.0;
  }
  const int total = int(seconds);
  const int m = total / 60;
  const int sec = total % 60;
  /* Parameter arrays decay to pointers, so SNPRINTF's ARRAY_SIZE can't see
   * the bound — pass it explicitly. */
  if (m >= 60) {
    BLI_snprintf(r_out, 32, "%d:%02d:%02d", m / 60, m % 60, sec);
  }
  else {
    BLI_snprintf(r_out, 32, "%d:%02d", m, sec);
  }
}

/** Fill \a rows from wm.mixie_queue.items (already newest-first). */
int gather_rows(wmWindowManager *wm, QueueRow *rows, int *r_index_of_row, int &r_active_index)
{
  r_active_index = -1;
  if (!wm) {
    return 0;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *queue_prop = RNA_struct_find_property(&wm_ptr, "mixie_queue");
  if (!queue_prop || RNA_property_type(queue_prop) != PROP_POINTER) {
    return 0;
  }
  PointerRNA queue = RNA_property_pointer_get(&wm_ptr, queue_prop);
  r_active_index = read_item_int(&queue, "active_index");
  PropertyRNA *items = RNA_struct_find_property(&queue, "items");
  if (!items || RNA_property_type(items) != PROP_COLLECTION) {
    return 0;
  }

  int count = 0;
  int index = 0;
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&queue, items, &iter);
  for (; iter.valid && count < QUEUE_MAX_ROWS; RNA_property_collection_next(&iter), index++) {
    PointerRNA item = iter.ptr;
    QueueRow &row = rows[count];

    read_item_string(&item, "job_id", row.job_id, sizeof(row.job_id));
    read_item_string(&item, "feature_key", row.feature_key, sizeof(row.feature_key));

    auto read_title = [&](const char *name) -> std::string {
      PropertyRNA *prop = RNA_struct_find_property(&item, name);
      return prop && RNA_property_type(prop) == PROP_STRING ?
                 RNA_property_string_get(&item, prop) :
                 std::string();
    };
    row.title = read_title("display_label");
    if (row.title.empty()) {
      row.title = read_title("label");
    }
    if (row.title.empty()) {
      row.title = "(unnamed)";
    }
    /* Match the UIList's capitalized first letter. ASCII-only on purpose —
     * a multi-byte first char is left alone. */
    if (row.title[0] >= 'a' && row.title[0] <= 'z') {
      row.title[0] = char(row.title[0] - 'a' + 'A');
    }

    char state[32] = "";
    char substate[64] = "";
    read_item_string(&item, "state", state, sizeof(state));
    read_item_string(&item, "substate_text", substate, sizeof(substate));
    status_word(state, substate, row.status);
    read_item_string(&item, "type_label", row.type_label, sizeof(row.type_label));
    read_item_string(&item, "model_label", row.model_label, sizeof(row.model_label));
    row.created_epoch = double(read_item_int(&item, "created_epoch"));
    row.elapsed_done = read_item_float(&item, "elapsed_done");

    row.is_running = state_is(state, "RUNNING_SUBMIT") || state_is(state, "RUNNING_POLL") ||
                     state_is(state, "RUNNING_DOWNLOAD");
    row.is_pending = state_is(state, "PENDING") || state_is(state, "PAUSED_AUTH");
    row.is_done = state_is(state, "SUCCESS");
    row.is_failed = state_is(state, "FAILED") || state_is(state, "CANCELLED");

    r_index_of_row[count] = index;
    count++;
  }
  RNA_property_collection_end(&iter);
  return count;
}

}  // namespace blender::agent_queue
