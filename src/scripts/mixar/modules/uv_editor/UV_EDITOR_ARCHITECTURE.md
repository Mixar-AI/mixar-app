<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Mixar UV Editor & UV Properties - Technical Architecture

This document provides comprehensive technical documentation for the Mixar UV Editor and UV Properties implementation. It is designed for developers extending the UV Editor and as context for LLMs adding new features.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [File Structure](#2-file-structure)
3. [Panel System](#3-panel-system)
4. [C Implementation Patterns](#4-c-implementation-patterns)
5. [Python Operator Wrappers](#5-python-operator-wrappers)
6. [Adding New Features](#6-adding-new-features)
7. [API Reference](#7-api-reference)

---

## 1. Architecture Overview

### Dual-Space Architecture

The Mixar UV Editor uses a **dual-space architecture**:

1. **IMAGE_EDITOR** (mode: `MIXAR_UV`) - The main UV editing viewport
2. **MIXAR_UV_PROPERTIES** - A separate properties panel space

```
┌─────────────────────────────────────┬──────────────────────┐
│                                     │                      │
│         IMAGE_EDITOR                │  MIXAR_UV_PROPERTIES │
│         (MIXAR_UV mode)             │                      │
│                                     │  ┌────────────────┐  │
│    UV Viewport & Editing            │  │ Transform (C)  │◄─── Active when Transform tool selected
│                                     │  │ Pack Islands   │◄─── Active when Pack Islands header clicked
│    ┌─────────────────┐              │  │ UV Set         │◄─── Active when UV Set header clicked
│    │ Tool Panel      │              │  │ Texel Density  │◄─── Active when Texel Density header clicked
│    ├─────────────────┤              │  │ Unwrap         │◄─── Active when Unwrap header clicked
│    │ ▶ Transform     │◄─ Activates │  │ Tools (Py)     │◄─── Active when UV Sculpt tool selected
│    │   UV Sculpt     │   C Panel   │  │ Functions (Py) │◄─── Active when Functions tool selected
│    │   Functions     │              │  └────────────────┘  │
│    └─────────────────┘              │                      │
└─────────────────────────────────────┴──────────────────────┘
```

### Panel Activation Methods

**Two activation patterns:**

1. **Header-Based** (Most panels)
   - User clicks header buttons (Pack Islands, UV Set, Unwrap, etc.)
   - Controlled by `mixar_uv_ui.active_panel` enum
   - Python panels

2. **Tool-Based** (Transform, Tools, Functions)
   - Automatically appear when specific tool is selected
   - Controlled by active tool in IMAGE_EDITOR
   - Can be Python or C panels

### Key Design Principle: Context Switching

Since UV operations require IMAGE_EDITOR context but panels draw in MIXAR_UV_PROPERTIES space, all operations must **switch context** before execution:

```
MIXAR_UV_PROPERTIES → Save Context → Switch to IMAGE_EDITOR → Execute → Restore Context
```

---

## 2. File Structure

### Python Files (Modular Architecture)

```
src/scripts/mixar/modules/uv_editor/
├── common/
│   └── uv_utils.py              # Common utilities, decorators, and poll functions
└── ui/
    ├── properties.py            # UI state management (MixarUVUIState)
    ├── base/
    │   ├── __init__.py
    │   └── operators.py         # Utility operators (open/close UV Properties)
    ├── selection/
    │   ├── __init__.py
    │   ├── operators.py         # Selection operators
    │   └── panels.py            # Selection panel
    ├── tools/
    │   ├── __init__.py
    │   ├── operators.py         # UV Sculpt tool operators
    │   └── panels.py            # UV Sculpt tools panel
    ├── functions/
    │   ├── __init__.py
    │   ├── operators.py         # Seam, Pin, Merge, Split, Hide operators
    │   └── panels.py            # Functions panel
    ├── projection/
    │   ├── __init__.py
    │   ├── operators.py         # Projection operators (Cube, Cylinder, Camera, etc.)
    │   └── panels.py            # Projection panel
    ├── unwrap/
    │   ├── __init__.py
    │   ├── operators.py         # Smart Project operator
    │   └── panels.py            # Unwrap panel
    ├── pack_islands/
    │   ├── __init__.py
    │   ├── operators.py         # Pack Islands, Average Scale, Minimize Stretch
    │   └── panels.py            # Pack Islands panel
    ├── export/
    │   ├── __init__.py
    │   ├── operators.py         # UV Layout export operator
    │   └── panels.py            # Export panel
    ├── image/
    │   ├── __init__.py
    │   ├── operators.py         # Image operations (Save, Load, Transform, Pack)
    │   └── panels.py            # Image panel
    ├── transform/
    │   ├── __init__.py
    │   ├── operators.py         # Snap, Mirror, Align operators
    │   └── panels.py            # Snapping panel
    ├── uv_set/
    │   ├── __init__.py
    │   ├── operators.py         # UDIM Tile operators
    │   └── panels.py            # UV Set panel
    └── texel_density/
        ├── __init__.py
        └── panels.py            # Texel Density panel wrapper
```

### C/C++ Files

```
src/source/blender/editors/space_mixar_uv_properties/
├── space_mixar_uv_properties.cc   # Main C implementation
└── CMakeLists.txt                 # Build configuration
```

### Integration Files

```
src/scripts/startup/bl_ui/space_image.py   # Header panel selector (lines 750-762)
```

### File Responsibilities

| File/Module                    | Purpose                                                                                 |
| ------------------------------ | --------------------------------------------------------------------------------------- |
| `common/uv_utils.py`           | Common utilities: decorators (`@with_uv_context`), poll functions, context helpers     |
| `properties.py`                | Defines `MixarUVUIState` PropertyGroup with `active_panel` enum and expansion states    |
| `base/operators.py`            | Utility operators for opening/closing UV Properties panel                              |
| `selection/operators.py`       | Selection tool operators (box, circle, lasso, more, less, similar, linked)             |
| `tools/operators.py`           | UV Sculpt tool activation operators (Grab, Relax, Pinch, Rip Region)                   |
| `functions/operators.py`       | UV editing operators (seam, pin, merge, split, hide, copy/paste)                       |
| `projection/operators.py`      | UV projection operators (Cube, Cylinder, Sphere, Camera, Normal, Planar)               |
| `unwrap/operators.py`          | Smart UV Project operator                                                              |
| `pack_islands/operators.py`    | Pack Islands, Average Scale, Minimize Stretch, Custom Region operators                 |
| `export/operators.py`          | UV Layout export operator                                                              |
| `image/operators.py`           | Image operations (save, reload, transform, pack/unpack, visualize)                     |
| `transform/operators.py`       | Transform operators (snap, mirror, align, move/rotate/scale)                           |
| `uv_set/operators.py`          | UDIM Tile operators (add, remove, fill)                                                |
| `{module}/panels.py`           | Panel definitions for each module                                                      |
| `space_mixar_uv_properties.cc` | C panels: Transform (Move/Resize/Cursor/Arrange), Redo panel, Unwrap                   |
| `space_image.py`               | Panel selector buttons in IMAGE_EDITOR header                                           |

---

## 3. Panel System

### Panel Selector (Header Buttons)

Located in `space_image.py` (lines 750-762), the panel selector appears when `sima.mode == 'MIXAR_UV'`:

```python
if sima.mode == 'MIXAR_UV':
    wm = context.window_manager
    if hasattr(wm, 'mixar_uv_ui'):
        row = layout.row(align=True)
        row.scale_y = 1.2
        row.prop_enum(wm.mixar_uv_ui, "active_panel", 'TRANSFORM', text="Transform", icon='ORIENTATION_GLOBAL')
        row.prop_enum(wm.mixar_uv_ui, "active_panel", 'PACK_ISLANDS', text="Pack", icon='PACKAGE')
        # ... more buttons
```

### Active Panel Enum

Defined in `properties.py`:

```python
active_panel: EnumProperty(
    items=[
        ('TRANSFORM', 'Transform', 'Transform panel', 'ORIENTATION_GLOBAL', 0),
        ('PACK_ISLANDS', 'Pack Islands', 'Pack Islands panel', 'PACKAGE', 1),
        ('UV_SET', 'UV Set', 'UV Set panel', 'UV', 2),
        ('TEXEL_DENSITY', 'Texel Density', 'Texel Density panel', 'TEXTURE', 3),
        ('UNWRAP', 'Unwrap', 'Unwrap panel', 'UV_SYNC_SELECT', 4),
        ('SNAPPING', 'Snapping', 'Snapping panel', 'SNAP_ON', 5),
    ],
    default='TRANSFORM',
    update=_active_panel_update  # Auto-opens UV Properties panel
)
```

### Panel Visibility Patterns

Panels use two different visibility patterns:

#### 1. Header-Based Panels (Python)

Most Python panels check the `active_panel` enum from the header selector:

```python
class MIXAR_UV_PT_pack_islands(Panel):
    bl_space_type = 'MIXAR_UV_PROPERTIES'
    bl_region_type = 'WINDOW'

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        if not hasattr(wm, 'mixar_uv_ui'):
            return False
        return wm.mixar_uv_ui.active_panel == 'PACK_ISLANDS'
```

#### 2. Tool-Based Panels (C and Python)

Some panels show when a specific tool is active in the IMAGE_EDITOR:

**Python Example:**
```python
class MIXAR_UV_PT_tools(Panel):
    @classmethod
    def poll(cls, context):
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper

        obj = context.active_object
        if not (obj and obj.type == 'MESH' and obj.mode == 'EDIT'):
            return False

        # Check if UV sculpt tool is active in IMAGE_EDITOR
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                sima = area.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    with context.temp_override(area=area):
                        tool = ToolSelectPanelHelper.tool_active_from_context(context)
                        if tool and tool.idname in ('sculpt.uv_sculpt_grab', 'sculpt.uv_sculpt_relax', 'sculpt.uv_sculpt_pinch'):
                            return True
        return False
```

**C Example (Transform Panel):**
```cpp
static bool mixar_uv_transform_panel_poll(const bContext *C, PanelType * /*pt*/)
{
  // Only show in Edit mode with mesh
  Object *obedit = CTX_data_edit_object(C);
  if (!ED_uvedit_test(obedit)) {
    return false;
  }

  // Check if transform tool is active in IMAGE_EDITOR
  bScreen *screen = CTX_wm_screen(C);
  LISTBASE_FOREACH (ScrArea *, area, &screen->areabase) {
    if (area->spacetype == SPACE_IMAGE) {
      SpaceImage *sima = static_cast<SpaceImage *>(area->spacedata.first);
      if (sima && sima->mode == SI_MODE_MIXAR_UV) {
        bToolRef *tref = area->runtime.tool;
        if (tref && STREQ(tref->idname, "builtin.transform")) {
          return true;
        }
      }
    }
  }
  return false;
}
```

**Key Differences:**
- **Header-based**: Visibility controlled by user clicking header buttons (Transform, Pack Islands, etc.)
- **Tool-based**: Visibility controlled by active tool in IMAGE_EDITOR toolbar (Transform tool, UV Sculpt tools, etc.)

### Python Panels Overview

| Panel Class                     | Active When     | Content                                                                    | Status |
| ------------------------------- | --------------- | -------------------------------------------------------------------------- | ------ |
| `MIXAR_UV_PT_selection`         | Tool: Selection | Selection tools and operations                                             | Active |
| `MIXAR_UV_PT_transform_options` | ~~`TRANSFORM`~~ | ~~Mirror, Proportional Editing, Round to Pixels, Align, Align Rotation~~  | **DEPRECATED - Replaced by C panel** |
| `MIXAR_UV_PT_pack_islands`      | `PACK_ISLANDS`  | Layout panel: Pack Islands props sub-section + Custom Region sub-section (when Pack To = Custom Region; appears between props and the Pack Islands run button) + full-width Pack Islands button + Average Islands Scale sub-section (with Non-Uniform / Shear) + Minimize Stretch sub-section | Active |
| `MIXAR_UV_PT_uv_set`            | `UV_SET`        | UV Maps, Active Image, UDIM Tiles, Grid, Stretch, Display                  | Active |
| `MIXAR_UV_PT_texel_density`     | `TEXEL_DENSITY` | Texel density calculation and application                                  | Active |
| `MIXAR_UV_PT_unwrap`            | `UNWRAP`        | Combined panel with two sub-sections: **Unwrap** (method dropdown + properties + Unwrap button) and **Project** (type dropdown + properties + Project button) | Active |
| `MIXAR_UV_PT_snapping`          | `SNAPPING`      | Snap settings and operations                                               | Active |
| `MIXAR_UV_PT_unwrap` (Project section) | `UNWRAP` | Project sub-section inside the Unwrap panel: Type dropdown (Cube, Cylinder, Sphere, Camera, Normal, Planar) + type-specific properties + Project button | Active |
| `MIXAR_UV_PT_tools`             | Tool: UV Sculpt | UV tool activation buttons and properties (Grab, Relax, Pinch, Rip Region) | Active |
| `MIXAR_UV_PT_functions`         | Tool: Functions | UV functions (Seam, Pin, Merge, Split, Hide)                               | Active |
| `MIXAR_UV_PT_image`             | `IMAGE`         | Image operations (New, Open, Save, Transform, Pack/Unpack)                 | Active |
| `MIXAR_UV_PT_export`            | `EXPORT`        | UV layout export settings and export button                                | Active |

> **Note:** `MIXAR_UV_PT_transform_options` is commented out in the registration (panels.py:1864) and replaced by the C-based Transform panel.

### C Panels Overview

| Panel ID                | Active When        | Content                                                                                          | Implementation |
| ----------------------- | ------------------ | ------------------------------------------------------------------------------------------------ | -------------- |
| `MIXAR_UV_PT_transform` | Tool: Transform    | Move (X/Y), Pivot, Rotation, Resize, 2D Cursor, Arrange Islands, Snapping, Mirror, Proportional Editing, Round to Pixels, Align, Align Rotation | C (space_mixar_uv_properties.cc) |
| `MIXAR_UV_PT_redo`      | Tool: Transform    | Last operation properties (like Blender's Adjust Last Operation)                                 | C (space_mixar_uv_properties.cc) |

### Collapsible Sections

For panels with multiple sections, use `draw_collapsible_header()`:

```python
def draw_collapsible_header(layout, ui_state, prop_name, label, icon='NONE'):
    is_expanded = getattr(ui_state, prop_name)
    header_row = layout.row(align=True)
    collapse_icon = 'DOWNARROW_HLT' if is_expanded else 'RIGHTARROW'
    header_row.prop(ui_state, prop_name, text="", icon=collapse_icon, emboss=False)
    header_row.label(text=label, icon=icon)
    return is_expanded

# Usage:
box = layout.box()
if draw_collapsible_header(box, uv_ui, "expand_uv_maps", "UV Maps", icon='UV'):
    # Draw expanded content
```

---

## 4. C Implementation Patterns

### Context Switching Structure

```cpp
struct ImageEditorContext {
    ScrArea *area;
    ARegion *region;
};

static ImageEditorContext find_image_editor_context(const bContext *C) {
    ImageEditorContext result = {nullptr, nullptr};
    bScreen *screen = CTX_wm_screen(C);

    LISTBASE_FOREACH (ScrArea *, area, &screen->areabase) {
        if (area->spacetype == SPACE_IMAGE) {
            SpaceImage *sima = static_cast<SpaceImage *>(area->spacedata.first);
            if (sima && sima->mode == SI_MODE_MIXAR_UV) {
                result.area = area;
                result.region = BKE_area_find_region_type(area, RGN_TYPE_WINDOW);
                return result;
            }
        }
    }
    return result;
}
```

### Static Variables for Real-Time Editing

```cpp
// Transform state - persists across panel redraws
static float mixar_uv_vertex_old_center[2];        // Translation
static float mixar_uv_vertex_old_angle = 0.0f;     // Rotation angle
static float mixar_uv_vertex_applied_angle = 0.0f; // Cumulative rotation for delta
static float mixar_uv_size_target[2];              // Target dimensions for resize
static int mixar_uv_pivot_point;                   // Pivot mode (V3D_AROUND_*)
static float mixar_uv_cursor_edit[2];              // 2D cursor position
```

### Callback Event Pattern

```cpp
#define B_MIXAR_UVEDIT_VERTEX 4
#define B_MIXAR_UVEDIT_ROTATE 5
#define B_MIXAR_UVEDIT_SCALE 6
#define B_MIXAR_UVEDIT_PIVOT 7
#define B_MIXAR_UVEDIT_CURSOR 8

static void do_mixar_uvedit_transform(bContext *C, void * /*arg*/, int event) {
    // Guard clause - only handle known events
    if (event != B_MIXAR_UVEDIT_VERTEX && event != B_MIXAR_UVEDIT_ROTATE &&
        event != B_MIXAR_UVEDIT_SCALE && event != B_MIXAR_UVEDIT_CURSOR) {
        return;
    }

    // 1. Find and switch to IMAGE_EDITOR context
    ImageEditorContext img_ctx = find_image_editor_context(C);
    ScrArea *area_prev = CTX_wm_area(C);
    ARegion *region_prev = CTX_wm_region(C);
    CTX_wm_area_set(C, img_ctx.area);
    CTX_wm_region_set(C, img_ctx.region);

    // 2. Get scene and objects
    SpaceImage *sima = CTX_wm_space_image(C);
    Scene *scene = CTX_data_scene(C);
    Vector<Object *> objects = BKE_view_layer_array_from_objects_in_edit_mode_unique_data_with_uvs(...);

    // 3. Perform operation based on event type
    if (event == B_MIXAR_UVEDIT_VERTEX) {
        // Calculate delta and translate
        mixar_uvedit_translate(scene, objects, delta);
    }
    else if (event == B_MIXAR_UVEDIT_ROTATE) {
        // Calculate pivot center and rotate
        mixar_uvedit_rotate(scene, objects, pivot_center, angle_rad);
    }
    // ... more events

    // 4. Notify and update
    WM_event_add_notifier(C, NC_IMAGE, sima->image);
    for (Object *obedit : objects) {
        DEG_id_tag_update((ID *)obedit->data, ID_RECALC_GEOMETRY);
    }

    // 5. Restore original context
    CTX_wm_area_set(C, area_prev);
    CTX_wm_region_set(C, region_prev);
}
```

### Panel Draw with Sub-Panels

```cpp
static void mixar_uv_transform_panel_draw(const bContext *C, Panel *panel) {
    // Switch context first
    ImageEditorContext img_ctx = find_image_editor_context(C);
    ScrArea *area_prev = CTX_wm_area(C);
    ARegion *region_prev = CTX_wm_region(C);
    CTX_wm_area_set((bContext *)C, img_ctx.area);
    CTX_wm_region_set((bContext *)C, img_ctx.region);

    // Create sub-panel
    PanelLayout move_layout = panel->layout->panel(C, "MIXAR_UV_move_panel", false);
    move_layout.header->label(IFACE_("Move"), ICON_NONE);

    if (move_layout.body) {
        uiBlock *block = move_layout.body->absolute_block();
        UI_block_func_handle_set(block, do_mixar_uvedit_transform, nullptr);

        // Create buttons with event IDs
        uiDefButF(block, ButType::Num, B_MIXAR_UVEDIT_VERTEX, IFACE_("X:"),
                  0, y -= UI_UNIT_Y, 200, UI_UNIT_Y,
                  &mixar_uv_vertex_old_center[0], min, max, "");
    }

    // Restore context
    CTX_wm_area_set((bContext *)C, area_prev);
    CTX_wm_region_set((bContext *)C, region_prev);
}
```

### Using Layout API for Operator Properties

```cpp
if (arrange_layout.body) {
    wmOperatorType *ot = WM_operatortype_find("UV_OT_arrange_islands", false);
    if (ot) {
        PointerRNA op_ptr;
        WM_operator_properties_create_ptr(&op_ptr, ot);
        WM_operator_properties_sanitize(&op_ptr, false);

        uiLayout *col = &arrange_layout.body->column(false);

        // Draw operator properties using layout API
        col->prop(&op_ptr, "initial_position", UI_ITEM_NONE, std::nullopt, ICON_NONE);
        col->prop(&op_ptr, "axis", UI_ITEM_NONE, std::nullopt, ICON_NONE);

        // Add operator button
        uiLayout *row = &col->row(false);
        row->op("UV_OT_arrange_islands", IFACE_("Arrange Islands"), ICON_NONE);
    }
}
```

---

## 5. Python Operator Wrappers

### Why Wrappers Are Needed

UV operators require IMAGE_EDITOR context, but when called from MIXAR_UV_PROPERTIES space, they fail. Wrappers solve this with `context.temp_override()`.

### Common Utilities Module

To reduce code duplication, all operator modules use the `common/uv_utils.py` module which provides:

#### Context Getters
- `get_mixar_uv_image_editor(context)` - Find IMAGE_EDITOR in MIXAR_UV mode
- `get_window_region(area)` - Get WINDOW region from area

#### Poll Functions
- `poll_mixar_uv_mode(context)` - Basic UV mode check
- `poll_mixar_uv_edit_mode(context)` - UV mode + edit mode mesh
- `poll_mixar_uv_with_image(context)` - UV mode with image
- `poll_mixar_uv_with_packed_image(context)` - UV mode with packed image
- `poll_mixar_uv_with_unpacked_image(context)` - UV mode with unpacked image

#### Decorators
- `@with_uv_context` - Auto context override with area
- `@with_uv_context_and_region` - Auto context override with area + region

#### Helpers
- `get_operator_properties(context, operator_idname)` - Get last used operator properties

### Modern Wrapper Pattern (Using Common Utilities)

**Simple operator with decorator:**

```python
from mixar.modules.uv_editor.common.uv_utils import (
    poll_mixar_uv_mode,
    with_uv_context,
)

class MIXAR_OT_snap_selected(Operator):
    """Snap selected UVs"""
    bl_idname = "mixar.snap_selected"
    bl_label = "Snap Selected"
    bl_options = {'REGISTER', 'UNDO'}

    target: EnumProperty(
        name="Target",
        items=[
            ('PIXELS', "Pixels", ""),
            ('CURSOR', "Cursor", ""),
            ('CURSOR_OFFSET', "Cursor (Offset)", ""),
            ('ADJACENT_UNSELECTED', "Adjacent Unselected", ""),
        ],
        default='PIXELS'
    )

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.snap_selected(target=self.target)
        return {'FINISHED'}
```

**Operator with region context (for modal operators):**

```python
from mixar.modules.uv_editor.common.uv_utils import (
    poll_mixar_uv_edit_mode,
    with_uv_context_and_region,
)

class MIXAR_OT_mirror(Operator):
    """Mirror selected UVs"""
    bl_idname = "mixar.mirror"
    bl_label = "Mirror"
    bl_options = {'REGISTER', 'UNDO'}

    axis: EnumProperty(...)

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)

    @with_uv_context_and_region
    def execute(self, context, area, region):
        with context.temp_override(area=area, region=region):
            if self.axis == 'X':
                bpy.ops.transform.mirror(constraint_axis=(True, False, False))
            else:
                bpy.ops.transform.mirror(constraint_axis=(False, True, False))
        return {'FINISHED'}
```

### Using operator_properties_last()

For operators that should use their last-used settings:

```python
from mixar.modules.uv_editor.common.uv_utils import (
    poll_mixar_uv_mode,
    with_uv_context,
    get_operator_properties,
)

class MIXAR_OT_align_rotation(Operator):
    """Align island rotation"""
    bl_idname = "mixar.align_rotation"
    bl_label = "Align Rotation"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        op_props = get_operator_properties(context, "uv.align_rotation")
        with context.temp_override(area=area):
            bpy.ops.uv.align_rotation(
                method=op_props.method,
                axis=op_props.axis,
                correct_aspect=op_props.correct_aspect
            )
        return {'FINISHED'}
```

### Legacy Pattern (Pre-Refactoring - Avoid)

The old pattern without common utilities (still works but creates code duplication):

```python
class MIXAR_OT_snap_selected(Operator):
    @classmethod
    def poll(cls, context):
        # Manual poll - AVOID, use poll_mixar_uv_mode() instead
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                sima = area.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    return True
        return False

    def execute(self, context):
        # Manual context override - AVOID, use @with_uv_context instead
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                sima = area.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    with context.temp_override(area=area):
                        bpy.ops.uv.snap_selected(target=self.target)
                    return {'FINISHED'}
        return {'CANCELLED'}
```

### Existing Wrapper Operators

| Operator ID                      | Wraps                      | Purpose                        |
| -------------------------------- | -------------------------- | ------------------------------ |
| `mixar.open_uv_properties`       | Area split                 | Opens UV Properties panel      |
| `mixar.close_uv_properties`      | Area close                 | Closes UV Properties panel     |
| `mixar.snap_selected`            | `uv.snap_selected`         | Snap selection to target       |
| `mixar.snap_cursor`              | `uv.snap_cursor`           | Snap cursor to target          |
| `mixar.mirror`                   | `transform.mirror`         | Mirror UVs on axis             |
| `mixar.align`                    | `uv.align`                 | Align UVs                      |
| `mixar.align_rotation`           | `uv.align_rotation`        | Align island rotation          |
| `mixar.activate_uv_sculpt_grab`  | `wm.tool_set_by_id`        | Activates UV Sculpt Grab tool  |
| `mixar.activate_uv_sculpt_relax` | `wm.tool_set_by_id`        | Activates UV Sculpt Relax tool |
| `mixar.activate_uv_sculpt_pinch` | `wm.tool_set_by_id`        | Activates UV Sculpt Pinch tool |
| `mixar.activate_rip_region`      | `wm.tool_set_by_id`        | Activates Rip Region tool      |
| `mixar.average_islands_scale`    | `uv.average_islands_scale` | Average the size of UV islands       |
| `mixar.minimize_stretch`         | `uv.minimize_stretch`      | Minimize UV stretch                  |
| `mixar.custom_region_set`        | `uv.custom_region_set`     | Create custom regions for UV packing |
| `mixar.mark_seam`                | `uv.mark_seam`             | Mark selected edges as seam          |
| `mixar.clear_seam`               | `uv.mark_seam`             | Clear seam from selected edges       |
| `mixar.seams_from_islands`       | `uv.seams_from_islands`    | Set seams based on UV islands        |
| `mixar.stitch`                   | `uv.stitch`                | Stitch UV vertices by proximity      |
| `mixar.weld`                     | `uv.weld`                  | Weld UVs at center                   |
| `mixar.merge_at_cursor`          | `uv.snap_selected`         | Merge UVs at cursor                  |
| `mixar.remove_doubles`           | `uv.remove_doubles`        | Merge UVs by distance                |
| `mixar.select_split`             | `uv.select_split`          | Split selected UVs                   |
| `mixar.pin`                      | `uv.pin`                   | Pin selected UVs                     |
| `mixar.unpin`                    | `uv.pin`                   | Unpin selected UVs                   |
| `mixar.invert_pin`               | `uv.pin`                   | Invert pin state of UVs              |
| `mixar.hide_selected`            | `uv.hide`                  | Hide selected UV faces                      |
| `mixar.reveal`                   | `uv.reveal`                | Reveal hidden UV faces                      |
| `mixar.hide_unselected`          | `uv.hide`                  | Hide unselected UV faces                    |
| `mixar.copy_uvs`                 | `uv.copy`                  | Copy selected UVs                          |
| `mixar.paste_uvs`                | `uv.paste`                 | Paste UVs                                   |
| `mixar.reset_uvs`                | `uv.reset`                 | Reset UVs to default 0-1 space              |
| `mixar.export_uv_layout`         | `uv.export_layout`         | Export UV layout with stored properties     |

### UV Functions Panel

The `MIXAR_UV_PT_functions` panel provides essential UV editing operations organized in sections:

#### Stitch Section (Collapsible - Interactive Modal Operator)

**Purpose**: Stitch UV vertices together by proximity with live adjustment

**Properties visible in panel:**
- Mode (VERTEX/EDGE)
- Use Limit toggle + Limit Distance slider
- Snap Islands checkbox
- Midpoint Snap checkbox
- Clear Seams checkbox
- Static Island index
- Interactive help text

**Workflow:**
1. User sets properties in panel (mode, limit, snap options, etc.)
2. User clicks "Stitch (Interactive)" button
3. Operator enters modal mode in UV editor with preset values
4. User can:
   - Move mouse to adjust stitch preview
   - Press Tab to switch between vertex/edge mode
   - Press Enter to confirm
   - Press Esc to cancel
5. Properties sync with last operation for next use

**Implementation Notes:**
- Uses `operator_properties_last("uv.stitch")` to sync properties
- Operator invoked with `'INVOKE_DEFAULT'` for modal interaction
- Requires proper region context (WINDOW region) for modal to work
- Context override includes both `area` and `region` parameters

### UV Sculpt Tools Panel

The `MIXAR_UV_PT_tools` panel provides tool activation and properties for UV sculpting:

#### Panel Structure

1. **Tool Selection Section** (Always Visible)

   - Four large buttons to activate UV tools:
     - **Grab** - Move UVs by painting
     - **Relax** - Smooth UV distortion
     - **Pinch** - Push UVs together or apart
     - **Rip Region** - Separate UV regions by ripping
   - Active tool button shows `depress=True` (highlighted)

2. **Tool Properties Section** (Conditional - only when a UV sculpt tool is active)
   - **Size** - Brush size
   - **Strength** - Brush strength
   - **Falloff** (collapsible) - Brush falloff curve
   - **Options** (collapsible) - Lock Borders, Sculpt All Islands, Relax Method
   - **Drag** - UV select mode (vertex/edge/face/island)

#### Tool Activation Pattern

```python
# User clicks button in Tools panel
bpy.ops.mixar.activate_uv_sculpt_grab()

# Operator finds IMAGE_EDITOR and activates tool with context override
for area in context.screen.areas:
    if area.type == 'IMAGE_EDITOR' and area.spaces.active.mode == 'MIXAR_UV':
        with context.temp_override(area=area, space_data=sima):
            bpy.ops.wm.tool_set_by_id(name='sculpt.uv_sculpt_grab')
```

#### Getting Active Tool

```python
from bl_ui.space_toolsystem_common import ToolSelectPanelHelper

# Must get tool from IMAGE_EDITOR context, not MIXAR_UV_PROPERTIES
for area in context.screen.areas:
    if area.type == 'IMAGE_EDITOR' and area.spaces.active.mode == 'MIXAR_UV':
        with context.temp_override(area=area):
            tool = ToolSelectPanelHelper.tool_active_from_context(context)
            if tool and tool.idname == 'sculpt.uv_sculpt_grab':
                # Grab tool is active
```

### C Transform Panel - Complete Feature Set

The C Transform panel (`MIXAR_UV_PT_transform`) appears when the **Transform tool is active** in IMAGE_EDITOR and includes comprehensive transform controls:

#### Panel Structure (Collapsible Sub-Panels)

1. **Move** - Real-time UV translation with X/Y fields
2. **Pivot Point Selector** - 5 pivot modes (Bounding Box, 2D Cursor, Median, Individual Origins, Active)
3. **Rotation** - Angle field with cumulative delta rotation
4. **Resize** - Target dimension fields for precise scaling
5. **Move on Axis** - Axis-aligned movement with distance control
6. **2D Cursor** - Direct cursor position editing
7. **Arrange Islands** - Island arrangement with real-time margin adjustment
8. **Snapping** - Complete snapping configuration (Enable, Target, Base, Affect, Rotation Increment)
9. **Mirror** - X/Y axis mirroring
10. **Proportional Editing** - Full proportional editing controls
11. **Round to Pixels** - Pixel rounding mode
12. **Align** - Straighten and align operations (S, T, U, Auto, X, Y)
13. **Align Rotation** - Island rotation alignment with method and axis

#### Proportional Editing Implementation (C)

**Key Properties:**
- `tool_settings.use_proportional_edit` - Enable/disable proportional editing
- `tool_settings.use_proportional_connected` - Restrict to connected vertices only
- `tool_settings.proportional_edit_falloff` - Falloff curve type (smooth, sharp, linear, sphere, root, etc.)
- `tool_settings.proportional_size` - Size of the proportional editing influence

**C Implementation:**
```cpp
ToolSettings *tool_settings = scene->toolsettings;
PointerRNA tool_ptr = RNA_pointer_create_discrete(&scene->id, &RNA_ToolSettings, tool_settings);

uiLayout *col = &prop_edit_layout.body->column(true);

// Enable toggle
row->prop(&tool_ptr, "use_proportional_edit", UI_ITEM_NONE, IFACE_("Enable Proportional Editing"), ICON_NONE);

// Options (automatically disabled by RNA when proportional edit is off)
col->prop(&tool_ptr, "use_proportional_connected", UI_ITEM_NONE, IFACE_("Connected Only"), ICON_NONE);
col->prop(&tool_ptr, "proportional_edit_falloff", UI_ITEM_NONE, IFACE_("Falloff"), ICON_NONE);
col->prop(&tool_ptr, "proportional_size", UI_ITEM_NONE, IFACE_("Size"), ICON_NONE);
```

**How It Works:**
- The properties panel modifies `tool_settings` which is scene-level data
- Changes immediately affect the UV Editor (no context override needed)
- RNA system automatically handles property dependencies

---

## 6. Adding New Features

### Adding a New Header-Based Panel

For panels activated by clicking header buttons (Pack Islands, UV Set, etc.):

1. **Add enum value** in `properties.py`:

```python
active_panel: EnumProperty(
    items=[
        # ... existing items
        ('NEW_PANEL', 'New Panel', 'New panel description', 'ICON_NAME', 6),
    ],
)
```

2. **Add header button** in `space_image.py` (after line 760):

```python
row.prop_enum(wm.mixar_uv_ui, "active_panel", 'NEW_PANEL', text="New", icon='ICON_NAME')
```

3. **Create panel class** in `panels.py`:

```python
class MIXAR_UV_PT_new_panel(Panel):
    bl_label = "New Panel"
    bl_idname = "MIXAR_UV_PT_new_panel"
    bl_space_type = 'MIXAR_UV_PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_options = set()

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        if not hasattr(wm, 'mixar_uv_ui'):
            return False
        return wm.mixar_uv_ui.active_panel == 'NEW_PANEL'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        # ... draw content
```

4. **Register panel** in `panels.py`:

```python
classes = (
    # ... existing classes
    MIXAR_UV_PT_new_panel,
)
```

### Adding a New Tool-Based Panel

For panels activated when a specific tool is active (Transform, UV Sculpt, etc.):

**Python Implementation:**

```python
class MIXAR_UV_PT_my_tool_panel(Panel):
    bl_label = "My Tool"
    bl_idname = "MIXAR_UV_PT_my_tool_panel"
    bl_space_type = 'MIXAR_UV_PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_options = set()

    @classmethod
    def poll(cls, context):
        from bl_ui.space_toolsystem_common import ToolSelectPanelHelper

        # Only show in Edit mode with mesh
        obj = context.active_object
        if not (obj and obj.type == 'MESH' and obj.mode == 'EDIT'):
            return False

        # Check if specific tool is active in IMAGE_EDITOR
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                sima = area.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    with context.temp_override(area=area):
                        tool = ToolSelectPanelHelper.tool_active_from_context(context)
                        if tool and tool.idname == 'builtin.my_tool':
                            return True
        return False

    @classmethod
    def msgbus_subscribe(cls, context, subscribe_to):
        """Subscribe to workspace tool changes for auto-refresh."""
        workspace = context.workspace
        subscribe_to(
            owner=workspace,
            key=(workspace, "tools"),
            options={'PERSISTENT'},
            notify=cls._msgbus_on_workspace_tool_change,
        )

    @staticmethod
    def _msgbus_on_workspace_tool_change():
        """Force refresh when tools change."""
        for wm in bpy.data.window_managers:
            for window in wm.windows:
                for area in window.screen.areas:
                    if area.type == 'MIXAR_UV_PROPERTIES':
                        for region in area.regions:
                            region.tag_redraw()

    def draw(self, context):
        layout = self.layout
        # ... draw content
```

**C Implementation:**

```cpp
static bool my_panel_poll(const bContext *C, PanelType * /*pt*/)
{
  Object *obedit = CTX_data_edit_object(C);
  if (!ED_uvedit_test(obedit)) {
    return false;
  }

  bScreen *screen = CTX_wm_screen(C);
  LISTBASE_FOREACH (ScrArea *, area, &screen->areabase) {
    if (area->spacetype == SPACE_IMAGE) {
      SpaceImage *sima = static_cast<SpaceImage *>(area->spacedata.first);
      if (sima && sima->mode == SI_MODE_MIXAR_UV) {
        bToolRef *tref = area->runtime.tool;
        if (tref && STREQ(tref->idname, "builtin.my_tool")) {
          return true;
        }
      }
    }
  }
  return false;
}
```

**Key Difference:**
- **No header button needed** - panel appears automatically when tool is selected
- **Must subscribe to tool changes** (Python) or check `area->runtime.tool` (C)
- **Tool ID** must match the registered tool name in Blender's tool system

### Adding Operator Properties to a Panel

Use `operator_properties_last()` pattern:

```python
def draw(self, context):
    layout = self.layout
    wm = context.window_manager

    op_props = wm.operator_properties_last("uv.some_operator")

    col = layout.column()
    col.prop(op_props, "property_name")
    col.prop(op_props, "another_property")

    col.separator()
    row = col.row()
    row.scale_y = 1.3
    row.operator("mixar.some_operator", text="Execute")
```

### Adding a New Wrapper Operator

#### Recommended Approach (Using Common Utilities)

1. **Determine the appropriate module** for your operator:
   - `selection/` - Selection operations
   - `tools/` - Tool activation
   - `functions/` - Seam, Pin, Merge, Split, Hide operations
   - `projection/` - UV projection methods
   - `unwrap/` - Unwrapping operations
   - `pack_islands/` - Packing and island operations
   - `export/` - Export operations
   - `image/` - Image operations
   - `transform/` - Transform, snap, align operations
   - `uv_set/` - UDIM tile operations

2. **Create operator class** in the module's `operators.py`:

```python
from mixar.modules.uv_editor.common.uv_utils import (
    poll_mixar_uv_edit_mode,
    with_uv_context,
    get_operator_properties,
)

class MIXAR_OT_new_operation(Operator):
    """Description"""
    bl_idname = "mixar.new_operation"
    bl_label = "New Operation"
    bl_options = {'REGISTER', 'UNDO'}

    # Add properties if needed
    some_prop: EnumProperty(...)

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_edit_mode(context)  # Or poll_mixar_uv_mode()

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.actual_operator(prop=self.some_prop)
        return {'FINISHED'}
```

3. **Register** in the module's `operators.py`:

```python
classes = (
    # ... existing classes
    MIXAR_OT_new_operation,
)
```

4. **The `__init__.py` in the module** will automatically export it:

```python
# No changes needed - operators are already imported
from . import operators

classes = (
    *operators.classes,
)
```

#### Legacy Approach (Manual Context Override - Avoid)

For reference only (use common utilities instead):

```python
class MIXAR_OT_new_operation(Operator):
    @classmethod
    def poll(cls, context):
        # AVOID - use poll_mixar_uv_mode() instead
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                sima = area.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    return True
        return False

    def execute(self, context):
        # AVOID - use @with_uv_context decorator instead
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                sima = area.spaces.active
                if sima and sima.mode == 'MIXAR_UV':
                    with context.temp_override(area=area):
                        bpy.ops.uv.actual_operator(prop=self.some_prop)
                    return {'FINISHED'}
        return {'CANCELLED'}
```

### Adding C-Based Real-Time Controls

1. **Add static variable** for state:

```cpp
static float mixar_new_property = 0.0f;
```

2. **Add event ID**:

```cpp
#define B_MIXAR_UVEDIT_NEW 10
```

3. **Add handler** in `do_mixar_uvedit_transform()`:

```cpp
else if (event == B_MIXAR_UVEDIT_NEW) {
    // Perform operation using mixar_new_property
}
```

4. **Update condition check**:

```cpp
if (event != B_MIXAR_UVEDIT_VERTEX && ... && event != B_MIXAR_UVEDIT_NEW) {
    return;
}
```

5. **Add UI** in panel draw function:

```cpp
PanelLayout new_layout = panel->layout->panel(C, "MIXAR_UV_new_panel", false);
new_layout.header->label(IFACE_("New Section"), ICON_NONE);

if (new_layout.body) {
    uiBlock *block = new_layout.body->absolute_block();
    UI_block_func_handle_set(block, do_mixar_uvedit_transform, nullptr);

    uiBut *but = uiDefButF(block, ButType::Num, B_MIXAR_UVEDIT_NEW,
                            IFACE_("Property:"),
                            0, y -= UI_UNIT_Y, 200, UI_UNIT_Y,
                            &mixar_new_property, 0.0f, 1.0f, "Tooltip");
}
```

### Adding Expansion State for Collapsible Section

1. **Add property** in `properties.py`:

```python
class MixarUVUIState(bpy.types.PropertyGroup):
    # ... existing properties

    expand_new_section: BoolProperty(
        name='Expand New Section',
        description='Show New Section expanded',
        default=True
    )
```

2. **Use in panel**:

```python
box = layout.box()
if draw_collapsible_header(box, uv_ui, "expand_new_section", "New Section", icon='ICON'):
    col = box.column()
    # Draw content when expanded
```

---

## 7. API Reference

### Key Python Classes

| Class            | Location        | Purpose                |
| ---------------- | --------------- | ---------------------- |
| `MixarUVUIState` | `properties.py` | UI state PropertyGroup |
| `MIXAR_UV_PT_*`  | `panels.py`     | Panel classes          |
| `MIXAR_OT_*`     | `operators.py`  | Operator wrappers      |

### Key C Functions

| Function                          | Purpose                                |
| --------------------------------- | -------------------------------------- |
| `find_image_editor_context()`     | Finds IMAGE_EDITOR in MIXAR_UV mode    |
| `do_mixar_uvedit_transform()`     | Main callback for transform operations |
| `mixar_uvedit_center()`           | Calculate center of selected UVs       |
| `mixar_uvedit_translate()`        | Translate selected UVs                 |
| `mixar_uvedit_rotate()`           | Rotate selected UVs around center      |
| `mixar_uvedit_scale()`            | Scale selected UVs                     |
| `mixar_uvedit_bounds()`           | Get bounding box of selected UVs       |
| `mixar_uvedit_pivot_center()`     | Get center based on pivot mode         |
| `mixar_uv_transform_panel_draw()` | Draw Transform panel                   |
| `mixar_uv_redo_panel_draw()`      | Draw Redo panel                        |

### Key Constants

```cpp
// Event IDs for callback
#define B_MIXAR_UVEDIT_VERTEX 4   // Translation
#define B_MIXAR_UVEDIT_ROTATE 5   // Rotation
#define B_MIXAR_UVEDIT_SCALE 6    // Scale
#define B_MIXAR_UVEDIT_PIVOT 7    // Pivot change (no operation)
#define B_MIXAR_UVEDIT_CURSOR 8   // 2D Cursor

// Pivot modes (from DNA_view3d_types.h)
V3D_AROUND_CENTER_BOUNDS  // Bounding Box Center
V3D_AROUND_CURSOR         // 2D Cursor
V3D_AROUND_CENTER_MEDIAN  // Median Point
V3D_AROUND_LOCAL_ORIGINS  // Individual Origins
V3D_AROUND_ACTIVE         // Active Element
```

### Property Paths

| Path                                                     | Type             | Purpose             |
| -------------------------------------------------------- | ---------------- | ------------------- |
| `context.window_manager.mixar_uv_ui`                     | `MixarUVUIState` | UI state            |
| `context.window_manager.mixar_uv_ui.active_panel`        | `EnumProperty`   | Current panel       |
| `context.window_manager.operator_properties_last(op_id)` | `PointerRNA`     | Last operator props |

---

## Quick Reference Card

### Adding a Simple Python Panel

```python
# 1. Add to active_panel enum in properties.py
# 2. Add header button in space_image.py
# 3. Create panel:

class MIXAR_UV_PT_my_panel(Panel):
    bl_idname = "MIXAR_UV_PT_my_panel"
    bl_label = "My Panel"
    bl_space_type = 'MIXAR_UV_PROPERTIES'
    bl_region_type = 'WINDOW'

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        return hasattr(wm, 'mixar_uv_ui') and wm.mixar_uv_ui.active_panel == 'MY_PANEL'

    def draw(self, context):
        self.layout.operator("mixar.my_operator")
```

### Adding an Operator Wrapper (Modern Pattern)

```python
from mixar.modules.uv_editor.common.uv_utils import (
    poll_mixar_uv_mode,
    with_uv_context,
)

class MIXAR_OT_my_op(Operator):
    bl_idname = "mixar.my_op"
    bl_label = "My Operation"

    @classmethod
    def poll(cls, context):
        return poll_mixar_uv_mode(context)

    @with_uv_context
    def execute(self, context, area):
        with context.temp_override(area=area):
            bpy.ops.uv.actual_operator()
        return {'FINISHED'}
```

### Context Override Pattern

```python
# Python
with context.temp_override(area=area):
    bpy.ops.uv.operation()
```

```cpp
// C
ScrArea *area_prev = CTX_wm_area(C);
ARegion *region_prev = CTX_wm_region(C);
CTX_wm_area_set(C, img_ctx.area);
CTX_wm_region_set(C, img_ctx.region);
// ... operation ...
CTX_wm_area_set(C, area_prev);
CTX_wm_region_set(C, region_prev);
```
