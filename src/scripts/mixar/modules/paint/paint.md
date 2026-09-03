<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Paint Module Directory Structure

This document provides a comprehensive overview of the Paint module's directory structure and file descriptions.

## Root Level

```
paint/
├── __init__.py                 # Module initialization and registration
├── test_baking_operators.py    # Test file for baking operators
└── paint.md                    # This documentation file
```

---

## core/
Backend logic for texture painting operations.

### core/bake/
```
bake_update.py                  # Bake update handling
```

### core/element/
Element management (images, vertex colors, UV, fcurves).

```
__init__.py
check_elements.py               # Element validation functions
check_processes.py              # Process checking utilities
check_uv.py                     # UV validation functions
create_vcol.py                  # Vertex color creation
frame_utils.py                  # Frame/node frame utilities
get_elements.py                 # Element retrieval functions
get_vcol.py                     # Vertex color retrieval
hash_utils.py                   # Hash generation utilities
image_editor.py                 # Image editor utilities
image_utils.py                  # Image manipulation utilities
modifier_utils.py               # Modifier utility functions
modifiers.py                    # Modifier operations
pixel_operations.py             # Pixel-level image operations
remove_fcurves.py               # F-curve removal
shift_fcurves.py                # F-curve shifting operations
swap_fcurves.py                 # F-curve swapping operations
update_elements.py              # Element update functions
update_fcurves.py               # F-curve updates
update_image.py                 # Image update operations
update_uv.py                    # UV update functions
update_vcol.py                  # Vertex color updates
uv_utils.py                     # UV utility functions
vertex_colors.py                # Vertex color operations
```

#### core/element/uv_helpers/
```
__init__.py
uv_layers.py                    # UV layer management
uv_mirror.py                    # UV mirroring operations
uv_nodes.py                     # UV node handling
uv_resolution.py                # UV resolution utilities
uv_temp.py                      # Temporary UV operations
uv_transform.py                 # UV transformation functions
```

### core/handlers/
```
__init__.py
decal_handlers.py               # Decal event handlers
```

### core/io/
Node input/output connections and arrangements.

#### core/io/arrangements/
Node arrangement and positioning.
```
__init__.py
layer_arrangements.py           # Main layer node arrangement entry point
layer_arrangements_blend.py     # Blend node arrangements
layer_arrangements_cache.py     # Cache node arrangements
layer_arrangements_frame.py     # Frame node arrangements
layer_arrangements_layer.py     # Layer-specific arrangements
layer_arrangements_mask.py      # Mask node arrangements
layer_arrangements_modifier.py  # Modifier node arrangements
layer_arrangements_parallax.py  # Parallax node arrangements
layer_arrangements_source.py    # Source node arrangements
layer_arrangements_mp.py        # MPaint root node arrangements
```

#### core/io/connections/
Node connection management.
```
__init__.py
layer_connections.py            # Main layer connection entry point
layer_connections_alpha.py      # Alpha channel connections
layer_connections_blend.py      # Blend mode connections
layer_connections_channel.py    # Single channel connections
layer_connections_channels.py   # Multi-channel connections
layer_connections_context.py    # Connection context management
layer_connections_height.py     # Height channel connections
layer_connections_main.py       # Main layer connections
layer_connections_masks.py      # Mask connections
layer_connections_normal.py     # Normal map connections
layer_connections_normal_height.py     # Normal-height connections
layer_connections_normal_neighbors.py  # Normal neighbor connections
layer_connections_normal_transition.py # Normal transition connections
layer_connections_override.py   # Override connections
layer_connections_setup.py      # Connection setup utilities
layer_connections_source.py     # Source node connections
```

#### core/io/input_outputs/
Input/output node management.
```
__init__.py
input_outputs.py                # Main I/O entry point
input_outputs_channel_ios.py    # Channel I/O handling
input_outputs_layer_ios.py      # Layer I/O handling
input_outputs_layer_props.py    # Layer property I/O
input_outputs_nodes.py          # I/O node management
input_outputs_props.py          # Property I/O utilities
inputs.py                       # Input node handling
outputs.py                      # Output node handling
```

