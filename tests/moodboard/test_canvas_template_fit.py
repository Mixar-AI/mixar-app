# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Canvas template strip reveals buttons one-by-one as width allows."""

from mixar.modules.moodboard.core.canvas_template_fit import (
    canvas_template_strip_items,
    templates_that_fit,
)


def test_strip_order_is_mesh_then_generation_shortcuts():
    items = canvas_template_strip_items()
    assert items[0][0] == 'MESH_REFERENCE'
    assert [item[0] for item in items[1:4]] == ['IMAGE_GEN', 'MODEL_3D', 'VIDEO_GEN']


def test_only_the_plus_menu_fits_in_a_narrow_strip():
    items = canvas_template_strip_items()
    widths = {item[0]: 100 for item in items}
    assert templates_that_fit(32, items, widths=widths, more_width=32, gap=4) == []
    assert templates_that_fit(0, items, widths=widths, more_width=32, gap=4) == []


def test_buttons_appear_progressively_as_width_grows():
    items = canvas_template_strip_items()
    widths = {item[0]: 100 for item in items}
    widths[items[1][0]] = 150
    fit = lambda available: templates_that_fit(
        available, items, widths=widths, more_width=32, gap=4,
    )
    assert fit(135) == []  # 100 + 4 + 32: the gap before + is reserved.
    assert fit(136) == list(items[:1])
    assert fit(289) == list(items[:1])
    assert fit(290) == list(items[:2])


def test_fitting_uses_measured_labels_and_scales_all_geometry_together():
    items = canvas_template_strip_items()
    widths = {item[0]: 100 for item in items}
    for scale in (1, 1.25, 1.5, 2):
        scaled = {key: value * scale for key, value in widths.items()}
        assert templates_that_fit(
            239 * scale, items, widths=scaled, more_width=32 * scale, gap=4 * scale,
        ) == list(items[:1])
        assert templates_that_fit(
            240 * scale, items, widths=scaled, more_width=32 * scale, gap=4 * scale,
        ) == list(items[:2])


def test_chrome_draw_no_longer_switches_coarse_panels():
    from pathlib import Path

    chrome = (Path(__file__).resolve().parents[2]
              / "src/source/blender/editors/space_mixie/mixie_draw_moodboard_chrome.cc")
    source = chrome.read_text(encoding="utf-8")
    assert "MIXIE_PT_canvas_templates_compact" not in source
    assert "MIXIE_PT_canvas_templates_icon" not in source
    assert "740 * UI_SCALE_FAC" not in source
    assert 'draw_panel(C, region, "MIXIE_PT_canvas_templates"' in source
