# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Export card's right column above the foot: the target's caption, its
settings and (3D) the "Made for" engine chips, Advanced settings and the
readiness block.

A setting is a row: its name on the left (``Metrics.label_w``) and its control on
the right — segmented chips (`mixar.export_card_set`), a dropdown or a
number field. Bools are two chips with their own words ("Include" / "Leave
out"). Everything is planned as `export_card_ui.Rows` (heights first)."""

from mixar.modules.common.i18n import iface_, n_
from mixar.modules.common.sheet import kit as S
from mixar.modules.common.sheet import tiles as T

from ... import constants as C
from ...core import logos, readiness, state, targets
from . import export_card_web
from .export_card_ui import Rows, metrics

NUM_W = 150
DROPDOWN_W = 420
YES_NO = ((True, n_("Yes")), (False, n_("No")))
ON_OFF = ((False, n_("Off")), (True, n_("On")))
INCLUDE = ((True, n_("Include")), (False, n_("Leave out")))


def plan(layout, context, p):
    rows = Rows()
    target = targets.get(p.target)
    rows.gap(S.CAPTION_TOP)
    rows.add(S.CAPTION_H, lambda col: S.caption(
        col, S.bright(iface_(target.title).upper()), S.RIGHT_INSET, translate=False))
    for line in S.wrap(layout, S.NOTE, iface_(target.subtitle), metrics().text_w) or [""]:
        rows.add(S.NOTE_H, lambda col, line=line: S.label(
            S.row(col, S.NOTE_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN), line, S.NOTE,
            translate=False))
    rows.gap(S.CAPTION_TO_CHIPS)
    if p.target in C.MODEL_TARGETS:
        _model(rows, layout, context, p)
    elif p.target in C.PROJECT_TARGETS:
        _setting(rows, n_("Agent chat"), _chips(p, "project_strip_chat",
                 ((False, n_("Keep")), (True, n_("Remove from the copy")))))
        _setting(rows, n_("Compress"), _chips(p, "project_compress", YES_NO))
    elif p.target in C.RENDER_TARGETS:
        _render(rows, context, p)
    else:
        export_card_web.form(rows, layout, context, p, _setting, _chips)
    return rows


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _setting(rows, label, control, height=None):
    """``label`` (a msgid) on the left, ``control(line)`` after it."""
    height = height or metrics().set_h
    def draw(col):
        line = S.row(col, height, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
        S.label(S.sized(line, metrics().label_w), label, S.BODY)
        control(line)
    rows.add(height, draw)
    rows.gap(metrics().row_gap)


def _chips(owner, prop, choices=None, prefix="", disabled=()):
    """Segmented chips for ``owner.prop``. ``choices`` = ``(value, msgid)``;
    without it the enum's own items are used. ``prefix`` routes the write
    (``web.`` → the scene's publish settings)."""
    def control(line):
        inner = line.row(align=True)
        inner.alignment = 'LEFT'
        current = getattr(owner, prop)
        if choices is None:
            items = [(item.identifier, item.name)
                     for item in owner.bl_rna.properties[prop].enum_items]
        else:
            items = choices
        for value, label in items:
            text = iface_(label)
            slot = S.sized(inner, T.chip_width(inner, text))
            slot.enabled = value not in disabled
            stored = ('TRUE' if value else 'FALSE') if isinstance(value, bool) else value
            S.choice(slot, C.OP_SET, text, S.CHIP, lit=(current == value),
                     prop=prefix + prop, value=stored)
    return control


def _numbers(owner, props, between=""):
    """Number fields in a row (``between`` drawn between them, e.g. "×")."""
    def control(line):
        inner = line.row(align=True)
        inner.alignment = 'LEFT'
        for index, prop in enumerate(props):
            if index and between:
                S.label(S.sized(inner, 40), between, S.BODY, translate=False)
            slot = S.sized(inner, NUM_W)
            slot.prop(owner, prop, text="")
    return control


def _dropdown(owner, prop):
    def control(line):
        S.dropdown(S.sized(line, DROPDOWN_W), owner, prop)
    return control


# ---------------------------------------------------------------------------
# 3D model
# ---------------------------------------------------------------------------

def _model(rows, layout, context, p):
    # OBJ and STL have no engine presets (export_presets.PRESETS): chips
    # there would change nothing.
    if p.target not in (C.OBJ, C.STL):
        _engines(rows, layout, p)
    selected = len(getattr(context, "selected_objects", ()) or ())
    _setting(rows, n_("What to export"), _chips(p, "scope", (
        ('SCENE', n_("Whole scene")),
        ('SELECTED', iface_("Selected ({count})").format(count=selected))),
        disabled=() if selected else ('SELECTED',)))
    advanced = []
    if p.target == C.GLTF:
        _setting(rows, n_("File"), _chips(p, "gltf_file"))
        _setting(rows, n_("Animation"), _chips(p, "animation"))
        _setting(rows, n_("Cameras and lights"), _chips(p, "cameras_lights", INCLUDE))
        advanced = [(n_("Textures"), _chips(p, "texture_format")),
                    (n_("Draco compression"), _chips(p, "draco", ON_OFF)),
                    (n_("Apply modifiers"), _chips(p, "apply_modifiers", YES_NO)),
                    (n_("Up axis"), _chips(p, "y_up", ((True, n_("Y up")), (False, n_("Z up")))))]
    elif p.target == C.FBX:
        _setting(rows, n_("Animation"), _chips(p, "animation"))
        _setting(rows, n_("Textures"), _chips(p, "fbx_embed", (
            (True, n_("Embed in the file")), (False, n_("Copy beside it")))))
        advanced = [(n_("Scale"), _chips(p, "fbx_scale")),
                    (n_("Leaf bones"), _chips(p, "leaf_bones", ON_OFF)),
                    (n_("Smoothing"), _chips(p, "smoothing")),
                    (n_("Apply modifiers"), _chips(p, "apply_modifiers", YES_NO))]
    elif p.target == C.USD:
        _setting(rows, n_("File"), _chips(p, "usd_file"))
        _setting(rows, n_("Animation"), _chips(p, "animation"))
        advanced = [(n_("Up axis"), _chips(p, "y_up", ((True, n_("Y up")), (False, n_("Z up"))))),
                    (n_("Cameras and lights"), _chips(p, "cameras_lights", INCLUDE))]
    elif p.target == C.OBJ:
        _setting(rows, n_("Textures"), _chips(p, "obj_copy_textures", (
            (True, n_("Copy beside it")), (False, n_("Keep original paths")))))
        _setting(rows, n_("Apply modifiers"), _chips(p, "apply_modifiers", YES_NO))
    else:
        _setting(rows, n_("Units"), _chips(p, "stl_units"))
        _setting(rows, n_("Scale"), _numbers(p, ("stl_scale",)))
        _setting(rows, n_("Encoding"), _chips(p, "stl_ascii", (
            (False, n_("Binary")), (True, n_("ASCII")))))
    if advanced:
        _advanced(rows, p, advanced)
    _readiness(rows, layout, p)


def _engines(rows, layout, p):
    rows.add(S.NOTE_H, lambda col: S.label(
        S.row(col, S.NOTE_H, left=S.RIGHT_INSET), n_("Made for"), S.BODY))
    rows.gap(8)
    items = [(C.OP_ENGINE, iface_(label) if key == 'other' else label, key == p.engine,
              logos.icon_id(logo), {"engine": key}) for key, label, logo in targets.ENGINE_CHIPS]
    rows.add(S.CHIP_H, lambda col: T.chip_line(col, items, S.RIGHT_INSET, S.RIGHT_MARGIN))
    rows.gap(metrics().row_gap + 6)


def _advanced(rows, p, advanced):
    text = iface_("Hide advanced settings") if p.show_advanced else \
        iface_("Advanced settings")

    def draw(col):
        line = S.row(col, S.CHIP_H, left=S.RIGHT_INSET, packed=True)
        S.button(S.sized(line, S.text_width(line, S.SECONDARY, text) + S.BUTTON_PAD),
                 C.OP_ADVANCED, text, S.SECONDARY)
    rows.add(S.CHIP_H, draw)
    rows.gap(metrics().row_gap)
    if p.show_advanced:
        for label, control in advanced:
            _setting(rows, label, control)


def _readiness(rows, layout, p):
    report = state.readiness(readiness.key(p))
    failures = readiness.failures(report) if report else []
    if report is None:
        dot, text, op, pill = (S.STATUS_DIM, iface_("Check the meshes before you export."),
                               C.OP_CHECK, iface_("Check"))
    elif not report.get("success", True) or report.get("error"):
        dot, text, op, pill = (S.STATUS_DANGER, str(report.get("error") or ""), C.OP_CHECK,
                               iface_("Check again"))
    elif failures:
        dot, text, op, pill = (S.STATUS_DANGER,
                               iface_("{count} things to fix before export").format(
                                   count=len(failures)), C.OP_FIX, iface_("Fix in scene"))
    else:
        dot, text, op, pill = (S.STATUS_ON, iface_("Ready: {count} meshes pass every check.").format(
            count=int(report.get("mesh_count") or 0)), C.OP_CHECK, iface_("Check again"))
    rows.gap(metrics().row_gap)

    def strip(col):
        line = S.row(col, S.STRIP_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN)
        S.status_dot(line, dot)
        S.label(line, text, S.DANGER_TEXT if dot == S.STATUS_DANGER else S.BODY,
                translate=False)
        S.gap(line, S.GAP)
        S.button(S.sized(line, S.text_width(line, S.SECONDARY, pill) + S.BUTTON_PAD),
                 op, pill, S.SECONDARY)
    rows.add(S.STRIP_H, strip)
    for label, count, names in failures:
        more = count - len(names)
        detail = ", ".join(names) + (iface_(" and {count} more").format(count=more) if more > 0 else "")
        line_text = iface_("{problem}: {meshes}").format(problem=iface_(label), meshes=detail)
        rows.add(S.NOTE_H, lambda col, t=line_text: S.label(
            S.row(col, S.NOTE_H, left=S.PROMPT_INSET + S.STATUS_DOT + S.STATUS_GAP,
                  right=S.RIGHT_MARGIN), t, S.NOTE, translate=False))


# ---------------------------------------------------------------------------
# Image / Video
# ---------------------------------------------------------------------------

def _render(rows, context, p):
    _setting(rows, n_("Camera"), _dropdown(p, "camera"))
    _setting(rows, n_("Size"), _numbers(p, ("width", "height"), "×"))
    if p.target == C.IMAGE:
        _setting(rows, n_("Format"), _chips(p, "render_format"))
        _setting(rows, n_("Background"), _chips(p, "transparent", (
            (False, n_("Scene")), (True, n_("Transparent"))),
            disabled=(True,) if p.render_format == 'JPEG' else ()))
    else:
        _setting(rows, n_("Frames"), _numbers(p, ("frame_start", "frame_end"), "–"))
        _setting(rows, n_("Frame rate"), _numbers(p, ("fps",)))
    _setting(rows, n_("Quality"), _chips(p, "quality"))
    _setting(rows, n_("Renderer"), _chips(p, "renderer"))
    note = (n_("Saved as an MP4 (H.264) video. It renders in the background while you work.")
            if p.target == C.VIDEO else
            n_("It renders in the background while you work; a notification says when it is saved."))
    rows.add(S.NOTE_H, lambda col: S.label(
        S.row(col, S.NOTE_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN), note, S.NOTE))


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