#### core/io/mask/
Mask-specific I/O.
```
__init__.py
mask_channels.py                # Mask channel handling
mask_connections.py             # Mask node connections
mask_source.py                  # Mask source handling
mask_vector.py                  # Mask vector operations
```

#### core/io/parallax/
Parallax mapping I/O.
```
__init__.py
parallax_connections.py         # Parallax node connections
parallax_input_utils.py         # Parallax input utilities
parallax_layer_nodes.py         # Parallax layer nodes
parallax_process_nodes.py       # Parallax processing nodes
```

#### core/io/setup_helpers/
I/O setup helper functions.
```
__init__.py
bump_setup.py                   # Bump map setup
channel_setup.py                # Channel setup utilities
rgb_alpha_setup.py              # RGB/Alpha channel setup
vector_setup.py                 # Vector channel setup
```

#### core/io/utils/
I/O utility functions.
```
__init__.py
bsdf_connections.py             # BSDF node connections
channel_autodetect.py           # Channel auto-detection
check_io.py                     # I/O validation
connections.py                  # General connection utilities
depth_connections.py            # Depth channel connections
io_utils.py                     # General I/O utilities
source_connections.py           # Source connection helpers
update_io.py                    # I/O update functions
```

#### core/io/mp/
MPaint root node connections.
```
__init__.py
mp_connections.py               # Main MPaint connections
mp_connections_baked.py         # Baked channel connections
mp_connections_channels.py      # Channel connections
mp_connections_layers.py        # Layer connections
mp_connections_parallax.py      # Parallax connections
```

### core/layer/
Layer logic and management.
```
__init__.py
channel_and_processing_checks.py # Channel/processing validation
channel_io.py                   # Channel I/O operations
check_channels.py               # Channel validation
check_layers.py                 # Layer validation
create_channels.py              # Channel creation
displacement_handling.py        # Displacement channel handling
enable_state_checks.py          # Enable state validation
get_channels.py                 # Channel retrieval
get_entities.py                 # Entity retrieval (layers/masks)
get_layers.py                   # Layer retrieval
layer_type_checks.py            # Layer type validation
layer_utils.py                  # Layer utility functions
mappings.py                     # Layer/channel mappings
normal_processing.py            # Normal map processing
transformations.py              # Layer transformations
update_channels.py              # Channel updates
update_layers.py                # Layer updates
```

### core/layer_handlers/
Layer type-specific handlers.
```
__init__.py
base_handler.py                 # Base handler class
fill_layer_handler.py           # Fill layer handling
handler_registry.py             # Handler registration
paint_layer_handler.py          # Paint layer handling
procedural_layer_handler.py     # Procedural layer handling
```

### core/lib/
Shared library functions.
```
lib.py                          # Core library functions
lib_operations.py               # Library operations
```

### core/material/
Material management.
```
__init__.py
check_materials.py              # Material validation
get_materials.py                # Material retrieval
```

### core/migration/
Data migration utilities.
```
__init__.py
layer_migration.py              # Layer data migration
```

### core/modifier/
Layer modifier system.
```
mask_modifier.py                # Mask modifier handling
modifier.py                     # Base modifier operations
modifier_channel.py             # Channel modifier handling
modifier_commons.py             # Common modifier utilities
modifier_node_handlers.py       # Modifier node handlers
modifier_nodes.py               # Modifier node creation
modifier_props.py               # Modifier properties
modifier_tree.py                # Modifier tree management
modifier_updates.py             # Modifier updates
```

