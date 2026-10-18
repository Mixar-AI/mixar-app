# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Game publishing contract v1 (``docs/modules/game-publishing-contract.md``):
roles, the ``mixar_game_spec_v1`` package, the fork CLI and job states."""

# --- §1 roles -------------------------------------------------------------
ROLE_PROP = "mixar_game_role"
PARAMS_PROP = "mixar_game_params"
ROLES = ("player", "static", "prop", "collectible", "hazard", "enemy",
         "goal", "spawn", "decor", "ignore")
DEFAULT_MESH_ROLE = "static"
# Role params (all optional) and their JSON types.
PARAM_TYPES = {"value": int, "speed": float, "damage": int, "patrol_distance": float}

# --- §2 game package --------------------------------------------------------
SPEC_SCHEMA = "mixar_game_spec_v1"
# Scene ID property holding the spec's settings as a JSON string. A plain ID
# property (no RNA registration) so ``--background`` agents read it too; the
# glTF lane runs with export_extras OFF, so it never reaches the file.
SPEC_PROP = "mixar_game_spec"
# Scene ID property with the store identity of the last publish
# ({"game_id", "slug", "store_url"}), so a re-publish updates that draft.
STORE_PROP = "mixar_game_store"
EXPORT_DIRNAME = "mixar_export"
SCENE_FILE = "scene.glb"
SPEC_FILE = "game_spec.json"
PROJECT_DIRNAME = "project"
BUILDS_DIRNAME = "builds"
RESULTS_DIRNAME = "results"
GAMES_SUBDIR = "mixar/games"

TEMPLATES = ("third_person", "first_person", "platformer", "top_down")
WIN_RULES = ("collect_all", "reach_goal", "survive", "score")
SKIES = ("procedural", "none")
TITLE_MAX = 80
SLUG_MAX = 48
DEFAULT_TITLE = "Untitled Game"

# --- §3 fork CLI ------------------------------------------------------------
FORK_MARKER = "mixar-godot"
GODOT_PATH_CONFIG_KEY = "godot_path"
GODOT_ENV_VAR = "MIXAR_GODOT_BIN"
PROGRESS_PREFIX = "MIXAR_PROGRESS "
RESULT_SCHEMA = "mixar_godot_result_v1"
PLATFORMS = ("web", "macos", "windows", "linux")
EXIT_CODES = {0: None, 1: "failed", 2: "bad_spec", 3: "import_failed",
              4: "templates_missing", 5: "export_failed"}
VERSION_TIMEOUT_S = 20.0
BUILD_TIMEOUT_S = 30 * 60.0

# --- §4 store ---------------------------------------------------------------
COMMUNITY_API_CONFIG_KEY = "community_api_url"
COMMUNITY_WEB_CONFIG_KEY = "community_web_url"
# Code-side fallbacks for a bundled mixar.json that predates the keys.
COMMUNITY_DEFAULTS = {
    "Dev": ("http://127.0.0.1:8100", "http://127.0.0.1:3000"),
    "Prod": ("https://community-api.mixar.app", "https://community.mixar.app"),
}
STORE_TIMEOUT_S = 30.0
UPLOAD_TIMEOUT_S = 15 * 60.0
UPLOAD_CHUNK = 1024 * 1024

# --- §5 jobs ------------------------------------------------------------------
JOB_KINDS = ("build", "export", "publish")
JOB_RUNNING, JOB_DONE, JOB_FAILED = "running", "done", "failed"
MAX_JOBS = 32
# The UI pump: polls while a job runs, then stops.
PUMP_SECONDS = 0.25
