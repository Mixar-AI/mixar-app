# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BAKING_DIR = ROOT / "src/source/blender/editors/space_baking"


def test_baking_operators_use_image_names_not_id_pointer_properties():
    sources = "\n".join(path.read_text(encoding="utf-8") for path in BAKING_DIR.glob("baking_ops_*.cc"))

    assert "RNA_def_pointer_runtime" not in sources
    assert "RNA_pointer_get(op->ptr" not in sources
    assert sources.count("define_image_name_property(") == 26
    assert sources.count("image_from_operator(C, op,") == 26


def test_python_baking_callers_pass_image_names():
    pixel_ops = (
        ROOT / "src/scripts/mixar/modules/paint/core/element/pixel_operations.py"
    ).read_text(encoding="utf-8")
    embedded_tests = (
        ROOT / "src/scripts/mixar/modules/testing/test_baking_operators.py"
    ).read_text(encoding="utf-8")

    assert "src_image=src.name" in pixel_ops
    assert "dest_image=dest.name" in pixel_ops
    assert "image=image.name" in pixel_ops
    assert "src_image=src_image.name" in embedded_tests
    assert "base_image=base_normal.name" in embedded_tests
    assert "detail_image=detail_normal.name" in embedded_tests
