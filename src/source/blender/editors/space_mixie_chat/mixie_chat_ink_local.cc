/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Scribble on-device recognition — the operator pair Python drives to reach
 * the platform recogniser (GHOST_MixarVisionCocoa.mm on macOS):
 *
 *   * mixie_chat.ink_recognize_local(job, image_path) starts one batch. Its
 *     poll is the platform capability: false wherever there is no local
 *     recogniser, which is how core/scribble.py decides between the instant
 *     path and the backend without a platform table of its own.
 *   * mixie_chat.ink_local_poll pops ONE finished result into the
 *     Python-registered WindowManager properties (`mixie_chat_ink_local_*`)
 *     and returns FINISHED; CANCELLED when nothing has landed. Recognition
 *     runs off the main thread; this is the only place its results cross
 *     into Blender, from a Python timer on the main thread.
 *
 * Results travel through RNA properties rather than a callback because the
 * recogniser's completion runs on a system queue with no bContext to call an
 * operator from — the same reason the pane message line is a property.
 */

#include <climits>
#include <cstring>

#include "BKE_context.hh"

#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"

#ifdef __APPLE__
extern "C" bool Mixar_VisionAvailable(void);
extern "C" bool Mixar_VisionRecognizeFile(int job_id, const char *png_path);
extern "C" bool Mixar_VisionPopResult(
    int *r_job_id, char *r_text, int text_maxlen, float *r_confidence, int *r_ok);
#endif

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* Longest path / result the operators carry. */
static constexpr int INK_LOCAL_PATH_MAX = 1024;
static constexpr int INK_LOCAL_TEXT_MAX = 4096;

static bool ink_local_available()
{
#ifdef __APPLE__
  return Mixar_VisionAvailable();
#else
  return false;
#endif
}

/* -------------------------------------------------------------------- */
/** \name MIXIE_CHAT_OT_ink_recognize_local
 * \{ */

static bool ink_recognize_local_poll(bContext * /*C*/)
{
  return ink_local_available();
}

static wmOperatorStatus ink_recognize_local_exec(bContext * /*C*/, wmOperator *op)
{
  char path[INK_LOCAL_PATH_MAX];
  RNA_string_get(op->ptr, "image_path", path);
  const int job = RNA_int_get(op->ptr, "job");
  if (path[0] == '\0') {
    return OPERATOR_CANCELLED;
  }
#ifdef __APPLE__
  return Mixar_VisionRecognizeFile(job, path) ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
#else
  (void)job;
  return OPERATOR_CANCELLED;
#endif
}

void MIXIE_CHAT_OT_ink_recognize_local(wmOperatorType *ot)
{
  ot->name = "Recognize Handwriting Locally";
  ot->idname = "MIXIE_CHAT_OT_ink_recognize_local";
  ot->description = "Start on-device recognition of one rasterized ink batch";
  ot->exec = ink_recognize_local_exec;
  ot->poll = ink_recognize_local_poll;
  ot->flag = OPTYPE_INTERNAL;

  RNA_def_int(ot->srna, "job", 0, 0, INT_MAX, "Job", "Batch id echoed back with the result", 0, INT_MAX);
  RNA_def_string(ot->srna,
                 "image_path",
                 nullptr,
                 INK_LOCAL_PATH_MAX,
                 "Image Path",
                 "PNG of the ink batch (dark strokes on a light page)");
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name MIXIE_CHAT_OT_ink_local_poll
 * \{ */

static bool ink_local_poll_poll(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm || !ink_local_available()) {
    return false;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  return RNA_struct_find_property(&wm_ptr, "mixie_chat_ink_local_text") != nullptr;
}

static wmOperatorStatus ink_local_poll_exec(bContext *C, wmOperator * /*op*/)
{
#ifdef __APPLE__
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return OPERATOR_CANCELLED;
  }
  int job = 0;
  int ok = 0;
  float confidence = 0.0f;
  char text[INK_LOCAL_TEXT_MAX];
  text[0] = '\0';
  if (!Mixar_VisionPopResult(&job, text, INK_LOCAL_TEXT_MAX, &confidence, &ok)) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  if (PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_ink_local_job")) {
    RNA_property_int_set(&wm_ptr, prop, job);
  }
  if (PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_ink_local_text")) {
    RNA_property_string_set(&wm_ptr, prop, text);
  }
  if (PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_ink_local_confidence")) {
    RNA_property_float_set(&wm_ptr, prop, confidence);
  }
  if (PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_ink_local_ok")) {
    RNA_property_boolean_set(&wm_ptr, prop, ok != 0);
  }
  return OPERATOR_FINISHED;
#else
  (void)C;
  return OPERATOR_CANCELLED;
#endif
}

void MIXIE_CHAT_OT_ink_local_poll(wmOperatorType *ot)
{
  ot->name = "Poll Local Handwriting Result";
  ot->idname = "MIXIE_CHAT_OT_ink_local_poll";
  ot->description = "Move one finished on-device recognition result into the window-manager properties";
  ot->exec = ink_local_poll_exec;
  ot->poll = ink_local_poll_poll;
  ot->flag = OPTYPE_INTERNAL;
}

/** \} */

}  // namespace blender
