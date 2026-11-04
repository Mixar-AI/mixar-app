# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Connect engine — the sheet `mixar.engine_connect` opens.

The same native sheet as AI Provider settings and Connect MCP
(`common/sheet/kit`): title and subtitle over the header divider, then

  sidebar        ENGINES: a row per engine led by its logo
                 (`core/engine_logos`); CONNECTED: the live editors
  right column   PROJECT: New / Existing chips; quiet field labels over the
                 fields (name + location, or the project folder), each folder
                 field with a Browse pill docked inside; the check line (where
                 the project goes, or why it cannot: a Godot and an Unreal game
                 never share a folder, `core/engine_projects`)
  foot           one line on what Connect changes, then the engine's status
                 (found / will download / missing) beside Connect

The sidebar row already names the engine, so the right column does not
repeat it; the status sits by the action it gates. Connect is a confirm
button: it closes the sheet and runs `mixar.engine_connect_start`, and the
engine chip shows the progress. Exactly one button (Connect) is the dialog's
active default, so the props dialog's own OK/Cancel row stays away. State
lives on WindowManager (`ui/properties/engine_dialog_props.py`); this module
only draws.
"""

import os

from mixar.modules.common.i18n import iface_, n_
from mixar.modules.common.sheet import kit as S

OP_PICK = "mixar.engine_dialog_pick"
OP_START = "mixar.engine_connect_start"
OP_BROWSE = "mixar.engine_browse_folder"

SHEET_WIDTH = S.WIDTH // 2
# Design px a text line of the right column may use (from the prompt inset).
TEXT_WIDTH = S.WIDTH - S.RIGHT_X - S.PROMPT_INSET - S.RIGHT_MARGIN
LABEL_TO_FIELD = 8
FOOT_GAP = 22
SIDEBAR_GAP = 40
MAX_EDITORS = 4
ENGINES = (('GODOT', "Godot", "godot"), ('UNREAL', "Unreal Engine", "unreal"))
ENGINE_NAMES = {"godot": "Godot", "unreal": "Unreal"}
MODES = (('NEW', n_("New project")), ('EXISTING', n_("Existing project")))
# One line on what Connect does to the project; closing Unreal first matters
# only for a project that may be open already.
WHAT_CHANGES = {
    ('GODOT', 'NEW'): n_("Mixar adds its open-source Mixar Link add-on and opens the project in Godot."),
    ('GODOT', 'EXISTING'): n_("Mixar adds its open-source Mixar Link add-on and opens the project in Godot."),
    ('UNREAL', 'NEW'): n_("Mixar adds its open-source Mixar Link plugin and turns on Unreal's MCP server "
                          "for this computer only."),
    ('UNREAL', 'EXISTING'): n_("Mixar adds its open-source Mixar Link plugin and turns on Unreal's MCP server "
                               "for this computer only. Close the project in Unreal first."),
}


def draw_dialog(layout, wm, view):
    """`mixar.engine_connect`'s draw(). ``view`` is the operator module's
    `SheetView`: the engine on this computer, the field check, busy, the
    live editors."""
    layout.use_property_split = False
    layout.use_property_decorate = False

    sheet = layout.column(align=True)
    if hasattr(sheet, 'mixar_sheet_frame'):
        sheet.mixar_sheet_frame(header=S.HEADER, sidebar=S.SIDEBAR)
    _draw_header(sheet)

    plan = FormPlan(sheet, wm, view)
    editors = list(view.editors)[:MAX_EDITORS]
    extra = (SIDEBAR_GAP + S.CAPTION_H + S.CAPTION_TO_ROWS + len(editors) * S.STRIP_H) if editors else 0
    geo = S.Geometry(len(ENGINES) + int(-(-extra // S.ROW_H)), plan.need, plan.bottom)
    body = sheet.split(factor=S.SPLIT_FACTOR, align=True)
    _draw_sidebar(body.column(align=True), wm, geo, editors, enabled=not view.busy)
    plan.build(S.fixed(body.column(align=True), geo.right), geo)


def _draw_header(sheet):
    header = sheet.row(align=True)
    title = header.row(align=True)
    title.scale_y = S.units(S.HEADER)
    S.label(title,
            iface_("Connect a game engine") + "\n"
            + iface_("Mixie builds your game in Godot or Unreal while you work in Mixar."),
            S.TITLE, translate=False)
    # The ✕: a cancel-path dismiss (see byok_dialog_ui._draw_header).
    slot = S.sized(header, S.CLOSE)
    slot.scale_y = S.units(S.CLOSE_TOP + S.CLOSE)
    S.dismiss(slot, S.CLOSE_GLYPH, S.CLOSE_KIND)
    S.gap(header, S.CLOSE_RIGHT)


def _draw_sidebar(col, wm, geo, editors, enabled):
    from ...core import engine_logos

    body = S.fixed(col, geo.left_body)
    body.enabled = enabled
    S.sep(body, S.CAPTION_TOP)
    S.label(S.row(body, S.CAPTION_H, left=S.LEFT_INSET, right=S.ROW_RIGHT), n_("ENGINES"), S.CAPTION)
    S.sep(body, S.CAPTION_TO_ROWS)
    current = wm.mixar_engine_dialog_engine
    for key, name, logo in ENGINES:  # product names: never translated
        S.choice(S.row(body, S.ROW_H, left=S.LEFT_INSET, right=S.ROW_MIN_RIGHT), OP_PICK, name,
                 S.PROVIDER_ROW, lit=(key == current), icon_value=engine_logos.icon_id(logo), engine=key)
    if editors:
        # What is live right now: the editors the agent can drive.
        S.sep(body, SIDEBAR_GAP)
        S.label(S.row(body, S.CAPTION_H, left=S.LEFT_INSET, right=S.ROW_RIGHT), n_("CONNECTED"), S.CAPTION)
        S.sep(body, S.CAPTION_TO_ROWS)
        for editor in editors:
            strip = S.row(body, S.STRIP_H, left=S.LEFT_INSET, right=S.ROW_MIN_RIGHT)
            S.status_dot(strip, S.STATUS_ON)
            engine = ENGINE_NAMES.get(editor.get("engine"), str(editor.get("engine") or "").title())
            S.label(strip, f"{engine} · {editor.get('project_name') or iface_('Untitled')}", S.NOTE,
                    translate=False)
    S.sep(S.fixed(col, S.FOOTER), S.FOOTER)


def _lines(col, lines, kind, height=S.NOTE_H):
    for line in lines:
        S.label(S.row(col, height, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN), line, kind,
                translate=False)


class FormPlan:
    """The right column for the selected engine and project mode."""

    def __init__(self, layout, wm, view):
        self.wm, self.view = wm, view
        self.engine = wm.mixar_engine_dialog_engine
        self.new = wm.mixar_engine_dialog_mode == 'NEW'
        self.browse_text = iface_("Browse")
        self.browse_w = S.text_width(layout, S.SECONDARY, self.browse_text) + S.BUTTON_PAD
        text, kind = self._check_text(view)
        self.check_kind = kind
        self.check = S.wrap(layout, kind, text, TEXT_WIDTH) if text else []
        fields = 2 if self.new else 1
        self.fields_h = fields * (S.NOTE_H + LABEL_TO_FIELD + S.FIELD_H) + (fields - 1) * S.GAP
        self.need = S.CHIP_H + S.GAP + self.fields_h + S.GAP + max(1, len(self.check)) * S.NOTE_H
        changes = iface_(WHAT_CHANGES[(self.engine, 'NEW' if self.new else 'EXISTING')])
        self.note = S.wrap(layout, S.NOTE, changes, TEXT_WIDTH) or [""]
        self.bottom = FOOT_GAP + len(self.note) * S.NOTE_H + S.NOTE_TO_INPUT + S.INPUT_H + S.BOTTOM

    def _check_text(self, view):
        """The line under the fields: an install the user must make first,
        else the folder check (a quiet hint, or the reason it is refused)."""
        if view.blocker:
            return view.blocker, S.DANGER_TEXT
        check = view.check
        if check.message:
            quiet = check.ok or check.status == 'empty'
            return iface_(check.message).format(**check.args), (S.NOTE if quiet else S.DANGER_TEXT)
        if check.folder and self.new:
            # The folder's own name: a whole path wraps and ellipsises.
            return iface_("Creates a new folder “{name}” here.").format(name=os.path.basename(check.folder)), S.NOTE
        return "", S.NOTE

    def build(self, col, geo):
        S.sep(col, S.CAPTION_TOP)
        S.caption(col, n_("PROJECT"), S.RIGHT_INSET)
        S.sep(col, S.CAPTION_TO_CHIPS)
        area = S.fixed(col, geo.area)
        enabled = self.view.installed and not self.view.busy
        self._chips(area, enabled)
        S.sep(area, S.GAP)
        fields = area.column(align=True)
        fields.enabled = enabled
        if self.new:
            self._field(fields, iface_("Name"), 'mixar_engine_dialog_name')
            S.sep(fields, S.GAP)
            self._field(fields, iface_("Location"), 'mixar_engine_dialog_location', browse='location')
        else:
            self._field(fields, iface_("Project folder"), 'mixar_engine_dialog_folder', browse='folder')
        S.sep(area, S.GAP)
        _lines(area, self.check, self.check_kind)
        self._foot(col)

    def _chips(self, area, enabled):
        line = S.row(area, S.CHIP_H, left=S.RIGHT_INSET, packed=True)
        line.enabled = enabled
        current = self.wm.mixar_engine_dialog_mode
        for key, label in MODES:
            text = iface_(label)
            S.choice(S.sized(line, S.text_width(line, S.CHIP, text) + 2 * S.CHIP_PAD), OP_PICK, text,
                     S.CHIP, lit=(key == current), mode=key)

    def _field(self, col, label, prop, browse=""):
        # A quiet label: the value in the field is what the eye should land on.
        S.label(S.row(col, S.NOTE_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN), label, S.NOTE,
                translate=False)
        S.sep(col, LABEL_TO_FIELD)
        field = S.row(col, S.FIELD_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
        if not browse:
            S.input_field(field, self.wm, prop)
            return
        # Browse docks inside the field like AI Provider settings' Save.
        S.input_field(field, self.wm, prop, docked_w=self.browse_w + S.DOCK_INSET)
        S.button(S.sized(field, self.browse_w + S.DOCK_INSET), OP_BROWSE, self.browse_text, S.SECONDARY,
                 docked=True).target = browse

    def _foot(self, col):
        S.sep(col, FOOT_GAP)
        _lines(col, self.note, S.NOTE)
        S.sep(col, S.NOTE_TO_INPUT)
        line = S.row(col, S.INPUT_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN)
        if self.view.busy:
            text = iface_("Connecting…")
        elif self.new and self.view.check.status != 'same':
            text = iface_("Create and connect")
        else:
            text = iface_("Connect")
        button_w = max(S.SAVE_W, S.text_width(line, S.PRIMARY, text) + 2 * S.BUTTON_PAD)
        # The engine on this computer, beside the action it gates.
        status = line.row(align=True)
        status.alignment = 'LEFT'
        S.status_dot(status, self.view.status_dot)
        room = TEXT_WIDTH - button_w - S.STATUS_DOT - S.STATUS_GAP - S.GAP
        S.label(status, (S.wrap(status, S.NOTE, self.view.status_text, room) or [""])[0], S.NOTE,
                translate=False)
        slot = S.sized(line, button_w)
        # A disabled pill keeps the slot and the active-default flag; Return
        # does nothing on it.
        slot.enabled = self.view.can_connect
        S.confirm(slot, OP_START, text, S.PRIMARY, default=True)


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
