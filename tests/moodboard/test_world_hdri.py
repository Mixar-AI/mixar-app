# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Apply-as-world HDRI helpers refuse movies and skip unselected items."""

from types import SimpleNamespace

from mixar.modules.moodboard.core.world_hdri import selected_still_image


class _Ctx:
    def __init__(self, images):
        self.scene = SimpleNamespace(mixie_moodboard_images=images)


def test_selected_still_image_skips_movies_and_unselected():
    movie = SimpleNamespace(source="MOVIE", name="clip")
    still = SimpleNamespace(source="FILE", name="pano")
    images = [
        SimpleNamespace(selected=True, image=movie),
        SimpleNamespace(selected=False, image=still),
        SimpleNamespace(selected=True, image=still),
    ]
    assert selected_still_image(_Ctx(images)) is still


def test_selected_still_image_empty():
    assert selected_still_image(_Ctx([])) is None
    assert selected_still_image(SimpleNamespace(scene=None)) is None
