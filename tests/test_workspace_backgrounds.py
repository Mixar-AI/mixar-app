# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

from types import SimpleNamespace as NS
from unittest.mock import Mock

from mixar.modules.common.core.theme_backgrounds import apply_forest_backgrounds


def test_background_reset_reaches_inactive_spaces_without_changing_lighting():
    theme = NS(view_3d=NS(space=NS(gradients=NS())), mixie=NS(space=NS()))
    screens = []
    viewports = []
    for mode in ('SOLID', 'MATERIAL', 'RENDERED'):
        shading = NS(type=mode, background_type='WORLD',
                     studiolight_background_alpha=1.0, studiolight_intensity=.7)
        viewports.append(shading)
        screens.append(NS(areas=[NS(
            spaces=[NS(type='MIXIE'), NS(type='VIEW_3D', shading=shading)],
            tag_redraw=Mock())]))
    apply_forest_backgrounds(theme, screens)
    assert theme.view_3d.space.gradients.high_gradient == (15 / 255,) * 3
    assert theme.view_3d.space.gradients.gradient == (15 / 255,) * 3
    assert theme.view_3d.space.gradients.background_type == 'SINGLE_COLOR'
    assert theme.mixie.space.back == (30 / 255,) * 3
    for shading, mode in zip(viewports, ('SOLID', 'MATERIAL', 'RENDERED')):
        assert shading.background_type == 'THEME'
        assert shading.studiolight_background_alpha == 0
        assert shading.type == mode
        assert shading.studiolight_intensity == .7
    for screen in screens:
        screen.areas[0].tag_redraw.assert_called_once()
