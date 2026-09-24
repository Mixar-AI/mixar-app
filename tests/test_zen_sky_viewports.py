# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Sky overrides preserve independent viewport preferences and undo history."""

from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from mixar.modules.workflow.core import zen_scene, zen_sky_viewports as sky


class Snapshots(list):
    def get(self, key):
        return next((item for item in self if item.name == key), None)

    def add(self):
        item = NS(name="", use_scene_world=False, use_scene_world_render=False, scene=None)
        self.append(item)
        return item


class Spaces(list):
    @property
    def active(self):
        return self[0]


def viewport(preview, render):
    return NS(type="VIEW_3D", shading=NS(
        use_scene_world=preview, use_scene_world_render=render,
        mixar_zen_sky=NS(key="", applied=False,
                         previous_preview=False, previous_render=False)))


def screen(*spaces):
    result = NS(areas=[NS(type=s.type, spaces=Spaces([s])) for s in spaces],
                mixar_zen_sky_owners=Snapshots())
    for space in spaces:
        space.shading.mixar_zen_sky.id_data = result
    return result


def flags(view):
    return view.shading.use_scene_world, view.shading.use_scene_world_render


@pytest.fixture
def scene():
    return NS(world=object(), mixar_zen_sky=NS(
        sky_world=object(), previous_world=None, viewports=Snapshots()))


def toggle(scene, enabled, screen):
    restart = enabled and not zen_scene.sky_enabled(scene)
    zen_scene.set_sky_enabled(scene, enabled)
    sky.set_sky_viewports(scene, enabled, screen, restart=restart)


@pytest.mark.parametrize("original", [(False, False), (False, True), (True, False), (True, True)])
def test_repeated_on_off_restores_each_flag(monkeypatch, scene, original):
    view = viewport(*original)
    area_screen = screen(view)
    monkeypatch.setattr(sky, "bpy", NS(data=NS(screens=[area_screen])))
    toggle(scene, True, area_screen)
    toggle(scene, True, area_screen)
    assert flags(view) == (True, True)
    assert len(scene.mixar_zen_sky.viewports) == 1
    toggle(scene, False, area_screen)
    assert flags(view) == original
    # Repeated OFF must not override a subsequent manual lighting change.
    view.shading.use_scene_world = not original[0]
    toggle(scene, False, area_screen)
    assert flags(view) == (not original[0], original[1])


def test_off_from_another_screen_restores_owned_inactive_spaces_only(monkeypatch, scene):
    first, second, untouched = viewport(False, True), viewport(True, False), viewport(False, False)
    original_screen, other_screen = screen(first, second), screen(untouched)
    monkeypatch.setattr(sky, "bpy", NS(data=NS(screens=[original_screen, other_screen])))
    toggle(scene, True, original_screen)
    assert flags(first) == flags(second) == (True, True)
    assert flags(untouched) == (False, False)
    original_screen.areas[0].type = "TEXT_EDITOR"
    original_screen.areas[0].spaces.insert(0, NS(type="TEXT_EDITOR"))
    toggle(scene, False, other_screen)
    assert flags(first) == (False, True)
    assert flags(second) == (True, False)
    assert flags(untouched) == (False, False)


def test_undo_redo_uses_the_matching_scene_snapshot_across_cycles(monkeypatch, scene):
    view = viewport(False, True)
    area_screen = screen(view)
    monkeypatch.setattr(sky, "bpy", NS(data=NS(screens=[area_screen])))
    original_world = scene.world
    toggle(scene, True, area_screen)
    first_snapshots = deepcopy(scene.mixar_zen_sky.viewports)
    # Native undo restores the scene but keeps UI data, including applied=True.
    scene.world = original_world
    scene.mixar_zen_sky.viewports.clear()
    sky.sync_sky_viewports()
    assert flags(view) == (False, True)
    scene.world = scene.mixar_zen_sky.sky_world
    scene.mixar_zen_sky.viewports = deepcopy(first_snapshots)
    sky.sync_sky_viewports()
    assert flags(view) == (True, True)
    toggle(scene, False, area_screen)
    view.shading.use_scene_world, view.shading.use_scene_world_render = True, False
    toggle(scene, True, area_screen)
    scene.world = original_world
    # The preceding OFF belongs to the first cycle. UI restoration must use
    # the just-undone override's local copy, not this older scene snapshot.
    scene.mixar_zen_sky.viewports = deepcopy(first_snapshots)
    sky.sync_sky_viewports()
    assert flags(view) == (True, False)
    # Undo back to the first ON, whose prior flags differ from the second ON.
    scene.world = scene.mixar_zen_sky.sky_world
    scene.mixar_zen_sky.viewports = first_snapshots
    sky.sync_sky_viewports()
    assert flags(view) == (True, True)
    scene.world = original_world
    sky.sync_sky_viewports()
    assert flags(view) == (False, True)


def test_new_cycle_captures_current_preferences_and_does_not_reactivate_old_views(monkeypatch, scene):
    old_view, new_view = viewport(False, False), viewport(True, False)
    old_screen, new_screen = screen(old_view), screen(new_view)
    monkeypatch.setattr(sky, "bpy", NS(data=NS(screens=[old_screen, new_screen])))
    toggle(scene, True, old_screen)
    toggle(scene, False, old_screen)
    toggle(scene, True, new_screen)
    sky.sync_sky_viewports()
    assert flags(old_view) == (False, False)
    assert flags(new_view) == (True, True)
    toggle(scene, False, new_screen)
    assert flags(new_view) == (True, False)


def test_external_world_change_keeps_world_but_releases_viewport_override(monkeypatch, scene):
    view = viewport(False, False)
    area_screen = screen(view)
    monkeypatch.setattr(sky, "bpy", NS(data=NS(screens=[area_screen])))
    toggle(scene, True, area_screen)
    external = scene.world = object()
    toggle(scene, False, area_screen)
    assert scene.world is external
    assert flags(view) == (False, False)


def test_unrelated_undo_does_not_reset_manual_flags_while_sky_state_is_unchanged(monkeypatch, scene):
    view = viewport(False, True)
    area_screen = screen(view)
    monkeypatch.setattr(sky, "bpy", NS(data=NS(screens=[area_screen])))
    toggle(scene, True, area_screen)
    view.shading.use_scene_world = False
    sky.sync_sky_viewports()
    assert flags(view) == (False, True)


def test_split_viewports_get_independent_snapshots(monkeypatch, scene):
    first, second = viewport(False, True), viewport(True, False)
    first.shading.mixar_zen_sky.key = second.shading.mixar_zen_sky.key = "copied-key"
    area_screen = screen(first, second)
    monkeypatch.setattr(sky, "bpy", NS(data=NS(screens=[area_screen])))
    toggle(scene, True, area_screen)
    assert first.shading.mixar_zen_sky.key != second.shading.mixar_zen_sky.key
    toggle(scene, False, area_screen)
    assert flags(first) == (False, True)
    assert flags(second) == (True, False)
