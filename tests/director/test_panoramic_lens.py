# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A panoramic camera gets the controls its projection is defined by.

The lens popup offered the projection TYPE and nothing else, so picking
Fisheye Equisolid changed the camera and left no way to set the lens or field
of view that define it — and nothing said the projection only renders in
Cycles.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LENS = (
    ROOT / "src/source/blender/editors/space_view3d/view3d_director_popup_lens.cc"
).read_text(encoding="utf-8")


def _table() -> dict[str, list[str]]:
    body = LENS[LENS.index("const PanoramaFields PANORAMA_FIELDS[] = {") :]
    body = body[: body.index("\n};")]
    table = {}
    for entry in re.finditer(r'\{"([A-Z_]+)",\s*\n?\s*\{(.*?)\}\}', body, re.S):
        fields = [
            part.strip().strip('"')
            for part in entry.group(2).split(",")
            if part.strip() and part.strip() != "nullptr"
        ]
        table[entry.group(1)] = fields
    return table


def test_every_panorama_type_blender_ships_is_in_the_table():
    """A type missing from the table silently draws no controls at all."""
    assert set(_table()) == {
        "EQUIRECTANGULAR",
        "FISHEYE_EQUIDISTANT",
        "FISHEYE_EQUISOLID",
        "FISHEYE_LENS_POLYNOMIAL",
        "MIRRORBALL",
        "EQUIANGULAR_CUBEMAP_FACE",
    }


def test_each_projection_gets_the_controls_it_is_defined_by():
    table = _table()
    assert table["EQUIRECTANGULAR"] == [
        "latitude_min",
        "latitude_max",
        "longitude_min",
        "longitude_max",
    ]
    assert table["FISHEYE_EQUIDISTANT"] == ["fisheye_fov"]
    # Equisolid is a real lens on a real sensor.
    assert table["FISHEYE_EQUISOLID"] == ["fisheye_lens", "fisheye_fov", "sensor_width"]
    assert table["FISHEYE_LENS_POLYNOMIAL"] == [
        "fisheye_fov",
        *[f"fisheye_polynomial_k{index}" for index in range(5)],
    ]


def test_a_projection_with_no_parameters_lists_none():
    """An empty row list is the correct answer, not a gap in the table."""
    table = _table()
    assert table["MIRRORBALL"] == []
    assert table["EQUIANGULAR_CUBEMAP_FACE"] == []


def test_the_table_is_keyed_by_the_rna_identifier_not_a_dna_constant():
    """So it reads the same list the property itself accepts."""
    body = LENS[LENS.index("const char *panorama_type_identifier(") :]
    body = body[: body.index("\n}\n")]
    assert 'RNA_struct_find_property(camera_data_ptr, "panorama_type")' in body
    assert "RNA_property_enum_identifier(" in body
    assert "CAM_PANORAMA" not in LENS


def test_a_property_the_running_blender_lacks_costs_one_row_not_the_popup():
    body = LENS[LENS.index("int panorama_fields(") :]
    body = body[: body.index("\n}\n\n")]
    assert "RNA_struct_find_property(&data->camera_data_ptr, property) == nullptr" in body
    assert "continue;" in body


def test_labels_come_from_the_properties_own_rna_names():
    """Restating them here would drift from Blender on its next rename."""
    body = LENS[LENS.index("int panorama_fields(") :]
    body = body[: body.index("\n}\n\n")]
    assert "ui::ButtonType::NumSlider,\n                                      std::nullopt," in body


def test_the_cycles_only_notice_shows_when_the_engine_is_not_cycles():
    """EEVEE renders a panoramic camera as a plain perspective, so the
    viewport can disagree with the render with nothing saying why."""
    assert 'STREQ(scene->r.engine, "CYCLES")' in LENS
    assert '"Renders in Cycles only"' in LENS
    notice = LENS[LENS.index('!STREQ(scene->r.engine, "CYCLES")') :]
    notice = notice[: notice.index("}")]
    assert "director_popup_section_label" in notice


def test_the_panorama_type_menu_is_still_offered():
    body = LENS[LENS.index("if (data.camera->type == CAM_PANO) {") :]
    body = body[: body.index("director_popup_block_end(block);")]
    assert '"panorama_type"' in body
    assert "ui::ButtonType::Menu" in body
    assert "panorama_fields(block, C, &data, y, width, row_h, gap);" in body


def test_the_ortho_branch_no_longer_doubles_as_the_panoramic_one():
    """It used to bind `ortho_scale` or `panorama_type` through one button,
    which is why the panoramic case had nowhere to put its own rows."""
    assert 'ortho ? "ortho_scale" : "panorama_type"' not in LENS


