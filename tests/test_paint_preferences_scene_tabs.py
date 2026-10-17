# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Paint preferences persist per user, not per Scene.

A scene created after load (a scene tab) must start from the saved values,
and an edit made in a scene that still holds defaults must never reset the
other saved keys. The add-on projects root moved out of the group into the
per-user config and is migrated there once.
"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.paint.utils import preferences_config as pc


ROOT = Path(__file__).resolve().parents[1]
PAINT = ROOT / "src/scripts/mixar/modules/paint"


class _Prefs:
    """A MixarPaintPreferences stand-in: attributes + bl_rna + idprop get."""

    _NAMES = ("default_new_image_size", "developer_mode", "icons")

    def __init__(self, idprops=None, **values):
        self.default_new_image_size = 1024
        self.developer_mode = False
        self.icons = "DEFAULT"
        for key, value in values.items():
            setattr(self, key, value)
        self._idprops = dict(idprops or {})
        self.bl_rna = SimpleNamespace(properties=[
            SimpleNamespace(identifier=name) for name in ("rna_type",) + self._NAMES
        ])

    def get(self, key, default=None):
        return self._idprops.get(key, default)


_uid = iter(range(1000, 100000))


def _scene(**values):
    return SimpleNamespace(session_uid=next(_uid), mixar_paint_preferences=_Prefs(**values))


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "preferences.json"
    monkeypatch.setattr(pc, "get_prefs_path", lambda: str(path))
    first = _scene()
    fake_bpy = SimpleNamespace(
        context=SimpleNamespace(scene=first),
        data=SimpleNamespace(scenes=[first]),
    )
    monkeypatch.setattr(pc, "bpy", fake_bpy)
    monkeypatch.setattr(pc, "_loading", False)
    pc.reset_hydration()
    yield SimpleNamespace(path=path, bpy=fake_bpy, first=first)
    pc.reset_hydration()


def _saved(env):
    return json.loads(env.path.read_text(encoding="utf-8"))


def test_a_default_scene_edit_merges_one_key(env):
    env.path.write_text(json.dumps({
        "default_new_image_size": 4096, "developer_mode": True, "icons": "LEGACY",
    }), encoding="utf-8")
    tab = _scene()  # a new scene tab, never hydrated: every value is a default
    tab.mixar_paint_preferences.icons = "DEFAULT"

    pc.save_preferences(prefs=tab.mixar_paint_preferences, key="icons")

    assert _saved(env) == {
        "default_new_image_size": 4096, "developer_mode": True, "icons": "DEFAULT",
    }


def test_save_without_a_key_merges_every_property_and_keeps_unknown_keys(env):
    env.path.write_text(json.dumps({"future_key": 1}), encoding="utf-8")
    pc.save_preferences()
    assert _saved(env) == {
        "future_key": 1, "default_new_image_size": 1024,
        "developer_mode": False, "icons": "DEFAULT",
    }


def test_load_preferences_hydrates_the_scene_passed_in(env):
    env.path.write_text(json.dumps({"developer_mode": True, "gone": 3}), encoding="utf-8")
    other = _scene()
    pc.load_preferences(other)
    assert other.mixar_paint_preferences.developer_mode is True
    assert env.first.mixar_paint_preferences.developer_mode is False


def test_scenes_created_after_load_are_hydrated_once(env):
    env.path.write_text(json.dumps({"default_new_image_size": 2048}), encoding="utf-8")
    pc.load_preferences()
    assert pc.hydrate_new_scenes() == 0
    tab = _scene()
    env.bpy.data.scenes.append(tab)

    assert pc.hydrate_new_scenes() == 1
    assert tab.mixar_paint_preferences.default_new_image_size == 2048
    # A later change in the tab is its own; the timer never re-applies.
    tab.mixar_paint_preferences.default_new_image_size = 512
    assert pc.hydrate_new_scenes() == 0
    assert tab.mixar_paint_preferences.default_new_image_size == 512


def test_hydration_does_not_save(env, monkeypatch):
    env.path.write_text(json.dumps({"developer_mode": True}), encoding="utf-8")
    writes = []
    monkeypatch.setattr(pc, "_write_prefs_file", writes.append)
    env.bpy.data.scenes.append(_scene())
    pc.hydrate_new_scenes()
    assert writes == []


