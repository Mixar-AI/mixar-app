/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/* Minimal runtime around the actual wm_files.cc functions, injected by the Python test. */
#include <cassert>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

template<typename T> struct Set : std::unordered_set<T> {
  void add(T value)
  {
    this->insert(value);
  }
};
template<typename T> struct List {
  T *first = nullptr;
  std::vector<T *> values;
  struct Iterator {
    typename std::vector<T *>::const_iterator iter;
    T &operator*() const
    {
      return **iter;
    }
    Iterator &operator++()
    {
      ++iter;
      return *this;
    }
    bool operator!=(const Iterator &other) const
    {
      return iter != other.iter;
    }
  };
  Iterator begin() const
  {
    return {values.begin()};
  }
  Iterator end() const
  {
    return {values.end()};
  }
  void add(T &value)
  {
    values.push_back(&value);
    first = values.front();
  }
  void clear_no_delete()
  {
    values.clear();
    first = nullptr;
  }
};
constexpr int SPACE_AGENT_BUBBLE = 108;
struct ScrArea {
  int spacetype = 1;
};
struct bScreen {
  List<ScrArea> areabase;
};
struct WindowRuntime {
  int handlers = 0, modalhandlers = 0;
};
struct wmWindow {
  int winid = 0;
  bScreen *screen = nullptr;
  WindowRuntime *runtime = nullptr;
  bool screens_retired = false;
  int native_window = 0;
};
struct ManagerRuntime {
  List<int> keyconfigs;
  void *addonconf = nullptr, *defaultconf = nullptr, *userconf = nullptr;
  void *message_bus = nullptr;
  wmWindow *winactive = nullptr;
};
enum class eWM_InitFlag {};
struct wmWindowManager {
  int id = 0, op_undo_depth = 0;
  eWM_InitFlag init_flag{};
  ManagerRuntime *runtime = nullptr;
  List<wmWindow> windows;
};
struct Main {
  List<wmWindowManager> wm;
};
struct bContext {
  wmWindow *window = nullptr;
};
struct BlendFileReadWMSetupData {
  wmWindowManager *old_wm;
  bool is_read_homefile, is_factory_startup;
};
#define BLI_assert assert
template<typename T> int BLI_listbase_count_at_most(const List<T> *list, int)
{
  return int(list->values.size());
}
template<typename T> T *MEM_new(const char *)
{
  return new T();
}
template<typename T> void MEM_delete(T *value)
{
  delete value;
}
bScreen *WM_window_get_active_screen(const wmWindow *window)
{
  if (window->screens_retired) {
    throw std::runtime_error("use-after-free: outgoing screen accessed after Main replacement");
  }
  return window->screen;
}
wmWindow *CTX_wm_window(bContext *context)
{
  return context->window;
}
void CTX_wm_window_set(bContext *context, wmWindow *window)
{
  context->window = window;
}
void CTX_wm_region_popup_set(bContext *, void *) {}
void WM_jobs_kill_all(wmWindowManager *) {}
void WM_event_remove_handlers(bContext *, int *) {}
void ED_screen_exit(bContext *, wmWindow *, bScreen *) {}
void WM_msgbus_destroy(void *) {}
void ED_editors_exit(Main *, bool) {}
namespace ed::asset::list {
void storage_exit() {}
}  // namespace ed::asset::list
void AS_asset_libraries_exit() {}
void wm_window_clear_drawable(wmWindowManager *) {}
void BKE_libblock_free_data(int *, bool) {}
void BKE_libblock_free_data_py(int *) {}
static bool closed_old_manager = false;
void wm_close_and_free(bContext *, wmWindowManager *)
{
  closed_old_manager = true;
}
void wm_file_read_setup_wm_substitute_old_window(wmWindowManager *,
                                                 wmWindowManager *,
                                                 wmWindow *old_window,
                                                 wmWindow *new_window)
{
  assert(old_window && new_window);
  new_window->native_window = old_window->native_window;
  old_window->native_window = 0;
}

// PRODUCTION_FUNCTIONS