### core/node/
Shader node management.
```
__init__.py
check_channel_blend_nodes.py    # Channel blend node validation
check_channel_helpers.py        # Channel node helpers
check_channel_normal_nodes.py   # Normal channel validation
check_layer_io_nodes.py         # Layer I/O node validation
check_mask_nodes.py             # Mask node validation
check_nodes.py                  # General node validation
check_parallax_nodes.py         # Parallax node validation
check_texcoord_nodes.py         # Texture coordinate validation
check_transition_ao_ramp.py     # Transition AO ramp validation
check_transition_bump.py        # Transition bump validation
check_uv_nodes.py               # UV node validation
create_nodes.py                 # Node creation utilities
get_nodes.py                    # Node retrieval
height_blend_nodes.py           # Height blend nodes
height_operations.py            # Height operations
height_process_nodes.py         # Height processing nodes
iterate_nodes.py                # Node iteration utilities
loc.py                          # Node location utilities
node_active_utils.py            # Active node utilities
node_copy_utils.py              # Node copying utilities
node_graph.py                   # Node graph utilities
node_tree_utils.py              # Node tree utilities
node_utils.py                   # General node utilities
normal_process_nodes.py         # Normal processing nodes
transition_ao.py                # Transition AO handling
transition_bump_influence.py    # Transition bump influence
transition_ramp.py              # Transition ramp handling
update_nodes.py                 # Node update functions
update_nodes_helpers.py         # Node update helpers
vdisp_process_nodes.py          # Vector displacement nodes
```

### core/subtree/
Layer subtree management.
```
__init__.py
channel_source_tree.py          # Channel source subtree
check_subtree.py                # Subtree validation
get_subtree.py                  # Subtree retrieval
height_calculations.py          # Height calculations
layer_hierarchy.py              # Layer hierarchy management
layer_source_tree.py            # Layer source subtree
mask_source_tree.py             # Mask source subtree
tree_operations.py              # Tree operations
update_subtree.py               # Subtree updates
```

---

## ui/
User interface components.

### Root UI Files
```
__init__.py
channel_filter.py               # Channel filtering UI
ui.py                           # Main UI module
ui_paint.py                     # Paint UI components
ui_state.py                     # UI state management
```

### ui/bake/
Baking operators and utilities.

#### ui/bake/channel/
```
__init__.py
bake_channel_core.py            # Channel baking core logic
bake_channel_helpers.py         # Channel bake helpers
bake_channel_normal.py          # Normal channel baking
bake_channel_temp.py            # Temporary bake operations
bake_outside_channel_setup.py   # Outside channel setup
bake_outside_cleanup.py         # Outside bake cleanup
bake_outside_nodes.py           # Outside bake nodes
```

#### ui/bake/entity/
```
__init__.py
bake_entity_image.py            # Entity to image baking
bake_entity_to_image_invoke.py  # Bake invoke handling
bake_entity_to_image_op.py      # MBakeEntityToImage operator
bake_entity_to_image_ui.py      # Entity bake UI
bake_to_entity.py               # Bake to entity core
bake_to_entity_atlas.py         # Atlas bake handling
bake_to_entity_execute.py       # Entity bake execution
bake_to_entity_helpers.py       # Entity bake helpers
bake_to_entity_loop.py          # Entity bake loop
bake_to_entity_nodes.py         # Entity bake nodes
bake_to_entity_process.py       # Entity bake processing
bake_to_entity_setup.py         # Entity bake setup
```

#### ui/bake/layer/
```
__init__.py
bake_layer_modifiers.py         # Layer modifier baking
bake_to_layer_invoke.py         # Bake to layer invoke
bake_to_layer_op.py             # MBakeToLayer operator
bake_to_layer_operators.py      # Bake operator aggregation
bake_to_layer_operators_helper.py # Bake operator helpers
bake_to_layer_properties.py     # Bake properties
bake_to_layer_ui.py             # Bake to layer UI
```

#### ui/bake/merge/
```
__init__.py
merge_layer_execute.py          # Layer merge execution
merge_layer_helpers.py          # Merge helpers
merge_layer_invoke.py           # Merge invoke handling
merge_layer_operator.py         # MMergeLayer operator
merge_layer_ui.py               # Merge UI
merge_mask_operator.py          # Mask merge operator
```

#### ui/bake/object_prep/
```
__init__.py
bake_object_helpers.py          # Object bake helpers
bake_object_prep.py             # Object preparation
bake_object_prep_channels.py    # Channel preparation
bake_object_prep_colors.py      # Color preparation
bake_object_prep_mesh.py        # Mesh preparation
```