def test_every_property_saves_only_its_own_key():
    source = (PAINT / "ui/properties/preferences_properties.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    group = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MixarPaintPreferences"
    )
    fields = [node for node in group.body if isinstance(node, ast.AnnAssign)]
    assert fields
    for field in fields:
        update = next(kw.value for kw in field.annotation.keywords if kw.arg == "update")
        assert isinstance(update, ast.Call) and update.args[0].value == field.target.id


def test_new_scenes_are_hydrated_from_the_ui_timer_and_on_load():
    handlers = (PAINT / "ui/utils/ui_handlers.py").read_text(encoding="utf-8")
    timer = handlers.split("def _ui_update_timer", 1)[1].split("\ndef ", 1)[0]
    assert timer.index("_hydrate_new_scenes()") < timer.index("if not _needs_update")
    restore = handlers.split("def _restore_preferences", 1)[1].split("\n@persistent", 1)[0]
    for step in ("reset_hydration()", "load_preferences()", "hydrate_new_scenes()",
                 "migrate_addon_projects_dir()"):
        assert step in restore


class _Config:
    def __init__(self, monkeypatch, stored=None, writable=True):
        import mixar.config.config as config

        self.values = {} if stored is None else {"addon_projects_dir": stored}
        self.writable = writable
        monkeypatch.setattr(config, "has_addon_projects_dir",
                            lambda: "addon_projects_dir" in self.values)
        monkeypatch.setattr(config, "set_addon_projects_dir", self._set)

    def _set(self, value):
        if not self.writable:
            return False
        self.values["addon_projects_dir"] = value
        return True


def test_migration_takes_the_saved_json_value_once(env, monkeypatch):
    cfg = _Config(monkeypatch)
    env.path.write_text(json.dumps({"addon_projects_dir": "/json/root"}), encoding="utf-8")
    assert pc.migrate_addon_projects_dir() is True
    assert cfg.values == {"addon_projects_dir": "/json/root"}
    env.path.write_text(json.dumps({"addon_projects_dir": "/other"}), encoding="utf-8")
    assert pc.migrate_addon_projects_dir() is False
    assert cfg.values == {"addon_projects_dir": "/json/root"}


def test_migration_falls_back_to_a_scene_idprop(env, monkeypatch):
    cfg = _Config(monkeypatch)
    env.bpy.data.scenes.append(SimpleNamespace(
        session_uid=next(_uid),
        mixar_paint_preferences=_Prefs(idprops={"addon_projects_dir": "/scene/root"}),
    ))
    assert pc.migrate_addon_projects_dir() is True
    assert cfg.values == {"addon_projects_dir": "/scene/root"}


def test_migration_skips_defaults_and_a_set_config(env, monkeypatch):
    cfg = _Config(monkeypatch)
    env.path.write_text(json.dumps({"addon_projects_dir": "~/Mixar Addons"}), encoding="utf-8")
    assert pc.migrate_addon_projects_dir() is False
    assert cfg.values == {"addon_projects_dir": ""}  # the pass is final

    cfg = _Config(monkeypatch, stored="")  # the user cleared the field: never migrate
    env.path.write_text(json.dumps({"addon_projects_dir": "/json/root"}), encoding="utf-8")
    assert pc.migrate_addon_projects_dir() is False
    assert cfg.values == {"addon_projects_dir": ""}



def test_a_first_pass_without_a_value_is_final(env, monkeypatch):
    # Opening someone else's .blend later must not re-point this user's root.
    cfg = _Config(monkeypatch)
    assert pc.migrate_addon_projects_dir() is False
    env.bpy.data.scenes.append(SimpleNamespace(
        session_uid=next(_uid),
        mixar_paint_preferences=_Prefs(idprops={"addon_projects_dir": "/foreign"}),
    ))
    assert pc.migrate_addon_projects_dir() is False
    assert cfg.values == {"addon_projects_dir": ""}


def test_a_failed_write_retries_later(env, monkeypatch):
    cfg = _Config(monkeypatch, writable=False)
    env.path.write_text(json.dumps({"addon_projects_dir": "/json/root"}), encoding="utf-8")
    assert pc.migrate_addon_projects_dir() is False
    cfg.writable = True
    assert pc.migrate_addon_projects_dir() is True
    assert cfg.values == {"addon_projects_dir": "/json/root"}
