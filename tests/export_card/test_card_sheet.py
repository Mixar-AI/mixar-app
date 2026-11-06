# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Export card drawn against a fake uiLayout, with and without the
native sheet API: every target in every state draws, the sidebar has one
tile per target with exactly one lit, and every state keeps the sheet's
one-action contract (exactly ONE active-default button)."""

from types import SimpleNamespace

import pytest

from mixar.modules.export_card import constants as C
from mixar.modules.export_card.core import state, targets
from mixar.modules.export_card.ui.operators import export_card_ui, export_card_web

ENUMS = {
    "gltf_file": ['GLB', 'GLTF'], "usd_file": ['USDZ', 'USDC'],
    "animation": ['ALL', 'NONE'], "texture_format": ['AUTO', 'JPEG', 'WEBP', 'NONE'],
    "fbx_scale": ['FBX_SCALE_NONE', 'FBX_SCALE_UNITS', 'FBX_SCALE_ALL'],
    "smoothing": ['FACE', 'EDGE', 'OFF'], "stl_units": ['MM', 'CM', 'M'],
    "render_format": ['PNG', 'JPEG', 'OPEN_EXR'], "quality": ['DRAFT', 'GOOD', 'FINAL'],
    "renderer": ['EEVEE', 'CYCLES'],
}


class Layout:
    """Records items: what each is, its effective `enabled`, its sheet tags."""

    def __init__(self, log, api, parent=None):
        self._log, self._api, self._parent = log, api, parent
        self.enabled, self.alert, self.alignment = True, False, 'EXPAND'
        self.scale_y = self.ui_units_x = self.ui_units_y = 0.0
        self.use_property_split = self.use_property_decorate = self.activate_init = False

    def _live(self):
        return self.enabled and (self._parent is None or self._parent._live())

    def _sub(self, *_a, **_kw):
        return Layout(self._log, self._api, self)

    row = column = split = box = _sub

    def separator(self, factor=1.0):
        pass

    def label(self, text="", icon='NONE', translate=True):
        self._log.append({"type": "label", "text": text, "enabled": self._live()})

    def operator(self, idname, text="", icon='NONE', translate=True, icon_value=0,
                 emboss=True, depress=False):
        props = SimpleNamespace()
        self._log.append({"type": "op", "op": idname, "text": text, "enabled": self._live(),
                          "props": props, "icon_value": icon_value})
        return props

    def prop(self, data, prop, text="", **_kw):
        self._log.append({"type": "prop", "prop": prop, "enabled": self._live()})

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
        self._log[-1].update(kind=kind, lit=lit)

    def _impl_mixar_sheet_label(self, text="", kind='BODY', lit=False, extra=0.0, translate=True):
        self._log.append({"type": "label", "text": text, "kind": kind, "enabled": self._live()})

    def _impl_mixar_sheet_text_width(self, kind='CHIP', text=""):
        return 4.0 * len(text)

    def _impl_mixar_card_button(self, kind='CARD', active_default=False):
        self._log[-1]["default"] = active_default

    def _impl_template_popup_confirm(self, operator, text="", cancel_text="", translate=True):
        self._log.append({"type": "dismiss", "text": cancel_text, "enabled": self._live()})
        return SimpleNamespace()


class Card(SimpleNamespace):
    """The card's property group: enum items readable like RNA's."""

    @property
    def bl_rna(self):
        return SimpleNamespace(properties={
            name: SimpleNamespace(enum_items=[SimpleNamespace(identifier=v, name=v.title())
                                              for v in values])
            for name, values in ENUMS.items()})


def _card(target, card_state=C.IDLE, **extra):
    values = dict(
        target=target, state=card_state, show_advanced=True, file_name="nook",
        folder="D:/exports", engine='web', scope='SCENE', animation='ALL', gltf_file='GLB',
        usd_file='USDZ', cameras_lights=True, texture_format='AUTO', draco=False,
        apply_modifiers=True, y_up=True, fbx_embed=True, fbx_scale='FBX_SCALE_NONE',
        leaf_bones=False, smoothing='FACE', obj_copy_textures=True, stl_units='MM',
        stl_scale=1.0, stl_ascii=False, project_strip_chat=False, project_compress=True,
        camera='Camera', render_format='PNG', transparent=False, quality='GOOD',
        renderer='EEVEE', width=1920, height=1080, frame_start=1, frame_end=250, fps=24)
    values.update(extra)
    return Card(**values)


def _context(p, published=False):
    web = SimpleNamespace(title="Nook", description="", visibility='public',
                          include_animation=True, is_published=published, revision=2,
                          last_published="today",
                          link="https://mixar.app/s/nook" if published else "")
    scene = SimpleNamespace(name="Scene", mixar_web_publish=web)
    return SimpleNamespace(window_manager=SimpleNamespace(mixar_export_card=p), scene=scene,
                           selected_objects=[object(), object()])


@pytest.fixture(autouse=True)
def quiet_publish(monkeypatch):
    progress = SimpleNamespace(status="IDLE", error="", error_args={}, warning="", progress=0.0)
    fake = SimpleNamespace(busy=False, scene_name="", snapshot=lambda: (progress, None))
    monkeypatch.setattr(export_card_web, "_publish_state", lambda: fake)
    state.clear_result()
    state.clear_readiness()
    yield fake


def _draw(p, api=True, published=False):
    log = []
    export_card_ui.draw_dialog(Layout(log, api), _context(p, published))
    return log


def _defaults(log):
    return [e for e in log if e.get("default")]


STATES = [
    (C.IDLE, {}), (C.RUNNING, {"kind": "running", "name": "nook.glb"}),
    ('CONFIRM', {"kind": "confirm", "name": "nook.glb", "folder": "D:/exports"}),
    (C.DONE, {"kind": "file", "name": "nook.glb", "folder": "D:/exports", "size": 4_200_000,
              "checked": True, "passed": True}),
    (C.DONE, {"kind": "render", "name": "nook.png", "folder": "D:/exports"}),
    (C.ERROR, {"kind": "error", "error": "The export did not finish.", "detail": "Bad mesh"}),
]


@pytest.mark.parametrize("target", [t.id for t in targets.TARGETS if t.id != C.WEB])
@pytest.mark.parametrize("card_state, facts", STATES)
def test_every_state_has_exactly_one_default(target, card_state, facts):
    state.set_result(**facts) if facts else state.clear_result()
    log = _draw(_card(target, card_state))
    assert len(_defaults(log)) == 1, [e for e in log if e["type"] in ("op", "dismiss")]


@pytest.mark.parametrize("published", [False, True])
def test_web_has_exactly_one_default(published):
    log = _draw(_card(C.WEB), published=published)
    assert len(_defaults(log)) == 1
    if published:
        assert any(e.get("op") == "mixar.web_publish_copy_link" for e in log)


def test_web_busy_keeps_one_disabled_default(quiet_publish):
    quiet_publish.busy, quiet_publish.scene_name = True, "Scene"
    log = _draw(_card(C.WEB))
    defaults = _defaults(log)
    assert len(defaults) == 1 and not defaults[0]["enabled"]
    assert any(e.get("op") == "mixar.web_publish_cancel" for e in log)


def test_sidebar_has_one_tile_per_target_one_lit():
    log = _draw(_card(C.FBX))
    tiles = [e for e in log if e.get("kind") == 'TILE']
    assert [e["props"].target for e in tiles] == [t.id for t in targets.TARGETS]
    assert [e["props"].target for e in tiles if e["lit"]] == [C.FBX]


def test_running_locks_the_sidebar_and_the_close():
    log = _draw(_card(C.GLTF, C.RUNNING))
    assert all(not e["enabled"] for e in log if e.get("kind") == 'TILE')
    assert not [e for e in log if e["type"] == "dismiss"]
    busy = _defaults(log)[0]
    assert busy["op"] == C.OP_RUN and not busy["enabled"]


def test_engine_chips_and_advanced_rows_for_gltf():
    log = _draw(_card(C.GLTF))
    engines = [e["props"].engine for e in log if e.get("op") == C.OP_ENGINE]
    assert engines == list(C.ENGINES)
    set_props = {e["props"].prop for e in log if e.get("op") == C.OP_SET}
    assert {"texture_format", "draco", "apply_modifiers", "y_up", "gltf_file"} <= set_props
    hidden = _draw(_card(C.GLTF, show_advanced=False))
    assert "draco" not in {e["props"].prop for e in hidden if e.get("op") == C.OP_SET}


@pytest.mark.parametrize("target", [C.OBJ, C.STL])
def test_formats_without_engine_presets_have_no_engine_chips(target):
    log = _draw(_card(target))
    assert not [e for e in log if e.get("op") == C.OP_ENGINE]


def test_long_lane_warning_wraps_instead_of_clipping():
    state.set_result(kind="file", name="nook.glb", folder="D:/x", size=10,
                     warning="word " * 120)
    log = _draw(_card(C.GLTF, C.DONE))
    lines = [e["text"] for e in log if e.get("kind") == 'NOTE' and "word" in e.get("text", "")]
    assert len(lines) >= 2


def test_selected_scope_disabled_without_a_selection():
    p = _card(C.GLTF)
    log = []
    context = _context(p)
    context.selected_objects = []
    export_card_ui.draw_dialog(Layout(log, True), context)
    selected = [e for e in log if e.get("op") == C.OP_SET and e["props"].value == 'SELECTED']
    assert selected and not selected[0]["enabled"]


def test_jpeg_disables_transparent_background():
    log = _draw(_card(C.IMAGE, render_format='JPEG'))
    transparent = [e for e in log if e.get("op") == C.OP_SET
                   and e["props"].prop == "transparent" and e["props"].value == 'TRUE']
    assert transparent and not transparent[0]["enabled"]


@pytest.mark.parametrize("target", [t.id for t in targets.TARGETS])
def test_stock_widgets_without_the_sheet_api(target):
    """A binary predating the painters still offers every choice."""
    log = _draw(_card(target), api=False)
    assert len([e for e in log if e.get("op") == C.OP_PICK]) == len(targets.TARGETS)


def test_readiness_failures_offer_fix(monkeypatch):
    from mixar.modules.export_card.core import readiness
    p = _card(C.GLTF)
    state.set_readiness(readiness.key(p), {
        "success": True, "ready": False, "mesh_count": 3,
        "checks": {"transforms": {"failed": 2, "failed_meshes": ["Mug", "Shelf"]},
                   "mixar_bakes": {"failed": 0, "failed_meshes": []}}})
    log = _draw(p)
    assert any(e.get("op") == C.OP_FIX for e in log)
    assert any("Mug, Shelf" in e.get("text", "") for e in log)


# ---------------------------------------------------------------------------
# Compact size: a small window / large UI scale never opens the card with its
# primary action off-screen (UX checklist: reachability).
# ---------------------------------------------------------------------------

@pytest.fixture
def compact():
    state.set_compact(True)
    yield
    state.set_compact(False)


@pytest.mark.parametrize("size, scale, expected", [
    ((1680, 1050), 2.25, True), ((1920, 1080), 1.5, False), ((1366, 768), 1.0, False), ((1280, 720), 1.25, True), ((3840, 2160), 2.0, False),
    ((2560, 1440), 1.0, False),
])
def test_choose_compact(size, scale, expected):
    window = SimpleNamespace(width=size[0], height=size[1])
    assert export_card_ui.choose_compact(window, scale) is expected
    assert export_card_ui.choose_compact(None, scale) is False


@pytest.mark.parametrize("target", [t.id for t in targets.TARGETS])
def test_compact_card_fits_the_smallest_window(compact, target):
    """1680 x 1050 at 225 % is 1493 x 933 design px: the whole card (header
    and its taller column) fits, so Export is on screen without scrolling."""
    from mixar.modules.export_card.ui.operators import export_card_foot, export_card_forms
    from mixar.modules.common.sheet import kit as S
    p = _card(target, show_advanced=False)
    layout = Layout([], True)
    context = _context(p)
    side = export_card_ui.sidebar_rows(p).height
    right = (export_card_forms.plan(layout, context, p).height
             + export_card_foot.plan(layout, context, p).height + S.GAP)
    assert export_card_ui.COMPACT.width <= 1493 - 40
    assert S.HEADER + max(side, right) <= 933 - 20, (side, right)


@pytest.mark.parametrize("card_state, facts", STATES)
def test_compact_keeps_one_default(compact, card_state, facts):
    state.set_result(**facts) if facts else state.clear_result()
    log = _draw(_card(C.GLTF, card_state))
    assert len(_defaults(log)) == 1
    frame = [e for e in log if e["type"] == "frame"][0]
    assert frame["sidebar"] == export_card_ui.COMPACT.sidebar
