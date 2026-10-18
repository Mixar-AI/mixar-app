# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sidebar properties for the Game tab.

Game settings and object roles live in plain ID properties (the scene's
spec JSON, ``obj["mixar_game_role"]``) so ``--background`` agents share
them; these RNA properties are get/set VIEWS onto that data, never a second
copy. The publish form (platforms, store page) is per-session UI state on
the WindowManager.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import PropertyGroup

from mixar.modules.game_studio.constants import ROLES
from mixar.modules.game_studio.core import roles, spec as game_spec

ROLE_ITEMS = (
    ("NONE", "Auto", "No explicit role: meshes are static, empties are left out"),
    ("player", "Player", "The character the player controls (exactly one)"),
    ("static", "Static", "Solid level geometry"),
    ("prop", "Prop", "A physics object the player can push"),
    ("collectible", "Collectible", "Picked up for score"),
    ("hazard", "Hazard", "Hurts the player on touch"),
    ("enemy", "Enemy", "Patrols and chases the player"),
    ("goal", "Goal", "Reaching it wins (Reach Goal rule)"),
    ("spawn", "Spawn", "Where the player starts"),
    ("decor", "Decor", "Visual only, no collision"),
    ("ignore", "Ignore", "Left out of the game"),
)
TEMPLATE_ITEMS = (
    ("third_person", "Third Person", "Camera follows behind the player"),
    ("first_person", "First Person", "Camera at the player's eyes"),
    ("platformer", "Platformer", "Side-on jumping"),
    ("top_down", "Top Down", "Camera looks down on the player"),
)
WIN_ITEMS = (
    ("collect_all", "Collect All", "Win by picking up every collectible"),
    ("reach_goal", "Reach Goal", "Win by entering the goal"),
    ("survive", "Survive", "Win by staying alive until the time limit"),
    ("score", "Score", "Win by reaching the target score"),
)
SKY_ITEMS = (
    ("procedural", "Procedural Sky", "A generated daylight sky"),
    ("none", "None", "Plain background"),
)
_ROLE_KEYS = [key for key, *_ in ROLE_ITEMS]
_cache = {"key": None, "settings": None}


def _settings():
    scene = bpy.context.scene
    raw = scene.get(game_spec.SPEC_PROP, "") if scene else ""
    key = (scene.as_pointer() if scene else 0, raw)
    if _cache["key"] != key:
        _cache["key"], _cache["settings"] = key, game_spec.load_settings(scene) if scene else dict(game_spec.DEFAULT_SETTINGS)
    return _cache["settings"]


def _write(section, field, value):
    scene = bpy.context.scene
    change = {field: value} if section is None else {section: {field: value}}
    merged, errors = game_spec.merge_settings(_settings(), change)
    if not errors:
        game_spec.save_settings(scene, merged)


def _view(section, field, choices=None):
    def get(_self):
        settings = _settings()
        value = settings.get(field) if section is None else settings[section].get(field)
        if choices is not None:
            keys = [key for key, *_ in choices]
            return keys.index(value) if value in keys else 0
        return value

    def set(_self, value):
        if choices is not None:
            value = choices[value][0]
        _write(section, field, value)
    return {"get": get, "set": set}


