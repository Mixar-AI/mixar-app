# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Generated World Labs worlds import the SPZ natively, with no Python decoding.

* ``world_labs_queue._download_spz`` writes the downloaded bytes unchanged to
  ``worldlabs_*/<label>.spz`` (the importer names the object after the file);
* the queue no longer references the retired ``world_labs_spz`` converter;
* ``import_world_labs_world`` imports through ``_import_splat_spz`` and the
  default splat rotation is the measured 180 deg X
  (``WORLD_LABS_SPZ_ROT_EULER_DEG``), shared with the local World Labs source.
"""

import ast
import os
import re
import tempfile
from pathlib import Path

_CORE = Path(__file__).resolve().parents[1] / "src/scripts/mixar/modules/moodboard/core"


def _tree(name):
    return ast.parse((_CORE / name).read_text(encoding="utf-8"))


def _function(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _download_spz(downloaded: bytes):
    """Run the real ``_download_spz`` body against a fake download."""
    tree = _tree("world_labs_queue.py")
    module = ast.Module(body=[_function(tree, "_download_spz")], type_ignores=[])
    scope = {"os": os, "re": re, "tempfile": tempfile,
             "_download_bytes": lambda url: downloaded}
    exec(compile(module, "world_labs_queue.py", "exec"), scope)
    return scope["_download_spz"]


def test_download_keeps_spz_bytes_and_a_readable_name():
    payload = b"\x1f\x8bSPZ-as-served"
    path = _download_spz(payload)("https://example.invalid/world.spz", "Cozy Room #2")
    try:
        assert path.endswith(os.sep + "Cozy Room 2.spz")
        assert os.path.basename(os.path.dirname(path)).startswith("worldlabs_")
        assert Path(path).read_bytes() == payload  # no conversion
    finally:
        import shutil
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def test_download_falls_back_to_world_for_an_empty_label():
    path = _download_spz(b"x")("u", "???")
    try:
        assert os.path.basename(path) == "world.spz"
    finally:
        import shutil
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def test_queue_does_not_use_the_retired_converter():
    source = (_CORE / "world_labs_queue.py").read_text(encoding="utf-8")
    assert "world_labs_spz" not in source and "spz_to_ply" not in source
    assert not (_CORE / "world_labs_spz.py").exists()


def test_importer_uses_native_spz_import_and_the_world_labs_rotation():
    tree = _tree("world_labs_importer.py")
    constant = next(
        n for n in tree.body
        if isinstance(n, ast.Assign) and n.targets[0].id == "WORLD_LABS_SPZ_ROT_EULER_DEG"
    )
    assert ast.literal_eval(constant.value) == (180.0, 0.0, 0.0)
    calls = {
        n.func.id for n in ast.walk(_function(tree, "import_world_labs_world"))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_import_splat_spz" in calls and "_import_splat_ply" not in calls
    orient = ast.unparse(_function(tree, "_orient_splats"))
    assert "WORLD_LABS_SPZ_ROT_EULER_DEG" in orient