# -------------------------------------------------------------------------
# One projection's controls at a time.


def test_only_the_live_projections_rows_are_drawn():
    """All three groups used to be on screen together — a focal length, a
    preset ladder and an orthographic scale, with the director left to work
    out which half applied. That was the cost of a popup that cannot re-lay
    itself; closing on a switch pays it properly instead."""
    assert "if (data.camera->type == CAM_PERSP) {" in LENS
    assert "if (data.camera->type == CAM_ORTHO) {" in LENS
    assert "if (data.camera->type == CAM_PANO) {" in LENS
    # No unconditional group blocks left.
    assert "Perspective's rows and Orthographic's are BOTH always drawn" not in LENS


def test_a_projection_switch_dismisses_the_popup():
    """Which is what makes one-group-at-a-time possible: a KEEP_OPEN
    block-button popup cannot re-lay itself, so the rows below the switch
    would otherwise still be the previous projection's."""
    assert "void lens_popup_close(bContext *" in LENS
    assert "ui::popup_menu_retval_set(" in LENS
    body = LENS[LENS.index("for (int index = 0; index < 3; index++)") :]
    body = body[: body.index("\n  y -= gap;")]
    assert "const bool live = data.camera->type == types[index].camera_type;" in body
    assert "if (!live) {" in body
    assert "ui::button_func_set(but, lens_popup_close, block, nullptr);" in body


def test_repicking_the_live_projection_does_not_close():
    """Closing on a no-op reads as the popup misbehaving."""
    body = LENS[LENS.index("for (int index = 0; index < 3; index++)") :]
    body = body[: body.index("\n  y -= gap;")]
    close_at = body.index("button_func_set(but, lens_popup_close")
    assert body.rindex("if (!live) {", 0, close_at) > body.index("const bool live =")


# ---- picking Panoramic shows it: Cycles + Rendered shading -----------------

from types import SimpleNamespace  # noqa: E402

from mixar.modules.director.core import panoramic  # noqa: E402

OPS = (
    ROOT / "src/scripts/mixar/modules/director/ui/operators/camera_surface_ops.py"
).read_text(encoding="utf-8")


class _Render:
    def __init__(self, engine: str, *, cycles_available: bool = True) -> None:
        self._engine = engine
        self._cycles_available = cycles_available

    @property
    def engine(self) -> str:
        return self._engine

    @engine.setter
    def engine(self, value: str) -> None:
        if value == "CYCLES" and not self._cycles_available:
            # What Blender raises for an enum item that is not registered.
            raise TypeError("enum \"CYCLES\" not found in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH')")
        self._engine = value


def _context(engine: str = "BLENDER_EEVEE", *, cycles_available: bool = True):
    shading = SimpleNamespace(type='SOLID')
    space = SimpleNamespace(shading=shading)
    redraws = []
    area = SimpleNamespace(
        type='VIEW_3D',
        regions=[SimpleNamespace(type='WINDOW')],
        spaces=SimpleNamespace(active=space),
        tag_redraw=lambda: redraws.append(True),
    )
    context = SimpleNamespace(
        scene=SimpleNamespace(render=_Render(engine, cycles_available=cycles_available)),
        area=area,
        window=SimpleNamespace(),
    )
    return context, shading, redraws


def test_picking_panoramic_switches_to_cycles_and_rendered_shading():
    context, shading, redraws = _context()
    assert panoramic.show_panoramic_lens(context) == []
    assert context.scene.render.engine == "CYCLES"
    assert shading.type == 'RENDERED'
    assert redraws


def test_without_cycles_the_viewport_is_left_alone_and_the_reason_reported():
    """Rendered shading without Cycles is EEVEE — the plain perspective this
    exists to avoid — so nothing is switched and the operator can say why."""
    context, shading, _redraws = _context(cycles_available=False)
    problems = panoramic.show_panoramic_lens(context)
    assert problems and "Cycles" in problems[0]
    assert context.scene.render.engine == "BLENDER_EEVEE"
    assert shading.type == 'SOLID'


def test_the_lens_operator_switches_only_for_panoramic():
    body = OPS[OPS.index("class MIXAR_OT_director_set_lens_type") :]
    body = body[: body.index("\nclass ")] if "\nclass " in body else body
    assert "if self.lens_type == 'PANO':" in body
    assert "show_panoramic_lens(context)" in body
    assert "self.report({'WARNING'}, problem)" in body
    # After the projection is set, so the switch follows a real change.
    assert body.index("camera.data.type = self.lens_type") < body.index("show_panoramic_lens(")
