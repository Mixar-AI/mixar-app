# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Program validation + DSL recording semantics — pure Python, no bpy."""
import pytest

from mixar.modules.procedural_assembly import dsl, mates, spec

GOOD_PROGRAM = """
P.define("hull_len", 1.2)
P.define("peg_d", 0.06)

def strut(part, x):
    part.box(size=(0.05, 0.05, 0.4), at=(x, 0, 0.2))

with asm.part("hull", detail="silhouette") as part:
    part.box(size=(P["hull_len"], 0.5, 0.3), at=(0, 0, 0.15))
    for i in range(2):
        strut(part, -0.4 + i * 0.8)
    part.frame("top_mount", origin=(0, 0, 0.3), z=(0, 0, 1))

with asm.part("turret") as part:
    part.cylinder(d=0.3, h=0.12, at=(0, 0, 0.06), block="armor")
    part.frame("base", origin=(0, 0, 0), z=(0, 0, -1))

asm.mate("turret.base", "hull.top_mount", type="peg_socket",
         d=P["peg_d"], fit="clearance")
"""


def test_good_program_records_parts_and_mates():
    asm = dsl.execute_program(GOOD_PROGRAM, "tank")
    assert [p.name for p in asm.parts] == ["hull", "turret"]
    assert len(asm.parts[0].solids) == 3
    assert asm.parts[1].solids[0]["color_block"] == "armor"
    assert asm.parts[0].frames["top_mount"]["z"] == (0.0, 0.0, 1.0)
    assert len(asm.mates) == 1
    m = asm.mates[0]
    assert (m["new_part"], m["partner"], m["type"]) == ("turret", "hull", "peg_socket")
    assert m["d"] == pytest.approx(0.06)
    assert asm.params.as_dict()["hull_len"] == pytest.approx(1.2)


def test_param_redefinition_is_first_wins():
    src = 'P.define("d", 1.0)\nP.define("d", 9.0)\n' \
          'with asm.part("a") as part:\n    part.box(size=(P["d"], 1, 1))\n'
    asm = dsl.execute_program(src, "x")
    assert asm.parts[0].solids[0]["size"][0] == pytest.approx(1.0)


@pytest.mark.parametrize("source, fragment", [
    ("import os\n", "disallowed construct"),
    ("while True:\n    pass\n", "disallowed construct"),
    ("try:\n    pass\nexcept Exception:\n    pass\n", "disallowed construct"),
    ("open('/etc/passwd')\n", "unknown name 'open'"),
    ("bpy.data.objects\n", "unknown name 'bpy'"),
    ("x = ().__class__\n", "dunder attribute"),
])
def test_validator_rejects_escapes(source, fragment):
    err = spec.validate_program(source)
    assert err is not None and fragment in err


def test_mate_must_reference_earlier_part():
    src = (
        'with asm.part("a") as part:\n'
        "    part.box(size=(1, 1, 1))\n"
        '    part.frame("f", origin=(0, 0, 0), z=(0, 0, 1))\n'
        'with asm.part("b") as part:\n'
        "    part.box(size=(1, 1, 1))\n"
        '    part.frame("f", origin=(0, 0, 0), z=(0, 0, 1))\n'
        'asm.mate("a.f", "b.f", type="seat_face", d=0.5)\n'
    )
    with pytest.raises(dsl.AssemblyError, match="topological order"):
        dsl.execute_program(src, "x")


def test_empty_part_and_duplicate_names_rejected():
    with pytest.raises(dsl.AssemblyError, match="no solids"):
        dsl.execute_program('with asm.part("a") as part:\n    pass\n', "x")
    with pytest.raises(dsl.AssemblyError, match="already defined"):
        dsl.execute_program(
            'with asm.part("a") as part:\n    part.box(size=(1,1,1))\n'
            'with asm.part("a") as part:\n    part.box(size=(1,1,1))\n', "x")


def test_error_carries_program_line():
    src = 'P.define("a", 1.0)\nx = P["missing"]\n'
    with pytest.raises(dsl.AssemblyError, match="line 2"):
        dsl.execute_program(src, "x")


def test_mate_macros_share_the_nominal():
    """Both halves of every static mate derive from the SAME d (rule 1)."""
    d = 0.08
    for mate_type in spec.STATIC_MATE_TYPES:
        male = mates.male_solids(mate_type, d, "clearance")
        female = mates.female_solids(mate_type, d, "clearance")
        if mate_type == "seat_face":
            assert male == [] and female == []
            continue
        assert male, mate_type
        assert female, mate_type
        # clearance opens the female by exactly 2x the per-side offset
        f = mates.fit_offset_m("clearance")
        male_ds = {s.get("d") or s.get("d_outer") for s in male if s.get("d") or s.get("d_outer")}
        female_ds = {s.get("d") or s.get("d_outer") for s in female if s.get("d") or s.get("d_outer")}
        if male_ds and female_ds:
            assert any(
                abs(fd - md - 2 * f) < 1e-9
                for fd in female_ds for md in male_ds
            ), mate_type


def test_kinematic_mates_emit_no_geometry():
    for mate_type in spec.KINEMATIC_MATE_TYPES:
        assert mates.male_solids(mate_type, 0.1, "clearance") == []
        assert mates.female_solids(mate_type, 0.1, "clearance") == []
        assert mates.engagement_depth(mate_type, 0.1) == 0.0
