# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""View3D sidebar "Game" tab. Draw only reads: cached Godot verdict, job
registry snapshots and ID properties — no process, file or network work."""

from bpy.types import Panel

from mixar.modules.common.i18n import iface_
from mixar.modules.game_studio.constants import STORE_PROP
from mixar.modules.game_studio.core import godot_locator, jobs, roles, spec as game_spec


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
        if obj is not None and obj.type in ('MESH', 'EMPTY'):
            layout.prop(obj, "mixar_game_role_ui", text=obj.name, translate=False)
        elif obj is not None:
            layout.label(text="Only meshes and empties have roles", icon='INFO')
        if len(context.selected_objects) > 1:
            layout.operator_menu_enum("mixar.game_set_role", "role", text="Set Role for Selected")
        layout.operator("mixar.game_auto_roles", icon='SHADERFX')
        summary = roles.role_summary([o for o in roles.game_objects(context.scene) if roles.in_game(o)])
        col = layout.column(align=True)
        for role in ("player", "collectible", "enemy", "hazard", "goal"):
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
        col = layout.column(heading="HUD")
        for name in ("show_score", "show_timer", "title_screen"):
            col.prop(form, name)


class MIXAR_PT_game_publish(_GamePanel, Panel):
    bl_label = "Build & Publish"
    bl_idname = "MIXAR_PT_game_publish"

    def draw(self, context):
        layout = self.layout
        form = context.window_manager.mixar_game
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
        from mixar.modules.game_studio.core.exporter import current_spec
        spec, _objects = current_spec(context.scene)
        errors, warnings = game_spec.validate_spec(spec)
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
    MIXAR_PT_game_publish,
)
