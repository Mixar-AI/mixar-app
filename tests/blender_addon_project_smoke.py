# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real-Blender smoke for the local Add-on Project transaction boundary."""

import json
from pathlib import Path
import sys
import tempfile

import addon_utils
import bpy

from mixar.modules.addon_project.service import AddonProjectService
from mixar.modules.addon_project.ui.operators import classes as project_ui_classes


BASE_INIT = """\
bl_info = {"name": "Mixar Project Smoke", "blender": (5, 0, 0), "category": "Test"}
from . import operators

def register():
    operators.register()

def unregister():
    operators.unregister()
"""

BASE_OPERATORS = """\
import bpy

class MIXAR_SMOKE_OT_answer(bpy.types.Operator):
    bl_idname = "mixar_smoke.answer"
    bl_label = "Answer 41"

    def execute(self, context):
        return {'FINISHED'}

def register():
    bpy.utils.register_class(MIXAR_SMOKE_OT_answer)

def unregister():
    bpy.utils.unregister_class(MIXAR_SMOKE_OT_answer)
"""

UPDATED_INIT = BASE_INIT.replace(
    "from . import operators",
    "from . import operators, panels",
).replace(
    "    operators.register()",
    "    operators.register()\n    panels.register()",
).replace(
    "    operators.unregister()",
    "    panels.unregister()\n    operators.unregister()",
)

UPDATED_OPERATORS = BASE_OPERATORS.replace("Answer 41", "Answer 42")

PANELS = """\
import bpy

class MIXAR_SMOKE_PT_status(bpy.types.Panel):
    bl_label = "Mixar Project Smoke"
    bl_idname = "MIXAR_SMOKE_PT_status"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'scene'

    def draw(self, context):
        self.layout.label(text="Multi-file project loaded")

def register():
    bpy.utils.register_class(MIXAR_SMOKE_PT_status)

def unregister():
    bpy.utils.unregister_class(MIXAR_SMOKE_PT_status)
"""


def _record(description: dict, relative: str) -> dict:
    return next(item for item in description["files"] if item["path"] == relative)


def main() -> None:
    assert {cls.bl_idname for cls in project_ui_classes} == {
        "mixar.addon_project_link",
        "mixar.addon_project_unlink",
        "mixar.addon_project_open_entrypoint",
        "mixar.addon_project_set_entrypoint",
        "mixar.addon_project_run_checks",
        "mixar.addon_project_rollback_last",
    }
    newly_registered = []
    for cls in project_ui_classes:
        if not cls.is_registered:
            bpy.utils.register_class(cls)
            newly_registered.append(cls)
    assert all(cls.is_registered for cls in project_ui_classes)

    with tempfile.TemporaryDirectory(prefix="mixar_addon_project_smoke_") as temp:
        temp_root = Path(temp)
        project = temp_root / "studio_addon"
        project.mkdir()
        (project / "__init__.py").write_text(BASE_INIT, encoding="utf-8")
        (project / "operators.py").write_text(BASE_OPERATORS, encoding="utf-8")

        service = AddonProjectService(temp_root / "client_state")
        description = service.link(str(project))
        staged = service.stage_patch(description["project_id"], {
            "expected_revision": description["revision"],
            "changes": [{
                "path": "__init__.py",
                "expected_sha256": _record(description, "__init__.py")["sha256"],
                "content": UPDATED_INIT,
            }, {
                "path": "operators.py",
                "expected_sha256": _record(description, "operators.py")["sha256"],
                "content": UPDATED_OPERATORS,
            }, {
                "path": "panels.py",
                "expected_sha256": None,
                "content": PANELS,
            }],
        })
        committed = service.commit_patch(
            description["project_id"], staged["proposal_id"]
        )
        checked = service.run_checks(
            description["project_id"], reload_blender=True
        )
        assert committed["success"] and committed["checks"]["success"]
        assert checked["success"] and checked["blender_reload"]["success"]
        assert checked["blender_reload"]["left_enabled"] is False
        assert "Answer 42" in (project / "operators.py").read_text(encoding="utf-8")
        assert (project / "panels.py").is_file()

        sys.path.insert(0, str(temp_root))
        try:
            enabled_module = addon_utils.enable(
                description["entrypoint"],
                default_set=False,
            )
            assert enabled_module is not None
            checked_while_enabled = service.run_checks(
                description["project_id"],
                reload_blender=True,
            )
            assert checked_while_enabled["success"]
            assert checked_while_enabled["blender_reload"]["left_enabled"] is True
            assert hasattr(bpy.types, "MIXAR_SMOKE_PT_status")
        finally:
            addon_utils.disable(description["entrypoint"], default_set=False)
            sys.path.remove(str(temp_root))

        rolled_back = service.rollback(
            description["project_id"],
            committed["transaction_id"],
            committed["revision"],
        )
        checked_after_rollback = service.run_checks(
            description["project_id"], reload_blender=True
        )
        assert rolled_back["success"]
        assert checked_after_rollback["success"]
        assert "Answer 41" in (project / "operators.py").read_text(encoding="utf-8")
        assert not (project / "panels.py").exists()

        public = {
            "protocol_version": description["protocol_version"],
            "entrypoint": description["entrypoint"],
            "changed_files": [item["path"] for item in staged["changes"]],
            "live_reload": checked["blender_reload"]["success"],
            "enabled_reload": checked_while_enabled["blender_reload"]["success"],
            "rollback_reload": checked_after_rollback["blender_reload"]["success"],
            "ui_registered": all(cls.is_registered for cls in project_ui_classes),
        }
        assert str(project) not in json.dumps(public)
        print("ADDON_PROJECT_BLENDER_SMOKE_OK " + json.dumps(public, sort_keys=True))

    for cls in reversed(newly_registered):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    main()
