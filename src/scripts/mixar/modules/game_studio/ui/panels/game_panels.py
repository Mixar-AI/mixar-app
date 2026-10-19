# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""View3D sidebar "Game" tab. Draw only reads: cached Godot verdict, job
registry snapshots and ID properties — no process, file or network work."""

import time

import bpy
from bpy.types import Panel

from mixar.modules.common.i18n import iface_
from mixar.modules.game_studio.constants import (BOSS_TEMPLATE, PARAMS_PROP, PART_ONLY_PROP, ROLE_PROP,
                                                 STORE_PROP, platform_list)
from mixar.modules.game_studio.core import approvals, godot_locator, jobs, roles
from mixar.modules.game_studio.core.assemblies import Hierarchy


class _GamePanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Game"


class MIXAR_PT_game_godot(_GamePanel, Panel):
    bl_label = "Godot"
    bl_idname = "MIXAR_PT_game_godot"

    def draw(self, context):
        layout = self.layout
        verdict = godot_locator.cached_status()
        if verdict is None or godot_locator.is_locating():
            layout.label(text="Looking for Mixar Godot…", icon='TIME')
        elif verdict.get("found"):
            layout.label(text=iface_("Mixar Godot {version}").format(version=verdict.get("version") or ""),
                         icon='CHECKMARK', translate=False)
        else:
            layout.label(text="Mixar Godot not found", icon='ERROR')
            # The verdict message is fixed client text (never server text).
            for line in _wrap(verdict.get("message") or "", 40):
                layout.label(text=line)
        row = layout.row(align=True)
        row.operator("mixar.game_locate_godot", icon='FILEBROWSER')
        row.operator("mixar.game_refresh_godot", text="", icon='FILE_REFRESH')


class MIXAR_PT_game_roles(_GamePanel, Panel):
    bl_label = "Roles"
    bl_idname = "MIXAR_PT_game_roles"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        form = context.window_manager.mixar_game
        objects = roles.game_objects(context.scene)
        if obj is not None and obj.type in ('MESH', 'EMPTY', 'ARMATURE'):
            hierarchy = Hierarchy(objects)
            root = obj if form.role_part_only else hierarchy.assembly_root(obj)
            if root is not obj:
                layout.label(text=iface_("Asset: {name} ({count} parts)").format(
                    name=root.name, count=len(hierarchy.parts(root))), icon='OUTLINER_OB_EMPTY',
                    translate=False)
            layout.prop(root, "mixar_game_role_ui", text=root.name, translate=False)
            _role, owner = roles.governing(obj)
            if owner is not None and owner is not root:
                layout.label(text=iface_("Tagged on {name}").format(name=owner.name), icon='INFO',
                             translate=False)
            layout.prop(form, "role_part_only")
        elif obj is not None:
            layout.label(text="Only meshes, empties and armatures have roles", icon='INFO')
        if len(context.selected_objects) > 1:
            layout.operator_menu_enum("mixar.game_set_role", "role", text="Set Role for Selected")
        row = layout.row(align=True)
        row.operator("mixar.game_auto_roles", icon='SHADERFX')
        row.operator("mixar.game_auto_roles", text="", icon='FILE_REFRESH').overwrite = True
        summary = roles.role_summary([o for o in objects if roles.in_game(o)])
        col = layout.column(align=True)
        for role in ("player", "boss", "static", "prop", "collectible", "enemy", "hazard", "goal", "spawn",
                     "decor"):
            count = summary["counts"].get(role, 0)
            if count:
                col.label(text=iface_("{role}: {count}").format(role=iface_(role.title()), count=count),
                          translate=False)


class MIXAR_PT_game_settings(_GamePanel, Panel):
    bl_label = "Game Settings"
    bl_idname = "MIXAR_PT_game_settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        form = context.window_manager.mixar_game
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        for name in ("title", "template", "win"):
            layout.prop(form, name)
        if form.win == "score":
            layout.prop(form, "target_score")
        layout.prop(form, "time_limit_s")
        layout.prop(form, "lives")
        col = layout.column(heading="Player")
        for name in ("move_speed", "jump_velocity", "gravity_scale"):
            col.prop(form, name)
        col = layout.column(heading="Camera")
        col.prop(form, "camera_distance")
        col.prop(form, "camera_height")
        col = layout.column(heading="World")
        col.prop(form, "sky")
        col.prop(form, "sun")
        col.prop(form, "ambient")
        if form.template == BOSS_TEMPLATE:
            col = layout.column(heading="Atmosphere")
            col.prop(form, "preset")
            col.prop(form, "scene_lights")
            col.prop(form, "bloom")
            col.prop(form, "fog")
            if form.fog:
                col.prop(form, "fog_density")
        col = layout.column(heading="HUD")
        for name in ("show_score", "show_timer", "title_screen"):
            col.prop(form, name)


CHECK_TTL_S = 0.5
_checked = {"key": None, "at": 0.0, "value": None}


def _edit_signature(scene) -> tuple:
    """What an agent script or Auto-assign changes between two draws of one
    burst: role tags and strike markers. Part of the cache key, so a reused
    result never predates them (a TTL alone left the panels stale until the
    next unrelated redraw)."""
    tags = tuple((obj.name, obj.get(ROLE_PROP), obj.get(PARAMS_PROP), obj.get(PART_ONLY_PROP))
                 for obj in scene.objects if obj.get(ROLE_PROP) is not None)
    marks = tuple((act.name, tuple((m.name, m.frame) for m in act.pose_markers))
                  for act in bpy.data.actions if len(act.pose_markers))
    return tags, marks


def checked_scene(scene) -> dict:
    """``exporter.inspect`` for the draw callbacks, reused for CHECK_TTL_S
    so the Build and Combat panels share one walk per redraw burst."""
    from mixar.modules.game_studio.core.exporter import inspect
    key = (scene.as_pointer(), scene.get("mixar_game_spec", ""), _edit_signature(scene))
    now = time.monotonic()
    if _checked["key"] != key or now - _checked["at"] > CHECK_TTL_S:
        _checked.update(key=key, at=now, value=inspect(scene))
    return _checked["value"]


class MIXAR_PT_game_combat(_GamePanel, Panel):
    """Boss Fight only: boss HP, the attack windows and where each comes
    from, and the clips each character is missing (read-only)."""
    bl_label = "Combat"
    bl_idname = "MIXAR_PT_game_combat"
    # Its own open panel (not inside the closed Game Settings), registered
    # right after it so it sits below.

    @classmethod
    def poll(cls, context):
        return context.window_manager.mixar_game.template == BOSS_TEMPLATE

    def draw(self, context):
        layout = self.layout
        checked = checked_scene(context.scene)
        if roles.first_with_role(context.scene.objects, "boss") is not None:
            layout.prop(context.window_manager.mixar_game, "boss_hp")
        clips = (checked["spec"].get("combat") or {}).get("clips") or {}
        sources = {"markers": iface_("markers"), "configured": iface_("configured"),
                   "default": iface_("kit default")}
        for character in checked["characters"]:
            box = layout.box()
            box.label(text=character["object"], icon='ARMATURE_DATA' if character["rig"] else 'ERROR',
                      translate=False)
            if not character["rig"]:
                box.label(text="No rig: needs an armature that deforms the mesh")
                continue
            col = box.column(align=True)
            prefix = character["clip_prefix"]
            for clip, source in sorted(checked["timing"].items()):
                if not any(clip in names for names in character["clips"].values()):
                    continue
                entry = clips.get(clip) or {}
                window = entry.get("hit") or entry.get("iframes")
                # The box already names the character, so the row shows the
                # state alone; two columns keep it readable in a narrow sidebar.
                split = col.split(factor=0.45, align=True)
                split.label(text=clip[len(prefix):] if clip.startswith(prefix) else clip, translate=False)
                split.label(text=iface_("{start}-{end} s · {source}").format(
                    start=f"{window[0]:.2f}", end=f"{window[1]:.2f}", source=sources[source])
                    if window else sources[source], translate=False)
            if character["missing"]:
                names = ", ".join(character["clip_prefix"] + s.replace("_*", "_1" if s == "light_*" else "_…")
                                  for s in character["missing"])
                box.label(text=iface_("Missing: {clips}").format(clips=names), icon='INFO', translate=False)


class MIXAR_PT_game_publish(_GamePanel, Panel):
    bl_label = "Build & Publish"
    bl_idname = "MIXAR_PT_game_publish"

    def draw(self, context):
        layout = self.layout
        form = context.window_manager.mixar_game
        request = approvals.pending()
        if request is not None:
            self._draw_approval(layout, request)
        running = jobs.running()
        if running is not None:
            self._draw_running(layout, running)
        else:
            self._draw_checks(layout, context)
            row = layout.row(align=True)
            row.scale_y = 1.3
            row.operator("mixar.game_build", text="Build & Play", icon='PLAY').play = True
            row.operator("mixar.game_play", text="", icon='WINDOW')
            row = layout.row(align=True)
            for platform in ("web", "macos", "windows", "linux"):
                row.prop(form, f"platform_{platform}", toggle=True)
            layout.operator("mixar.game_export", icon='EXPORT')
            box = layout.box()
            box.prop(form, "tagline")
            box.prop(form, "description")
            box.prop(form, "genres")
            box.prop(form, "tags")
            box.operator("mixar.game_publish", icon='WORLD')
        self._draw_last(layout, context)

    @staticmethod
    def _draw_approval(layout, request):
        box = layout.box()
        box.label(text=iface_("Mixie asks to publish \"{title}\"").format(
            title=request["summary"].get("title") or ""), icon='QUESTION', translate=False)
        box.label(text=platform_list(request["summary"].get("platforms")), translate=False)
        row = box.row(align=True)
        row.operator("mixar.game_publish_approve", text="Publish", icon='CHECKMARK').request_id = \
            request["request_id"]
        row.operator("mixar.game_publish_decline", text="Cancel", icon='X').request_id = \
            request["request_id"]

    @staticmethod
    def _draw_running(layout, job):
        layout.progress(factor=job["pct"] / 100.0, type='BAR',
                        text=iface_("{kind}: {pct}%").format(kind=iface_(job["kind"].title()),
                                                             pct=int(job["pct"])),
                        translate=False)
        if job["message"]:
            layout.label(text=job["message"], translate=False)
        layout.operator("mixar.game_cancel", icon='CANCEL').job_id = job["job_id"]

    @staticmethod
    def _draw_checks(layout, context):
        checked = checked_scene(context.scene)
        errors, warnings = checked["errors"], checked["warnings"]
        # Validation lines are fixed client text, shown as built.
        for line in errors[:4]:
            layout.label(text=line, icon='ERROR', translate=False)
        for line in warnings[:2]:
            layout.label(text=line, icon='INFO', translate=False)

    @staticmethod
    def _draw_last(layout, context):
        job = jobs.latest_settled()
        if job is not None:
            result = job.get("result") or {}
            if job["state"] == "failed":
                # Errors are client text or the fork's/store's own message.
                for line in _wrap(job.get("error") or iface_("Failed"), 40)[:3]:
                    layout.label(text=line, icon='ERROR', translate=False)
            elif job["kind"] == "publish":
                layout.label(text=iface_("Published, builds in review ({status})").format(
                    status=result.get("review_status") or "pending"), icon='CHECKMARK', translate=False)
            else:
                layout.label(text=iface_("{kind} finished").format(kind=iface_(job["kind"].title())),
                             icon='CHECKMARK', translate=False)
        store_url = _store_url(context.scene)
        if store_url:
            layout.operator("mixar.game_open_store_page", icon='URL').url = store_url


def _store_url(scene) -> str:
    import json
    try:
        identity = json.loads(scene.get(STORE_PROP) or "{}")
    except (ValueError, TypeError, AttributeError):
        return ""
    return str(identity.get("store_url") or "") if isinstance(identity, dict) else ""


def _wrap(text, width):
    words, lines, line = str(text).split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width and line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


classes = (
    MIXAR_PT_game_godot,
    MIXAR_PT_game_roles,
    MIXAR_PT_game_settings,
    MIXAR_PT_game_combat,
    MIXAR_PT_game_publish,
)
