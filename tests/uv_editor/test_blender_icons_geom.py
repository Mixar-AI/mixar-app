# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load_icon_geom_module():
    path = ROOT / "src/release/datafiles/blender_icons_geom.py"
    spec = importlib.util.spec_from_file_location("blender_icons_geom", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_non_triangle_face_error_uses_mesh_name():
    module = _load_icon_geom_module()
    mesh = SimpleNamespace(
        name="ToolbarIconMesh",
        loops=[object(), object(), object(), object()],
        vertices=[],
        polygons=[
            SimpleNamespace(
                index=7,
                loop_start=0,
                loop_total=4,
                material_index=0,
            )
        ],
        attributes=SimpleNamespace(active_color=None),
    )

    with pytest.raises(RuntimeError, match="Non-triangle face 7 in ToolbarIconMesh"):
        module.mesh_data_lists_from_mesh(mesh, [])
