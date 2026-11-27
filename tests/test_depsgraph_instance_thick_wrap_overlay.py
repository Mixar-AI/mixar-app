# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins `src/source/blender/makesrna/intern/rna_depsgraph.cc`: upstream's file plus
one comment block fenced by `/* MIXAR-2146 begin */ ... /* MIXAR-2146 end */` and
lines tagged `/* MIXAR-2146 */`.

Every `DepsgraphObjectInstance` that `depsgraph.object_instances` yields is the
iterator itself, so its array properties were live views of the iterator.
A `inst.matrix_world` kept past the loop read freed memory, and the app crashed in
`DepsgraphObjectInstance_matrix_world_get` (mixar-backend#2146, an agent script
reading `.translation.x`); kept during the loop, every matrix showed the current
instance instead of its own. The overlay thick-wraps the per-instance arrays
(`persistent_id`, `matrix_world`, `orco`, `uv`): Python gets a copy at access, as
upstream already does for `Bone.matrix_local`-style "no reference" properties.
Replayed in the app: the unfixed build crashes; the fixed one returns each
instance's own matrix."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/source/blender/makesrna/intern/rna_depsgraph.cc"
UPSTREAM_CANDIDATES = (
    ROOT / "upstream/source/blender/makesrna/intern/rna_depsgraph.cc",
    ROOT.parents[1] / "upstream/source/blender/makesrna/intern/rna_depsgraph.cc",
)
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
MARKED = re.compile(r"[ \t]*/\* MIXAR-2146 begin \*/\n.*?[ \t]*/\* MIXAR-2146 end \*/\n", re.S)
TAGGED = re.compile(r"^[^\n]*/\* MIXAR-2146 \*/\n", re.M)
WRAPPED = ("persistent_id", "matrix_world", "orco", "uv")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _instance_struct(text: str) -> str:
    start = text.index("static void rna_def_depsgraph_instance(BlenderRNA *brna)\n{")
    return text[start : text.index("\n}\n", start)]


def _property_block(body: str, name: str) -> str:
    start = body.index(f'prop = RNA_def_property(srna, "{name}"')
    nxt = body.find("prop = RNA_def_property(srna,", start + 1)
    return body[start : nxt if nxt != -1 else len(body)]


@pytest.mark.parametrize("name", WRAPPED)
def test_each_per_instance_array_is_thick_wrapped(name):
    block = _property_block(_instance_struct(_read(OVERLAY)), name)
    assert "RNA_def_property_flag(prop, PROP_THICK_WRAP); /* MIXAR-2146 */" in block


def test_pointer_and_scalar_properties_are_left_alone():
    body = _instance_struct(_read(OVERLAY))
    assert body.count("PROP_THICK_WRAP") == len(WRAPPED)


def test_the_overlay_is_upstream_plus_the_marked_lines():
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        pytest.skip("no upstream checkout")
    up = _read(upstream)
    if "PROP_THICK_WRAP" in _instance_struct(up):
        pytest.fail("the pin thick-wraps instance properties: delete the rna_depsgraph.cc overlay "
                    "(mixar-backend#2146)")
    ov = _read(OVERLAY)
    assert MIXAR_SPDX in ov
    assert TAGGED.sub("", MARKED.sub("", ov.replace(MIXAR_SPDX, "", 1))) == up
