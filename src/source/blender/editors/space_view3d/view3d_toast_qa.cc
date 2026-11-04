/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Read the Python overlay's paint/hit geometry only when QA asks for targets. */
#include <cstdint>
#include <sstream>

#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_main.hh"
#include "BLI_serialize.hh"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "MEM_guardedalloc.h"
#include "../interface/interface_qa_inspect.hh"
#ifdef WITH_PYTHON
#  include "BPY_extern_run.hh"
#endif

namespace blender {
namespace {
void toast_targets(const wmWindow *win, const ScrArea *, const ARegion *region,
                   std::vector<MixarQATarget> &targets)
{
#ifdef WITH_PYTHON
  if (region->regiontype != RGN_TYPE_WINDOW || !G_MAIN || G_MAIN->wm.is_empty()) {
    return;
  }
  bContext *C = CTX_create();
  CTX_data_main_set(C, G_MAIN);
  CTX_wm_manager_set(C, static_cast<wmWindowManager *>(G_MAIN->wm.first));
  CTX_wm_window_set(C, const_cast<wmWindow *>(win));
  const std::string expr =
      "__import__('mixar.modules.common.notifications.core.qa_targets', "
      "fromlist=['targets_json']).targets_json(" + std::to_string(uintptr_t(region)) + ")";
  char *result = nullptr;
  const bool ok = BPY_run_string_as_string(C, nullptr, expr.c_str(), nullptr, &result);
  CTX_free(C);
  if (!ok || !result) {
    return;
  }
  std::istringstream stream(result);
  MEM_delete(result);
  io::serialize::JsonFormatter json;
  const auto value = json.deserialize(stream);
  const auto *rows = value ? value->as_array_value() : nullptr;
  if (!rows) {
    return;
  }
  for (const auto &entry : rows->elements()) {
    const auto *array = entry->as_array_value();
    if (!array || array->elements().size() != 7) {
      continue;
    }
    const auto &fields = array->elements();
    if (!fields[0]->as_string_value() || !fields[1]->as_string_value() ||
        !fields[2]->as_string_value() || !fields[3]->as_int_value() ||
        !fields[4]->as_int_value() || !fields[5]->as_int_value() || !fields[6]->as_int_value())
    {
      continue;
    }
    MixarQATarget target;
    target.surface = fields[0]->as_string_value()->value();
    target.text = fields[1]->as_string_value()->value();
    target.value = fields[2]->as_string_value()->value();
    target.rect_win = {int(fields[3]->as_int_value()->value()),
                       int(fields[5]->as_int_value()->value()),
                       int(fields[4]->as_int_value()->value()),
                       int(fields[6]->as_int_value()->value())};
    BLI_rcti_translate(&target.rect_win, region->winrct.xmin, region->winrct.ymin);
    targets.push_back(std::move(target));
  }
#endif
}
}  // namespace

void view3d_toast_qa_register()
{
  static bool registered = false;
  if (!registered) {
    Mixar_qa_register_target_provider(SPACE_VIEW3D, toast_targets);
    registered = true;
  }
}
}  // namespace blender
