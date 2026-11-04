/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <string>
#include "BLI_rect.h"
#include "BLI_vector.hh"
namespace blender {
struct bContext;
struct Main;
struct Scene;
struct ARegion;
struct ScrArea;
struct wmTimer;
struct GPUOffScreen;
struct GPUViewport;
struct Depsgraph;
struct WorkspaceTab {
  std::string task_id, name;
  bool available = false;
  int ordinal = 0;
  rcti rect = {};
};
struct WorkspaceViewer {
  ARegion *region = nullptr;
  ScrArea *area = nullptr;
  void *draw_handle = nullptr;
  wmTimer *timer = nullptr;
  std::string task_id, main_session, run_id;
  Vector<WorkspaceTab> tabs;
  rcti bar = {}, image = {}, close = {}, previous = {}, next = {};
  float scroll = 0, scroll_max = 0;
  bool reveal_selection = true;
  GPUOffScreen *offscreen = nullptr;
  GPUViewport *viewport = nullptr;
  bool has_render = false, render_failed = false;
  uint64_t scene_uid = 0, update_count = 0, frame_count = 0;
  double last_render_time = 0;
  int draw_type = -1;
};
Scene *view3d_workspace_scene(Main *bmain, Scene *main, const std::string &task_id);
std::string view3d_workspace_rna_string(Scene *scene, const char *key);
void view3d_workspace_viewer_register();
void view3d_workspace_viewer_draw(const bContext *C, ARegion *region, void *data);
void view3d_workspace_viewer_render(const bContext *C, WorkspaceViewer &viewer, Scene *scene);
void view3d_workspace_viewer_gpu_free(WorkspaceViewer &viewer);
void view3d_workspace_viewer_region_free(ARegion *region);
void view3d_workspace_viewer_qa_register();
WorkspaceViewer *view3d_workspace_viewer_active();
}  // namespace blender