class MIXAR_GameSettings(PropertyGroup):
    title: StringProperty(name="Title", **_view(None, "title"))
    template: EnumProperty(name="Template", items=TEMPLATE_ITEMS, **_view(None, "template", TEMPLATE_ITEMS))
    win: EnumProperty(name="Win Rule", items=WIN_ITEMS, **_view("rules", "win", WIN_ITEMS))
    target_score: IntProperty(name="Target Score", min=0, max=100000, **_view("rules", "target_score"))
    time_limit_s: IntProperty(name="Time Limit (s)", min=0, max=86400, **_view("rules", "time_limit_s"))
    lives: IntProperty(name="Lives", min=0, max=99, **_view("rules", "lives"))
    move_speed: FloatProperty(name="Move Speed", min=0.1, max=100.0, **_view("player", "move_speed"))
    jump_velocity: FloatProperty(name="Jump", min=0.0, max=100.0, **_view("player", "jump_velocity"))
    gravity_scale: FloatProperty(name="Gravity", min=0.0, max=10.0, **_view("player", "gravity_scale"))
    camera_distance: FloatProperty(name="Camera Distance", min=0.5, max=100.0, **_view("camera", "distance"))
    camera_height: FloatProperty(name="Camera Height", min=-50.0, max=100.0, **_view("camera", "height"))
    sky: EnumProperty(name="Sky", items=SKY_ITEMS, **_view("world", "sky", SKY_ITEMS))
    sun: BoolProperty(name="Sun", **_view("world", "sun"))
    ambient: FloatProperty(name="Ambient", min=0.0, max=4.0, **_view("world", "ambient"))
    show_score: BoolProperty(name="Score", **_view("ui", "show_score"))
    show_timer: BoolProperty(name="Timer", **_view("ui", "show_timer"))
    title_screen: BoolProperty(name="Title Screen", **_view("ui", "title_screen"))

    role_part_only: BoolProperty(
        name="This part only",
        description="Give the role to the selected part instead of the whole asset it belongs to",
        default=False)

    # Publish form (session UI state).
    platform_web: BoolProperty(name="Web", default=True)
    platform_macos: BoolProperty(name="macOS", default=True)
    platform_windows: BoolProperty(name="Windows", default=True)
    platform_linux: BoolProperty(name="Linux", default=False)
    tagline: StringProperty(name="Tagline", default="")
    description: StringProperty(name="Description", default="")
    genres: StringProperty(name="Genres", description="Comma-separated", default="")
    tags: StringProperty(name="Tags", description="Comma-separated", default="")

    def platforms(self):
        return [p for p in ("web", "macos", "windows", "linux") if getattr(self, f"platform_{p}")]

    def store_page(self):
        split = lambda text: [w.strip() for w in text.split(",") if w.strip()]  # noqa: E731
        return {"tagline": self.tagline, "description": self.description,
                "genres": split(self.genres), "tags": split(self.tags), "price_cents": 0}


def _role_get(obj):
    role = roles.get_role(obj)
    return _ROLE_KEYS.index(role) if role in ROLES else 0


def _role_set(obj, index):
    """Set ``obj``'s role. On an assembly root (the panel draws the root
    unless "This part only" is on) part-level tags inside are cleared, so
    one asset carries one role."""
    key = _ROLE_KEYS[index]
    wm = bpy.context.window_manager
    form = getattr(wm, "mixar_game", None)
    part_only = bool(form is not None and form.role_part_only and getattr(obj, "parent", None))
    roles.set_role(obj, None if key == "NONE" else key, part_only=part_only)
    if not part_only:
        from mixar.modules.game_studio.core.assemblies import Hierarchy
        hierarchy = Hierarchy(roles.game_objects(bpy.context.scene))
        for part in hierarchy.descendants(obj):
            if roles.get_role(part):
                roles.set_role(part, None)


classes = (MIXAR_GameSettings,)


def _warm_godot_locate():
    # Warm before use: locate (and validate) Godot at idle, off the main thread.
    try:
        from mixar.config.config import get_godot_path
        from mixar.modules.game_studio.core import godot_locator
        godot_locator.locate_async(get_godot_path())
    except Exception:
        pass
    return None


def register():
    bpy.utils.register_class(MIXAR_GameSettings)
    bpy.types.WindowManager.mixar_game = bpy.props.PointerProperty(type=MIXAR_GameSettings)
    bpy.types.Object.mixar_game_role_ui = EnumProperty(
        name="Game Role", items=ROLE_ITEMS, get=_role_get, set=_role_set,
        description="What this object does in the game")
    if not bpy.app.background:
        bpy.app.timers.register(_warm_godot_locate, first_interval=8.0)


def unregister():
    for owner, name in ((bpy.types.Object, "mixar_game_role_ui"),
                        (bpy.types.WindowManager, "mixar_game")):
        if hasattr(owner, name):
            delattr(owner, name)
    if bpy.app.timers.is_registered(_warm_godot_locate):
        bpy.app.timers.unregister(_warm_godot_locate)
    bpy.utils.unregister_class(MIXAR_GameSettings)