#### ui/bake/operators/
```
__init__.py
bake_base_operator.py           # Base bake operator class
bake_channel_operators.py       # Channel bake operators
bake_channel_operators_helpers.py # Channel operator helpers
bake_channel_operators_ui.py    # Channel operator UI
bake_height_ops.py              # Height bake operators
bake_image_resize_operator.py   # Image resize operator
bake_merge_operators.py         # Merge operators
bake_operators.py               # General bake operators
bake_preview_operators.py       # Preview toggle operators
bake_temp_operators.py          # Temporary bake operators
bake_utility_operators.py       # Utility bake operators
bake_uv_ops.py                  # UV bake operators
bake_uv_transfer_operators.py   # UV transfer operators
bake_vcol_operator.py           # Vertex color bake operator
```

#### ui/bake/target/
```
__init__.py
bake_target_helpers.py          # Target bake helpers
bake_target_operators.py        # Target bake operators
bake_target_operators_helper.py # Target operator helpers
bake_target_properties.py       # Target properties
```

#### ui/bake/utils/
```
__init__.py
bake_common.py                  # Common bake utilities
bake_constants.py               # Bake constants
bake_displacement_helpers.py    # Displacement bake helpers
bake_effects.py                 # Bake effects (FXAA, SSAA)
bake_execution.py               # Bake execution
bake_image_config.py            # Image configuration
bake_image_helpers.py           # Image bake helpers
bake_image_processing.py        # Image processing
bake_info_properties.py         # Bake info properties
bake_node_utils.py              # Bake node utilities
bake_normal_overlay.py          # Normal overlay baking
bake_operations.py              # Bake operations
bake_operators_helper.py        # Operator helpers
bake_prepare.py                 # Bake preparation
bake_property_callbacks.py      # Property callbacks
bake_result_handlers.py         # Result handling (atlas, layers, masks)
bake_scene_settings.py          # Scene settings management
bake_settings_manager.py        # Settings manager
bake_state_manager.py           # State manager
bake_subdivision.py             # Subdivision handling
bake_temp_materials.py          # Temporary materials
bake_update_handlers.py         # Update handlers
bake_utils.py                   # General bake utilities
bake_uv_transfer.py             # UV transfer utilities
bake_validation.py              # Bake validation
bake_vcol_helpers.py            # Vertex color helpers
bake_vcol_utils.py              # Vertex color utilities
composite_settings.py           # Compositor settings
compositor_effects.py           # Compositor effects
image_resize.py                 # Image resize utilities
```

### ui/displacement/
```
__init__.py
displacement_utils.py           # Displacement utilities
```

### ui/dragdrop/
```
__init__.py
# Drag and drop functionality
```

### ui/image_atlas/
```
__init__.py
image_atlas_conversion_operators.py  # Atlas conversion operators
image_atlas_operators.py        # Atlas operators
image_atlas_operators_helper.py # Atlas operator helpers
image_atlas_properties.py       # Atlas properties
image_atlas_utils.py            # Atlas utilities
image_atlas_uv_operators.py     # Atlas UV operators
```

### ui/image_ops/
```
__init__.py
float_image_helpers.py          # Float image helpers
image_format_helpers.py         # Image format helpers
image_ops_basic.py              # Basic image operations
image_ops_convert.py            # Image conversion
image_ops_operator.py           # Image operators
image_ops_operators_helper.py   # Operator helpers
image_ops_save.py               # Image save operations
image_ops_save_as.py            # Save as operations
image_ops_utils.py              # Image operation utilities
image_save_helpers.py           # Save helpers
save_as_execute_helpers.py      # Save as execution helpers
save_as_ui_helpers.py           # Save as UI helpers
```

### ui/layer/
Layer UI components.

#### ui/layer/callbacks/
```
__init__.py
layer_callbacks_projection.py   # Projection callbacks
layer_callbacks_source.py       # Source callbacks
layer_callbacks_transform.py    # Transform callbacks
layer_channel_callbacks.py      # Channel callbacks
layer_normal_callbacks.py       # Normal map callbacks
layer_override_callbacks.py     # Override callbacks
layer_state_callbacks.py        # State callbacks
layer_uv_callbacks.py           # UV callbacks
layer_visual_callbacks.py       # Visual callbacks
```