static void run(const std::string &scenario)
{
  ScrArea regular_area, bubble_area{SPACE_AGENT_BUBBLE};
  bScreen regular_screen, bubble_screen;
  regular_screen.areabase.add(regular_area);
  bubble_screen.areabase.add(bubble_area);
  WindowRuntime old_regular_runtime, old_bubble_runtime, new_regular_runtime, new_bubble_runtime;
  wmWindow old_regular{7, &regular_screen, &old_regular_runtime, false, 700};
  wmWindow old_bubble{8, &bubble_screen, &old_bubble_runtime, false, 800};
  wmWindow new_regular{7, &regular_screen, &new_regular_runtime};
  wmWindow new_bubble{8, &bubble_screen, &new_bubble_runtime};
  ManagerRuntime old_runtime, new_runtime;
  auto *old_wm = new wmWindowManager;
  old_wm->runtime = &old_runtime;
  wmWindowManager new_wm;
  new_wm.runtime = &new_runtime;
  Main old_main;
  old_main.wm.add(*old_wm);
  bContext context{&old_regular};

  if (scenario == "empty") {
    Main empty;
    auto *setup = wm_file_read_setup_wm_init(&context, &empty, true);
    assert(setup->old_wm == nullptr && setup->is_read_homefile);
    assert(!setup->is_factory_startup && setup->old_agent_bubble_windows.empty());
    MEM_delete(setup);
    delete old_wm;
    return;
  }

  // Bubble comes first so the fallback must deliberately skip it.
  if (scenario != "ordinary") {
    old_wm->windows.add(old_bubble);
    new_wm.windows.add(new_bubble);
  }
  old_wm->windows.add(old_regular);
  new_wm.windows.add(new_regular);
  if (scenario == "fallback") {
    // The only winid match is the outgoing bubble: it must never donate its OS window.
    new_regular.winid = old_bubble.winid;
    new_bubble.winid = old_regular.winid;
  }

  auto *setup = wm_file_read_setup_wm_init(&context, &old_main, false);
  assert(setup->old_wm == nullptr && !setup->is_factory_startup);
  assert(setup->old_agent_bubble_windows.contains(&old_bubble) == (scenario != "ordinary"));
  assert(!setup->old_agent_bubble_windows.contains(&old_regular));
  assert(context.window == &old_regular);

  // Main replacement preserves window allocations, but invalidates all their UI pointers.
  // The window-manager ID can be swapped; matching must not key its snapshot by WM address.
  auto *swapped_old_wm = new wmWindowManager(*old_wm);
  delete old_wm;
  setup->old_wm = swapped_old_wm;
  for (wmWindow &window : swapped_old_wm->windows) {
    window.screens_retired = true;
    window.screen = reinterpret_cast<bScreen *>(1);
  }

  wm_file_read_setup_wm_use_new(&context, nullptr, setup, &new_wm);
  assert(new_regular.native_window == 700);
  assert(new_bubble.native_window == 0);
  assert(old_bubble.native_window == 800);
  assert(old_regular.native_window == 0);
  assert(setup->old_wm == nullptr && closed_old_manager);
  MEM_delete(setup);

  // A later read with the same window addresses must not inherit bubble classification.
  old_regular.screens_retired = false;
  old_regular.screen = &regular_screen;
  old_bubble.screens_retired = false;
  old_bubble.screen = &regular_screen;
  wmWindowManager next_wm;
  next_wm.runtime = &old_runtime;
  next_wm.windows.add(old_bubble);
  next_wm.windows.add(old_regular);
  Main next_main;
  next_main.wm.add(next_wm);
  setup = wm_file_read_setup_wm_init(&context, &next_main, false);
  assert(setup->old_agent_bubble_windows.empty());
  MEM_delete(setup);
}

int main(int argc, char **argv)
{
  try {
    assert(argc == 2);
    run(argv[1]);
    std::cout << "PASS " << argv[1] << '\n';
    return EXIT_SUCCESS;
  }
  catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return EXIT_FAILURE;
  }
}
