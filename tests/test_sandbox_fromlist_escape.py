# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`from pkg import <denied child>` must not hand an agent script the REAL
denied module.

The restricted __import__ used to check only the dotted ``name``. With a
fromlist, the real import loads every listed submodule; the package proxy
then refuses the attribute, and the interpreter's from-import falls back to
``sys.modules["pkg.child"]`` — binding the unwrapped denied module.
"""

import builtins
import types

import pytest

from mixar.modules.space_mixie_chat.core.sandbox_import import make_restricted_import


def _run(source):
    restricted = make_restricted_import({})
    namespace = {"__builtins__": {**vars(builtins), "__import__": restricted}}
    exec(compile(source, "<agent_script>", "exec"), namespace)  # noqa: S102
    return namespace


@pytest.mark.parametrize("source", [
    "from mixar.modules import addon_project",
    "from mixar.modules.addon_project import service",
    "import mixar.modules.addon_project",
])
def test_denied_module_cannot_be_imported_any_way(source):
    with pytest.raises(ImportError):
        _run(source)


def test_fromlist_fallback_never_binds_a_real_denied_module():
    try:
        namespace = _run("from mixar.modules import addon_project as leaked")
    except ImportError:
        return
    leaked = namespace["leaked"]
    # Without the fix this is the real module, with its real builtins.
    assert not (isinstance(leaked, types.ModuleType) and leaked.__name__ == "mixar.modules.addon_project")


def test_allowed_children_still_import():
    namespace = _run("from mixar.modules.space_mixie_chat.core import export_presets\n"
                     "result = export_presets.preset_kwargs('godot', 'glb')['export_apply']")
    assert namespace["result"] is True


def test_restricted_import_refuses_denied_fromlist_children():
    restricted = make_restricted_import({})
    with pytest.raises(ImportError):
        restricted("mixar.modules", {}, {}, ["addon_project"], 0)
    restricted("mixar.modules.space_mixie_chat.core", {}, {}, ["export_presets"], 0)
