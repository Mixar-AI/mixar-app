# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Export sheet (`mixar.export_menu`): the Zen toolbar opens it, every format
keeps the one-action contract, the runner maps choices to files, and the
native blur behind it is held by the pop-up and drawn under the menus.

The sheet is drawn against a fake uiLayout with and without the native
sheet API (a binary predating the painters gets stock widgets)."""

from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from mixar.modules.export_menu import constants as C
from mixar.modules.export_menu.core import runner
from mixar.modules.export_menu.ui.operators import export_menu_sheet as sheet

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
WM = SRC / "source" / "blender" / "windowmanager"


class Layout:
    """Records every item; ``sheet_api`` False models an older binary."""

    def __init__(self, log, sheet_api, parent=None):
        self._log, self._api, self._parent = log, sheet_api, parent
        self.enabled = True
        self.alert = False
        self.activate_init = False
        self.alignment = 'EXPAND'
        self.scale_y = self.ui_units_x = self.ui_units_y = 0.0
        self.use_property_split = self.use_property_decorate = False

    def _live(self):
        return self.enabled and (self._parent is None or self._parent._live())

    def _sub(self, *_a, **_kw):
        return Layout(self._log, self._api, self)

    row = column = split = box = _sub

    def separator(self, factor=1.0):
        pass

    def label(self, text="", icon='NONE', translate=True):
        self._log.append({"type": "label", "text": text, "enabled": self._live()})

    def prop(self, data, name, text=None, **_kw):
        self._log.append({"type": "prop", "prop": name, "enabled": self._live()})

    def operator(self, idname, text="", icon='NONE', translate=True, emboss=True, icon_value=0):
        props = NS()
        self._log.append({"type": "op", "op": idname, "text": text, "icon": icon,
                          "icon_value": icon_value, "enabled": self._live(), "props": props})
        return props

    def __getattr__(self, name):
        if name in ('mixar_sheet_frame', 'mixar_sheet', 'mixar_sheet_label',
                    'mixar_sheet_text_width', 'mixar_card_button', 'template_popup_confirm'):
            if not self.__dict__['_api']:
                raise AttributeError(name)
            return getattr(self, "_impl_" + name)
        raise AttributeError(name)

    def _impl_mixar_sheet_frame(self, header=0.0, sidebar=0.0):
        self._log.append({"type": "frame", "sidebar": sidebar})

    def _impl_mixar_sheet(self, kind, lit=False, extra=0.0):
        self._log[-1].update(kind=kind, lit=lit, extra=extra)

    def _impl_mixar_sheet_label(self, text="", kind='BODY', lit=False, extra=0.0, translate=True):
        self._log.append({"type": "label", "text": text, "kind": kind, "enabled": self._live()})

    def _impl_mixar_sheet_text_width(self, kind='CHIP', text=""):
        return 4.0 * len(text)

    def _impl_mixar_card_button(self, kind='CARD', active_default=False):
        self._log[-1]["default"] = active_default

    def _impl_template_popup_confirm(self, operator, text="", cancel_text="", translate=True):
        props = NS()
        self._log.append({"type": "confirm" if operator else "dismiss", "op": operator,
                          "text": text or cancel_text, "enabled": self._live(), "props": props})
        return props


def _props(**kw):
    values = dict(format="GLB", file_name="Scooter", quality="GOOD", gltf_variant="GLB",
                  engine_format="FBX", image_format="PNG", video_format="MP4",
                  selected_only=False, strip_chat=True, include_animation=True)
    values.update(kw)
    return NS(**values)


def _context(props, camera=True, meshes=True, selected=(), web=None):
    render = NS(resolution_x=1920, resolution_y=1080, resolution_percentage=100, fps=24,
                fps_base=1.0)
    scene = NS(name="Scene", camera=object() if camera else None, frame_start=1, frame_end=48,
               render=render, objects=[NS(type='MESH' if meshes else 'EMPTY')],
               mixar_web_publish=web)
    return NS(window_manager=NS(mixar_export_menu=props), scene=scene,
              selected_objects=list(selected))


@pytest.fixture(autouse=True)
def _downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "output_folder", lambda: str(tmp_path))
    # The render coordinator's thread check has no Blender here.
    import mixar.modules.common.render_coordinator.core as slot
    monkeypatch.setattr(slot, "busy", lambda: False)


def _draw(props, sheet_api=True, **ctx):
    log = []
    sheet.draw_sheet(Layout(log, sheet_api), _context(props, **ctx), lambda _key: 0)
    return log


def _defaults(log):
    return [item for item in log if item.get("default")]


@pytest.mark.parametrize("key", [fmt.key for fmt in C.FORMATS if fmt.kind != C.KIND_WEB])
def test_every_export_format_has_one_tile_lit_and_one_default_confirm(key):
    log = _draw(_props(format=key))
    tiles = [item for item in log if item.get("kind") == sheet.TILE_KIND]
    assert [tile["props"].format for tile in tiles] == [fmt.key for fmt in C.FORMATS]
    assert [tile["props"].format for tile in tiles if tile["lit"]] == [key]
    (default,) = _defaults(log)
    assert default["type"] == "confirm" and default["op"] == sheet.OP_RUN
    assert default["enabled"]
    # The ✕ is a cancel-path dismiss, never a second default.
    assert any(item["type"] == "dismiss" for item in log)


def test_the_sheet_is_framed_with_its_wide_sidebar():
    assert {"type": "frame", "sidebar": sheet.SIDEBAR} in _draw(_props())


@pytest.mark.parametrize("key, ctx, kind", [
    ("PNG", {"camera": False}, "DANGER_TEXT"),
    ("MP4", {"camera": False}, "DANGER_TEXT"),
    ("FBX", {"meshes": False}, "DANGER_TEXT"),
])
def test_a_blocked_export_says_why_and_disables_export(key, ctx, kind):
    log = _draw(_props(format=key), **ctx)
    (default,) = _defaults(log)
    assert not default["enabled"]
    assert any(item.get("kind") == kind for item in log)


def test_selected_only_needs_a_selection():
    props = _props(format="OBJ", selected_only=True)
    assert runner.blocker(props, _context(props))
    assert not runner.blocker(props, _context(props, selected=[object()]))


def test_quality_chips_only_apply_to_renders():
    def quality_enabled(key):
        chips = [item for item in _draw(_props(format=key))
                 if item.get("kind") == "CHIP" and getattr(item["props"], "name", "") == "quality"]
        assert len(chips) == len(C.QUALITY_ITEMS)
        return {chip["enabled"] for chip in chips}
    assert quality_enabled("PNG") == {True}
    assert quality_enabled("GLB") == {False}


def test_web_without_publishing_support_keeps_one_disabled_default():
    log = _draw(_props(format="WEB"))
    (default,) = _defaults(log)
    assert default["op"] == sheet.OP_PUBLISH and not default["enabled"]


@pytest.mark.parametrize("key", [fmt.key for fmt in C.FORMATS])
def test_an_older_binary_still_draws_every_format(key):
    log = _draw(_props(format=key), sheet_api=False)
    assert any(item["type"] == "op" and item["op"] == sheet.OP_PICK for item in log)


@pytest.mark.parametrize("props, expected", [
    (dict(format="GLB"), ".glb"),
    (dict(format="GLB", gltf_variant="GLTF"), ".gltf"),
    (dict(format="UNREAL"), ".fbx"),
    (dict(format="UNITY", engine_format="GLB"), ".glb"),
    (dict(format="PNG", image_format="WEBP"), ".webp"),
    (dict(format="MP4", video_format="WEBM"), ".webm"),
    (dict(format="MIXAR"), ".mixar"),
    (dict(format="BLEND"), ".blend"),
])
def test_each_choice_writes_its_extension(props, expected):
    assert runner.extension(_props(**props)) == expected


def test_exports_never_overwrite(tmp_path):
    (tmp_path / "Scooter.glb").write_bytes(b"x")
    assert runner.unique_path(str(tmp_path), "Scooter", ".glb").endswith("Scooter_2.glb")


def test_render_quality_scales_to_even_sizes():
    props = _props(format="MP4", quality="FAST")
    options = runner.render_options(props, _context(props), C.KIND_VIDEO)
    assert (options["width"], options["height"], options["engine"]) == (960, 540, "eevee")
    awesome = runner.render_options(_props(format="PNG", quality="AWESOME"),
                                    _context(props), C.KIND_IMAGE)
    assert (awesome["engine"], awesome["samples"]) == ("cycles", 256)


def test_the_zen_export_button_opens_the_sheet_and_file_export_is_untouched():
    controls = (SRC / "scripts/mixar/modules/workflow/ui/headers/zen_scene_controls.py").read_text()
    assert 'export.operator("mixar.export_menu", text="Export", icon="EXPORT")' in controls
    topbar = (SRC / "scripts/startup/bl_ui/space_topbar.py").read_text()
    assert 'props.name = "MIXAR_PT_web_publish"' in topbar  # File ▸ Export keeps Publish to Web
    ops = (SRC / "scripts/mixar/modules/export_menu/ui/operators/export_menu_ops.py").read_text()
    assert '{"sheet": True, "blur": True}' in ops


def test_the_blur_is_held_by_the_popup_and_drawn_under_the_menus():
    operators = (WM / "intern/wm_operators.cc").read_text()
    assert "Mixar_backdrop_blur_hold(win_dialog, data);" in operators
    assert "Mixar_backdrop_blur_release(this);" in operators  # every close path frees `data`
    draw = (WM / "intern/wm_draw.cc").read_text()
    begin = draw.index("wm_draw_mixar_backdrop_begin(win, view)")
    assert begin < draw.index("wm_draw_mixar_backdrop_end(win, backdrop)") < draw.index(
        "/* Blend in floating regions (menus). */")
    assert "if (backdrop != MixarBackdropPass::Cached) {" in draw
    window = (WM / "intern/wm_window.cc").read_text()
    assert "wm_draw_mixar_backdrop_free(win);" in window
    rna = (SRC / "source/blender/makesrna/intern/rna_wm_mixar_popup.cc").read_text()
    assert '"blur",' in rna
    backdrop = (WM / "intern/wm_draw_mixar_backdrop.cc").read_text()
    # The blur chain is rebuilt in the drawing window's context, then dropped.
    assert backdrop.count("ui::mixar_glass_free();") == 2