#### ui/layer/channel/
```
__init__.py
channel_defaults.py             # Channel default values
channel_image_operators.py      # Channel image operators
channel_image_utils.py          # Channel image utilities
channel_override_image_ops.py   # Override image operators
channel_source_callbacks.py     # Source callbacks
channel_source_properties.py    # Source properties
layer_channel_setup.py          # Channel setup
```

#### ui/layer/helpers/
```
__init__.py
layer_create_helpers.py         # Layer creation helpers (add_new_layer)
layer_duplicate_helpers.py      # Layer duplication helpers
layer_enum_helpers.py           # Enum helpers (channel_items, get_normal_map_type_items)
layer_move_ops.py               # Layer move operators
layer_operation_helpers.py      # Operation helpers (remove_layer)
layer_removal_helpers.py        # Layer removal helpers
layer_search_helpers.py         # Layer search utilities
layer_transform_utils.py        # Transform utilities
layer_type_helpers.py           # Layer type helpers
layer_ui_draw_helpers.py        # UI draw helpers
layer_ui_helpers.py             # General UI helpers
```

#### ui/layer/operators/
```
__init__.py
layer_group_ops.py              # Layer group operators
layer_operators.py              # General layer operators
layer_operators_crud.py         # CRUD operators (create, read, update, delete)
layer_operators_crud_helpers.py # CRUD helpers
layer_operators_crud_ui.py      # CRUD UI components
layer_operators_crud_ui_mask.py # CRUD UI for masks
layer_operators_transform.py    # Transform operators
```

#### ui/layer/properties/
```
__init__.py
layer_channel_properties.py     # Channel property definitions
layer_properties.py             # MLayer PropertyGroup
layer_properties_callbacks.py   # Property callbacks
layer_properties_channel_nodes.py # Channel node properties
layer_properties_layer.py       # Layer-specific properties
layer_properties_transition.py  # Transition properties
```

#### ui/layer/utils/
```
__init__.py
brush_texture_ops.py            # Brush texture operators
decal_utils.py                  # Decal utilities
driver_utils.py                 # Driver utilities
image_duplicate_utils.py        # Image duplication utilities
layer_mask_setup.py             # Layer mask setup
layer_source_setup.py           # Layer source setup
vcol_duplicate_utils.py         # Vertex color duplication
```

### ui/list_item/
```
__init__.py
list_item_operators.py          # List item operators
list_item_operators_helper.py   # Operator helpers
list_item_properties.py         # List item properties
list_item_utils.py              # List item utilities
```

### ui/lists/
```
__init__.py
layer_uilist.py                 # Layer UIList implementation
```

### ui/mask/
```
__init__.py
mask_creation.py                # Mask creation (add_new_mask)
mask_operators.py               # Mask operators
mask_operators_helper.py        # Mask operator helpers
mask_operators_new.py           # New mask operators
mask_operators_new_draw.py      # New mask draw UI
mask_operators_new_execute.py   # New mask execution
mask_operators_open.py          # Open mask operators
mask_operators_open_data.py     # Open mask data
mask_operators_open_image.py    # Open mask image
mask_properties.py              # Mask properties
mask_properties_helper.py       # Property helpers
mask_properties_misc.py         # Misc mask properties
mask_properties_name_enable.py  # Name/enable properties
mask_properties_source.py       # Source properties
mask_properties_uv_transform.py # UV transform properties
mask_removal.py                 # Mask removal
mask_source_setup.py            # Mask source setup
mask_type_utils.py              # Mask type utilities
mask_utils.py                   # General mask utilities
```

### ui/mask_modifier/
```
__init__.py
mask_modifier_operators.py      # Mask modifier operators
mask_modifier_operators_helpers.py # Operator helpers
mask_modifier_properties.py     # Modifier properties
mask_modifier_utils.py          # Modifier utilities
```

### ui/menus/
```
__init__.py
layer_menus.py                  # Layer context menus
```

### ui/modifier/
```
__init__.py
modifier_operators.py           # Modifier operators
modifier_operators_helper.py    # Operator helpers
modifier_popup.py               # Modifier popup UI
modifier_properties.py          # Modifier properties
modifier_utils.py               # Modifier utilities
```

