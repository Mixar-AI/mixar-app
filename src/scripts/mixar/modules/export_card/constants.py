# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export card constants: target ids, operator ids and the card's artboard."""

# Targets (the sidebar's tiles), in sidebar order.
MIXAR, BLEND = 'MIXAR', 'BLEND'
GLTF, FBX, USD, OBJ, STL = 'GLTF', 'FBX', 'USD', 'OBJ', 'STL'
IMAGE, VIDEO, WEB = 'IMAGE', 'VIDEO', 'WEB'

PROJECT_TARGETS = (MIXAR, BLEND)
MODEL_TARGETS = (GLTF, FBX, USD, OBJ, STL)
RENDER_TARGETS = (IMAGE, VIDEO)

# Card states (``WindowManager.mixar_export_card.state``).
IDLE, RUNNING, DONE, ERROR = 'IDLE', 'RUNNING', 'DONE', 'ERROR'

# "Made for" engines: the export lane's ``use_case`` presets
# (space_mixie_chat/core/export_presets.USE_CASES), in chip order.
ENGINES = ('web', 'unreal', 'unity', 'godot', 'ar', 'other')
DEFAULT_ENGINE = {GLTF: 'web', FBX: 'unreal', USD: 'ar', OBJ: 'other', STL: 'other'}

# Operators.
OP_OPEN = "mixar.export_card"
OP_PICK = "mixar.export_card_pick"
OP_ENGINE = "mixar.export_card_engine"
OP_SET = "mixar.export_card_set"
OP_RUN = "mixar.export_card_run"
OP_CHECK = "mixar.export_card_check"
OP_FIX = "mixar.export_card_fix"
OP_REVEAL = "mixar.export_card_reveal"
OP_AGAIN = "mixar.export_card_again"
OP_ADVANCED = "mixar.export_card_advanced"

# STL: Blender's metre is this many slicer units.
STL_UNIT_SCALE = {'MM': 1000.0, 'CM': 100.0, 'M': 1.0}

# Render quality → samples per renderer.
RENDER_SAMPLES = {
    'EEVEE': {'DRAFT': 16, 'GOOD': 64, 'FINAL': 128},
    'CYCLES': {'DRAFT': 32, 'GOOD': 128, 'FINAL': 512},
}
RENDER_EXTENSIONS = {'PNG': '.png', 'JPEG': '.jpg', 'OPEN_EXR': '.exr'}

# Repair cache identity for the card's own "Fix in scene" preflight runs.
REPAIR_SESSION = "export_card"
