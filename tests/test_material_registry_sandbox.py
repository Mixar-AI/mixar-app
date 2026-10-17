# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Material-registry exec sandbox: server-fetched material code is untrusted.

Bundled MatGen-style scripts must keep loading (side effects observable on
the stubbed bpy), while escape vectors — class-hierarchy introspection,
runtime dunder getattr, open/os/runpy/subprocess, bpy.ops.script.* — must
be rejected before they can reach real builtins.
"""

import os
import sys

# The runtime `mixar` package is synthesized by Blender's bootstrap; for
# pytest, src/scripts on sys.path + PEP 420 namespace packages give the same
# import surface (bpy is stubbed by the root conftest). Embedded-Python
# third-party deps pulled in by package __init__ chains are stubbed the same
# way the root conftest stubs bpy.
_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

from unittest.mock import MagicMock  # noqa: E402

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk",
             "mathutils", "bmesh", "imbuf"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.paint.procedural_materials import material_registry as mr  # noqa: E402

# Assert on mr.bpy — the exact object the exec path binds — not a fresh
# `import bpy`: other test modules replace sys.modules["bpy"] during
# collection (mock_bpy installs over the conftest stub), which would make a
# re-imported name a different mock than the one the script executed against.
_BPY = mr.bpy


def _material(script):
    return mr.ProceduralMaterial(
        material_id="sandbox-test", name="Sandbox Test",
        category="test", script=script,
    )


def _execute(script):
    return mr.MaterialRegistry()._execute_material_script(_material(script))


def test_bundled_style_script_still_executes():
    # A generator-style script (import bpy + data-API calls) must run through
    # the hardened namespace unchanged.
    result = _execute(
        "import bpy\n"
        "mat = bpy.data.materials.new(name='Sandbox Test Mat')\n"
        "sock = getattr(mat, 'name')\n"
    )
    # No real node groups exist under the stubbed bpy, so the registry returns
    # None — but the script must HAVE RUN (side effect observable).
    assert _BPY.data.materials.new.called
    assert result is None


def test_class_hierarchy_introspection_is_blocked():
    # object.__subclasses__() walks the class hierarchy to real builtins/os.
    result = _execute(
        "import bpy\n"
        "object.__subclasses__()\n"
        "bpy.data.materials.new(name='BOOM')\n"
    )
    # Blocked before exec: the marker call must never happen.
    assert not _called_with_name(_BPY.data.materials.new, "BOOM")
    assert result is None


def test_runtime_dunder_getattr_is_blocked():
    # Computed attribute names bypass the AST scan; the wrapped getattr from
    # the chat sandbox blocks them at runtime.
    result = _execute(
        "import bpy\n"
        "getattr(object, '__sub' + 'classes__')\n"
        "bpy.data.materials.new(name='BOOM')\n"
    )
    assert not _called_with_name(_BPY.data.materials.new, "BOOM")
    assert result is None


def test_dangerous_names_are_absent_from_namespace():
    for prologue in (
        "open('/tmp/evil.py', 'w')\n",
        "import os\n",
        "import subprocess\n",
        "import runpy\n",
    ):
        result = _execute(
            prologue
            + "import bpy\n"
            + "bpy.data.materials.new(name='BOOM')\n"
        )
        assert not _called_with_name(_BPY.data.materials.new, "BOOM"), prologue
        assert result is None


def test_bpy_ops_script_is_denied():
    # script.python_file_run executes files with REAL builtins — the ops
    # proxy must deny the namespace here too (server code, no AST around ops).
    result = _execute(
        "import bpy\n"
        "bpy.ops.script.python_file_run(filepath='/tmp/evil.py')\n"
        "bpy.data.materials.new(name='BOOM')\n"
    )
    assert not _called_with_name(_BPY.data.materials.new, "BOOM")
    assert result is None


def _called_with_name(mock_new, name):
    """Whether materials.new(...) was called with the given name kwarg."""
    return any(
        call.kwargs.get("name") == name or (call.args and call.args[0] == name)
        for call in mock_new.call_args_list
    )