### ui/normal_map_modifier/
```
__init__.py
normal_map_modifier_operators.py        # Normal modifier operators
normal_map_modifier_operators_helper.py # Operator helpers
normal_map_modifier_properties.py       # Modifier properties
normal_map_modifier_utils.py            # Modifier utilities
```

### ui/operators/
Main operators module.
```
__init__.py
add_channel.py                  # Add channel operators
channel_menu.py                 # Channel menu
channel_operators.py            # Channel operators
create_material_op.py           # Create material operator
decal_operators.py              # Decal operators
layer_add_ops.py                # Layer add operators
layer_channel_ops.py            # Layer channel operators
layer_clipboard_ops.py          # Copy/paste layer operators
layer_copy_ops.py               # Layer copy operators
layer_duplicate_ops.py          # Layer duplicate operators
layer_edit_ops.py               # Layer edit operators
layer_group_membership_ops.py   # Group membership operators
layer_group_ops.py              # Layer group operators
layer_image_import_ops.py       # Image import operators
layer_menu_ops.py               # Layer menu operators
layer_menus.py                  # Layer menus
layer_move_ops.py               # Layer move operators
layer_operators.py              # General layer operators
layer_paint_ops.py              # Paint operators
layer_paint_ops_helpers.py      # Paint helpers
layer_popup_ops.py              # Popup operators
layer_procedural_ops.py         # Procedural layer operators
layer_remove_ops.py             # Layer remove operators
layer_selection_ops.py          # Selection operators
mask_operators.py               # Mask operators
material_ops.py                 # Material operators
material_slot_ops.py            # Material slot operators
move_channel.py                 # Move channel operators
operators_helper_displacement.py # Displacement helpers
procedural_library_ops.py       # Procedural library operators
procedural_material_ops.py      # Procedural material operators
procedural_pattern_ops.py       # Procedural pattern operators
remove_channel.py               # Remove channel operators
```

### ui/other/
```
__init__.py
cozy_panel_operators.py         # Cozy panel operators
helper_gn.py                    # Geometry nodes helpers
```

### ui/panels/
```
__init__.py
baking_panel.py                 # Baking panel
layer_popup.py                  # Layer popup panel
layers_panel.py                 # Main layers panel
panel_modifiers.py              # Modifiers panel
paint_panel.py                  # Paint panel
panel_utils.py                  # Panel utilities
```

### ui/properties/
```
__init__.py
channel_properties.py           # Channel properties
layer_properties_callbacks.py   # Layer property callbacks
main_paint_properties.py        # Main paint properties (MPaintProperties)
wm_properties.py                # Window manager properties
```

### ui/transition/
```
__init__.py
transition_bump_operators.py    # Transition bump operators
transition_bump_utils.py        # Transition bump utilities
transition_operators.py         # General transition operators
transition_properties.py        # Transition properties
transition_ramp_utils.py        # Transition ramp utilities
```

### ui/udim/
```
__init__.py
udim_properties.py              # UDIM properties
udim_utils.py                   # UDIM utilities
udim_utils_atlas.py             # UDIM atlas utilities
udim_utils_segment.py           # UDIM segment utilities
```

### ui/utils/
```
__init__.py
ui_helpers.py                   # General UI helpers
ui_helpers_channels.py          # Channel UI helpers
ui_helpers_fill_channel_row.py  # Fill channel row helpers
ui_helpers_fill_extras.py       # Fill extras helpers
ui_helpers_fill_utils.py        # Fill utilities
ui_helpers_layer_material.py    # Layer material helpers
ui_helpers_mask.py              # Mask UI helpers
ui_helpers_mask_sections.py     # Mask section helpers
ui_helpers_mask_utils.py        # Mask utility helpers
ui_helpers_materials.py         # Material UI helpers
ui_helpers_toolbar.py           # Toolbar helpers
ui_refresh.py                   # UI refresh utilities
```

### ui/vcol/
```
__init__.py
vcol_operators.py               # Vertex color operators
```

