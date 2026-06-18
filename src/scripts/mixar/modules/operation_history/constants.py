# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the operation_history module."""

# Persistent per-scene history id (Scene StringProperty, saved in the .blend so a scene's
# operation log is continuous across saves/sessions — NOT tied to the chat session).
SCENE_HISTORY_ID_PROP = "mixar_op_history_id"

# Storage layout
MODULE_DIR_NAME = "operation_history"
ENV_BASE_DIR = "MIXAR_OPERATION_HISTORY_DIR"   # optional absolute base-dir override (tests/ops)
DEFAULT_DATA_SUBDIR = ".mixar"                  # under the user home dir
OPERATIONS_FILE = "operations.jsonl"
SCRIPTS_SUBDIR = "scripts"
NO_SESSION = "_nosession"
CLEANUP_MAX_AGE_DAYS = 15

# Record sources / kinds
SOURCE_AGENT = "AGENT"
SOURCE_USER = "USER"
KIND_OPERATION = "operation"   # mutating
KIND_QUERY = "query"           # read-only context tool
KIND_META = "meta"             # the history-read tools themselves

# Categories
CAT_OBJECT = "OBJECT"
CAT_TRANSFORM = "TRANSFORM"
CAT_MATERIAL = "MATERIAL"
CAT_LAYER = "LAYER"
CAT_MASK = "MASK"
CAT_MODE = "MODE"
CAT_SCENE = "SCENE"
CAT_SELECTION = "SELECTION"
CAT_UNDO = "UNDO"
CAT_QUERY = "QUERY"
CAT_SCRIPT = "SCRIPT"
CAT_OTHER = "OTHER"

# Read-only tools, as they appear in the RECORDED tool_name (= the RPC-frame tool name:
# the @blender_script func name, or the CONTEXT script basename). The scene_graph_query
# script backs roots/children/descendants/ancestors/describe_object, so they all record as
# "scene_graph_query". Keep in sync with the backend CONTEXT domain script basenames.
READ_ONLY_TOOLS = {
    "scene_overview", "get_object_details", "inspect_assembly",
    "scene_graph_query", "get_scene_state",
}
# Backend history-read scripts/tools. These are excluded from recording so reading the
# history does not recursively add history entries.
HISTORY_TOOLS = {"operation_history_query"}
HISTORY_SCRIPT_MARKER = "MIXAR_OPERATION_HISTORY_QUERY"

# Output caps (the backend caches tool results — keep results small)
MAX_LIST_RESULTS = 50
MAX_SCRIPT_CHARS = 20000
MAX_LABEL_CHARS = 256
