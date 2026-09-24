/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once

#include "BLI_rect.h"
#include <string>
#include <vector>

namespace blender {
struct ARegion;
struct bContext;
struct wmWindow;
struct wmWindowManager;
struct wmOperatorType;
struct Scene;
struct AgentIslandLayout;
struct AgentIslandState;
namespace ui {
struct Block;
}

constexpr float AGENT_REFERENCE_COLUMN_W = 288.0f;
constexpr const char *AGENT_REFERENCE_SCROLL = "mixar_reference_scroll";
struct AgentReference {
  std::string path, name, source;
  bool sketch = false;
};
/** Read the active pane's inputs without copying them into the chat draft. */
std::vector<AgentReference> agent_bubble_reference_items(Scene *scene, wmWindowManager *wm);
struct AgentReferenceGeometry {
  rctf view;
  rctf scrollbar;
  float image_size, row_pitch, max_scroll, offset;
};
bool agent_bubble_references_visible(const bContext *C);
void agent_bubble_references_sync(const bContext *C);
void agent_bubble_references_region_init(wmWindowManager *wm, ARegion *region);
void agent_bubble_references_draw(const bContext *C,
                                  ARegion *region,
                                  const AgentIslandLayout &layout,
                                  const AgentIslandState &state);
void agent_bubble_send_button(const bContext *C,
                              ARegion *region,
                              ui::Block *block,
                              const AgentIslandLayout &layout,
                              const AgentIslandState &state);
AgentReferenceGeometry agent_bubble_reference_geometry(const wmWindow *win,
                                                       const ARegion *region,
                                                       int count,
                                                       float fraction);
int agent_bubble_reference_count(const bContext *C);
float agent_bubble_reference_fraction(wmWindowManager *wm);
void MIXAR_OT_reference_scroll(wmOperatorType *ot);
void MIXAR_OT_preview_sketch(wmOperatorType *ot);
void agent_bubble_references_qa_register();
}  // namespace blender
