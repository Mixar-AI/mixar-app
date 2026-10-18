# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Game publishing contract v1 (``docs/modules/game-publishing-contract.md``):
roles, the ``mixar_game_spec_v1`` package, the fork CLI and job states."""

# --- §1 roles -------------------------------------------------------------
ROLE_PROP = "mixar_game_role"
PARAMS_PROP = "mixar_game_params"
# Set on a part tagged on purpose ("This part only"). A part-level tag
# WITHOUT it (left by the old per-part auto-assign) is stale: Auto-assign
# replaces it with a tag on the part's assembly root.
PART_ONLY_PROP = "mixar_game_part_only"
ROLES = ("player", "static", "prop", "collectible", "hazard", "enemy",
         "goal", "spawn", "decor", "ignore", "boss")
DEFAULT_MESH_ROLE = "static"
# Role params (all optional) and their JSON types.
PARAM_TYPES = {"value": int, "speed": float, "damage": int, "patrol_distance": float,
               "hp": int, "clip_prefix": str, "display_name": str}
# Contract v1.3 §1 param bounds: numbers (min, max), strings a pattern / length.
PARAM_RANGES = {"hp": (1, 100000)}
CLIP_PREFIX_PATTERN = r"^[A-Za-z0-9_]{1,32}$"
DISPLAY_NAME_MAX = 40

# --- v1.3 characters (rigged player / boss / enemy) -----------------------
CHARACTER_ROLES = ("player", "boss", "enemy")
DEFAULT_CLIP_PREFIX = {"boss": "boss_", "player": "player_", "enemy": "enemy_"}
# Clip states per role (§3). ``attack_*`` / ``light_<n>`` are families.
CLIP_STATES = {
    "boss": ("idle", "walk", "attack_*", "roar", "hit", "death"),
    "player": ("idle", "run", "light_*", "heavy", "dodge", "hit", "death"),
    # The contract names no enemy states; an enemy plays the boss's set.
    "enemy": ("idle", "walk", "attack_*", "roar", "hit", "death"),
}
# Pose markers on an action that time its combat windows (§2).
HIT_MARKERS = ("hit_start", "hit_end")
HIT_MARKER_SINGLE = "hit"
HIT_SINGLE_S = 0.12
IFRAME_MARKERS = ("iframes_start", "iframes_end")
# Timing sources game_status reports per attack clip (§5).
TIMING_SOURCES = ("markers", "configured", "default")

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

TEMPLATES = ("third_person", "first_person", "platformer", "top_down", "boss_fight")
WIN_RULES = ("collect_all", "reach_goal", "survive", "score", "defeat_boss")
BOSS_TEMPLATE = "boss_fight"
# What switching to boss_fight sets unless the same change sets it (§2).
BOSS_DEFAULTS = {"win": "defeat_boss", "lives": 1}
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
# Contract v1.1: every game ships for the web and both desktops by default.
DEFAULT_PLATFORMS = ("web", "macos", "windows")
# Display names (proper nouns, shown untranslated).
PLATFORM_NAMES = {"web": "Web", "macos": "macOS", "windows": "Windows", "linux": "Linux"}


def platform_list(platforms) -> str:
    """``["web", "macos"]`` → ``"Web, macOS"`` for display."""
    return ", ".join(PLATFORM_NAMES.get(p, str(p)) for p in platforms or ())
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
