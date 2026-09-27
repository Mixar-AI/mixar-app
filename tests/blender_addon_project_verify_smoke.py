# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real-Blender smoke for verified commits: a change reaches the user only once
its reload and its tests pass; every failure reverts and keeps the old add-on.

Run in background with a throwaway user-resource dir, e.g.::

    BLENDER_USER_RESOURCES=$(mktemp -d) PYTHONPATH=src/scripts \\
        blender -b --factory-startup --python tests/blender_addon_project_verify_smoke.py

Prints one JSON line per step and exits non-zero on the first broken promise.
"""

import json
import sys
import tempfile
from pathlib import Path

import addon_utils
import bpy

from mixar.modules.addon_project import workspace
from mixar.modules.addon_project.constants import (
    PROTOCOL_VERSION,
    RPC_COMMIT_PATCH,
    RPC_STAGE_PATCH,
)
from mixar.modules.addon_project.service import AddonProjectService

NAME = "verify_smoke_tool"

INIT = """\
bl_info = {"name": "Verify Smoke", "blender": (5, 0, 0), "category": "Test"}
import bpy

LABEL = "%s"


class VERIFY_SMOKE_OT_make(bpy.types.Operator):
    bl_idname = "verify_smoke.make"
    bl_label = "Make Thing"

    def execute(self, context):
        mesh = bpy.data.meshes.new("SmokeThingMesh")
        obj = bpy.data.objects.new(LABEL, mesh)
        context.scene.collection.objects.link(obj)
        return {'FINISHED'}


class VERIFY_SMOKE_PT_main(bpy.types.Panel):
    bl_label = "Smoke Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Smoke"

    def draw(self, context):
        self.layout.operator(VERIFY_SMOKE_OT_make.bl_idname)


def menu_entry(self, context):
    self.layout.operator(VERIFY_SMOKE_OT_make.bl_idname)


keymaps = []


def register():
    %s
    bpy.utils.register_class(VERIFY_SMOKE_OT_make)
    bpy.utils.register_class(VERIFY_SMOKE_PT_main)
    bpy.types.VIEW3D_MT_object.append(menu_entry)
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig:
        keymap = keyconfig.keymaps.new(name="3D View", space_type="VIEW_3D")
        keymaps.append((keymap, keymap.keymap_items.new(VERIFY_SMOKE_OT_make.bl_idname, "J", "PRESS", ctrl=True)))


def unregister():
    for keymap, item in keymaps:
        keymap.keymap_items.remove(item)
    keymaps.clear()
    bpy.types.VIEW3D_MT_object.remove(menu_entry)
    bpy.utils.unregister_class(VERIFY_SMOKE_PT_main)
    bpy.utils.unregister_class(VERIFY_SMOKE_OT_make)
"""

TEST = """\
import unittest
import bpy


class MakeThing(unittest.TestCase):
    def test_make_creates_the_labelled_object(self):
        bpy.ops.verify_smoke.make()
        self.assertIn("%s", bpy.data.objects)
"""


def _check(step, ok, **detail):
    print(json.dumps({"step": step, "ok": bool(ok), **detail}, default=str))
    if not ok:
        sys.exit(1)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="mixar_verify_smoke_") as temp:
        root = Path(temp) / "Mixar Addons"
        root.mkdir()
        workspace.preferred_root_value = lambda: str(root)
        service = AddonProjectService(Path(temp) / "state")
        project_id = service.link_workspace_root()["project_id"]
        wire = {"protocol_version": PROTOCOL_VERSION, "project_id": project_id,
                "lease_id": service.issue_lease(project_id)["lease_id"]}

        def commit(changes):
            description = service.describe(project_id)
            hashes = {f["path"]: f["sha256"] for f in description["files"]}
            for change in changes:
                change.setdefault("expected_sha256", hashes.get(change["path"]))
            staged = service.dispatch(RPC_STAGE_PATCH, {**wire, "expected_revision": description["revision"],
                                                        "changes": changes})
            _check("stage", staged.get("success"), error=staged.get("error"))
            return service.dispatch(RPC_COMMIT_PATCH, {**wire, "proposal_id": staged["proposal_id"],
                                                       "verify": True})

        def write(path, content):
            return {"path": f"{NAME}/{path}", "operation": "write", "content": content}

        objects_before = len(bpy.data.objects)

        # 1. No tests: never lands, never installed.
        result = commit([write("__init__.py", INIT % ("SmokeThing", "pass"))])
        _check("untested_is_refused", not result["success"] and result.get("reverted")
               and "tests package" in result["error"]["message"],
               message=result.get("error"))
        _check("untested_left_nothing", not (root / NAME / "__init__.py").exists()
               and not addon_utils.check(NAME)[1])

        # 2. Passing add-on + test: proven, then live; the test's object is cleaned up.
        result = commit([write("__init__.py", INIT % ("SmokeThing", "pass")),
                         write("tests/__init__.py", ""),
                         write("tests/test_make.py", TEST % "SmokeThing")])
        proof = (result.get("verification") or [{}])[0]
        _check("good_commit_lands", result["success"] and proof.get("success"),
               tests=proof.get("tests", {}).get("message"), live=result.get("live"),
               error=result.get("error"))
        _check("good_addon_is_enabled", addon_utils.check(NAME)[1] and hasattr(bpy.ops.verify_smoke, "make"))
        usage = (result.get("live") or [{}])[0].get("usage") or {}
        panel = (usage.get("panels") or [{}])[0]
        _check("usage_names_the_sidebar_tab",
               panel.get("tab") == "Smoke"
               and panel.get("location") == "3D Viewport > Sidebar (press N) > Smoke tab > Smoke Tools panel",
               usage=usage)
        _check("usage_names_the_menu_and_operator",
               any(m["menu"] == "VIEW3D_MT_object" for m in usage.get("menus", []))
               and usage.get("operators", [{}])[0].get("idname") == "verify_smoke.make"
               and "mixar_note" in usage and "no_ui" not in usage)
        _check("tests_left_no_data", len(bpy.data.objects) == objects_before
               and proof["tests"].get("cleaned_up", 0) >= 1, cleaned=proof["tests"].get("cleaned_up"))
        good_source = (root / NAME / "__init__.py").read_text()

        # 3. A behaviour change its test rejects: reverted, old version still live.
        result = commit([write("__init__.py", INIT % ("WrongThing", "pass"))])
        _check("failing_test_reverts", not result["success"] and result.get("reverted")
               and result["verification"][0]["failed"] == "tests", message=result.get("error"))
        _check("failing_test_kept_old_source", (root / NAME / "__init__.py").read_text() == good_source)
        bpy.ops.verify_smoke.make()
        _check("old_behaviour_still_live", "SmokeThing" in bpy.data.objects and addon_utils.check(NAME)[1])

        # 4. A register() that raises: reverted, old version re-enabled.
        result = commit([write("__init__.py", INIT % ("SmokeThing", "raise RuntimeError('boom')"))])
        _check("broken_register_reverts", not result["success"] and result.get("reverted")
               and result["verification"][0]["failed"] == "reload", message=result.get("error"))
        restored = (result.get("restored") or [{}])[0]
        _check("previous_version_re_enabled", restored.get("success") and addon_utils.check(NAME)[1]
               and hasattr(bpy.ops.verify_smoke, "make"), restored=restored)
        _check("history_has_only_the_good_commit",
               len(service.history(project_id)["transactions"]) == 1)

        addon_utils.disable(NAME, default_set=False)
    print(json.dumps({"step": "done", "ok": True}))


if __name__ == "__main__":
    main()