### ui/vector_displacement/
```
__init__.py
bake_settings_helpers.py        # Bake settings helpers
vdisp_operators.py              # Vector displacement operators
vdisp_preview_operators.py      # Preview operators
vector_displacement_operators_helper.py # Operator helpers
vector_displacement_properties.py       # VDisp properties
```

---

## utils/
Shared utilities and constants.
```
bake_constants.py               # Baking constants
blender_commons.py              # Common Blender utilities
blender_commons_color.py        # Color utilities
blender_commons_context.py      # Context utilities
blender_commons_image.py        # Image utilities
bsdf_constants.py               # BSDF constants
channel_constants.py            # Channel constants
channel_detection.py            # Channel detection utilities
classes.py                      # Class utilities
common.py                       # General common utilities
common_addon.py                 # Addon common utilities
common_animation.py             # Animation utilities
common_entity.py                # Entity utilities
common_layer_types.py           # Layer type utilities
common_nodes.py                 # Node utilities
common_properties.py            # Property utilities
common_ui.py                    # UI utilities
constants.py                    # General constants
layer_constants.py              # Layer constants
mask_constants.py               # Mask constants
math_utils.py                   # Math utilities
node_constants.py               # Node constants
preferences.py                  # Addon preferences
statics.py                      # Static values (blend_type_items, etc.)
texture_constants.py            # Texture constants
ui_constants.py                 # UI constants
```

---

## procedural_materials/
Procedural material definitions (organized by category).
```
__init__.py
material_registry.py            # Material registration
test_compatibility.py           # Compatibility testing
```

### Material Categories
- `filtered_asphalt_matplus/` - Asphalt materials
- `filtered_bricks_matplus/` - Brick materials
- `filtered_ceramic_matplus/` - Ceramic materials
- `filtered_concrete_matplus/` - Concrete materials
- `filtered_dirt_matplus/` - Dirt materials
- `filtered_fabric_matplus/` - Fabric materials
- `filtered_floor_matplus/` - Floor materials
- `filtered_food_matplus/` - Food materials
- `filtered_fx_matplus/` - FX materials
- `filtered_glass_matplus/` - Glass materials
- `filtered_grass_matplus/` - Grass materials
- `filtered_ground_matplus/` - Ground materials
- `filtered_human_matplus/` - Human materials
- `filtered_ice_matplus/` - Ice materials
- `filtered_leather_matplus/` - Leather materials
- `filtered_liquid_matplus/` - Liquid materials
- `filtered_marble_matplus/` - Marble materials
- `filtered_metal_matplus/` - Metal materials
- `filtered_organic_matplus/` - Organic materials
- `filtered_ornaments_matplus/` - Ornament materials
- `filtered_paper_matplus/` - Paper materials
- `filtered_paving_matplus/` - Paving materials
- `filtered_plaster_matplus/` - Plaster materials
- `filtered_plastic_matplus/` - Plastic materials
- `filtered_rock_matplus/` - Rock materials
- `filtered_roofing_matplus/` - Roofing materials
- `filtered_rust_matplus/` - Rust materials
- `filtered_sand_matplus/` - Sand materials
- `filtered_stone_matplus/` - Stone materials
- `filtered_tech_matplus/` - Tech materials
- `filtered_tiles_matplus/` - Tile materials
- `filtered_wood_matplus/` - Wood materials
- `thumbnails_transparent/` - Material thumbnails

---

## Key Import Mappings

When importing from the `ui/layer/` module, use direct submodule paths:

| Export | Location |
|--------|----------|
| `add_new_layer` | `ui/layer/helpers/layer_create_helpers.py` |
| `remove_layer` | `ui/layer/helpers/layer_operation_helpers.py` |
| `duplicate_layer_nodes_and_images` | `ui/layer/helpers/layer_duplicate_helpers.py` |
| `channel_items` | `ui/layer/helpers/layer_enum_helpers.py` |
| `get_normal_map_type_items` | `ui/layer/helpers/layer_enum_helpers.py` |
| `check_override_layer_channel_nodes` | `ui/layer/callbacks/layer_override_callbacks.py` |
| `MLayer` | `ui/layer/properties/layer_properties.py` |
| `MOpenImageToOverrideChannel` | `ui/layer/channel/channel_image_operators.py` |
