# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reference identity must survive stale native buttons and shared datablocks."""
from types import SimpleNamespace as NS

from mixar.modules.agent_bubble.core.references import remove_reference


class Collection(list):
    def remove(self, index):
        del self[index]


def scene():
    shared = NS(name='shared.png')
    other = NS(name='other.png')
    return NS(mixie_moodboard_sidebar=NS(
        tab_image_to_3d=NS(reference_image=shared),
        tab_world_labs=NS(reference_image=shared),
        tab_imagegen=NS(reference_images=Collection([NS(image=other), NS(image=shared)]))),
        mixie_moodboard_images=[NS(image=shared, selected=True), NS(image=other, selected=True)])


def test_stale_upload_button_does_not_clear_replacement_image():
    s = scene()
    assert not remove_reference(s, 'previous.png', 'MODEL_UPLOAD')
    assert s.mixie_moodboard_sidebar.tab_image_to_3d.reference_image.name == 'shared.png'


def test_clear_only_the_owning_pane_without_deleting_shared_image():
    s = scene()
    shared = s.mixie_moodboard_sidebar.tab_world_labs.reference_image
    assert remove_reference(s, shared.name, 'MODEL_UPLOAD')
    assert s.mixie_moodboard_sidebar.tab_image_to_3d.reference_image is None
    assert s.mixie_moodboard_sidebar.tab_world_labs.reference_image is shared
    assert s.mixie_moodboard_images[0].image is shared


def test_media_removal_resolves_identity_after_collection_changes():
    s = scene()
    refs = s.mixie_moodboard_sidebar.tab_imagegen.reference_images
    refs.remove(0)
    assert remove_reference(s, 'shared.png', 'MEDIA_UPLOAD')
    assert not refs
    assert not remove_reference(s, 'shared.png', 'MEDIA_UPLOAD')


def test_board_removal_deselects_only_that_image_and_retains_uploads():
    s = scene()
    assert remove_reference(s, 'shared.png', 'BOARD')
    assert not s.mixie_moodboard_images[0].selected
    assert s.mixie_moodboard_images[1].selected
    assert s.mixie_moodboard_sidebar.tab_world_labs.reference_image.name == 'shared.png'
    assert len(s.mixie_moodboard_sidebar.tab_imagegen.reference_images) == 2
