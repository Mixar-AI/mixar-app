# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Connect MCP — the right column of each state (see `connect_sheet_ui`).

A plan measures what its column needs (``need`` above the foot, ``bottom``
for the foot) so `kit.Geometry` can grow the sheet, then builds it:

- FormPlan (IDLE / ADDING / ERROR): the caption, the Other app's format
  chips, where the setup goes, the snippet (Claude Code / Codex: Copy docked
  in its corner), the error lines, the MCP status line, the interface
  switch, then the prompt, note and actions — Add to <app> (Adding to
  <app>… while it runs, Try Again after a failure) or Copy setup, plus
  Open <config file> when the app has one.
- RecapPlan (ADDED): what happened and one Done.
- SignedOutPlan: what MCP needs, the status line while MCP is on (turning
  it off needs no account), Sign in.

The snippet is `setup.render(app, *stable_launch())` — `stable_launch`
writes nothing, so drawing never touches the launcher.
"""

from mixar.modules.common.i18n import iface_, n_, rpt_
from mixar.modules.common.sheet import kit as S

from ...constants import OTHER_APP
from ...core import app_configs, runtime
from ...core.connect_state import BUSY_STATES
from ...core.setup import render, stable_launch
from . import connect_sheet_ui as ui

#: Format chips of the Other app (keys of `app_configs.FORMATS`).
FORMAT_LABELS = {'JSON': n_("mcpServers JSON"), 'COMMAND': n_("Command")}
# Design px the snippet block spans (from the column inset to the margin).
BLOCK_WIDTH = S.WIDTH - S.RIGHT_X - S.RIGHT_INSET - S.RIGHT_MARGIN
SIGNED_OUT_WIDTH = 832   # the signed-out explanation's measure
ERROR_DETAIL_LINES = 2
BODY_ROW = 40


def plan_for(layout, wm, state, signed_in, ready):
    if state == 'ADDED':
        return RecapPlan(layout, wm)
    if not signed_in:
        return SignedOutPlan(layout, wm, state)
    return FormPlan(layout, wm, state, ready)


def _name(app):
    """An app's product name (never translated); the Other app is "your app"."""
    if app in app_configs.SIDEBAR or app in app_configs.FORMATS:
        return app_configs.label(app)
    return iface_("your app")


def _caption(col, text):
    S.sep(col, S.CAPTION_TOP)
    S.caption(col, text, S.RIGHT_INSET, translate=False)
    S.sep(col, S.CAPTION_TO_CHIPS)


def _lines(area, lines, kind, height=S.NOTE_H, left=S.PROMPT_INSET):
    for line in lines:
        S.label(S.row(area, height, left=left, right=S.RIGHT_MARGIN), line, kind, translate=False)


class FormPlan:
    """IDLE / ADDING / ERROR for one app."""

    def __init__(self, layout, wm, state, ready):
        self.wm, self.state, self.ready = wm, state, ready
        self.app = wm.mixar_mcp_dialog_app
        self.other = self.app == OTHER_APP
        self.target = wm.mixar_mcp_dialog_format if self.other else self.app
        self.name = _name(OTHER_APP if self.other else self.app)
        self.addable = not self.other and self.app in app_configs.ADDABLE
        self.busy = state in BUSY_STATES
        self.on = runtime.enabled()

        how = next(how for key, _name_, how in app_configs.APPS if key == self.target)
        self.how = S.wrap(layout, S.NOTE, iface_(how), ui.TEXT_WIDTH) or [""]
        self.copy_text = iface_("Copy")
        dock_w = S.snippet_dock_width(layout, self.copy_text) if self.addable else 0.0
        columns = S.snippet_columns(layout, BLOCK_WIDTH - dock_w - 2 * S.SNIPPET_PAD_X)
        self.snippet = S.wrap_code(render(self.target, *stable_launch()), columns)
        self.errors = self._errors(layout)
        self.status = ui.status_lines(layout, self.on, ready)
        self.note_beside = ui.switch_note_fits(layout)
        self.strips_h = ((len(self.errors) + len(self.status)) * S.STRIP_H + ui.STRIP_GAP
                         + S.STRIP_H + (0 if self.note_beside else S.NOTE_H))
        chips = S.CHIP_H + S.GAP if self.other else 0.0
        self.need = (chips + len(self.how) * S.NOTE_H + S.GAP
                     + S.snippet_height(len(self.snippet)) + self.strips_h)
        self.note = S.wrap(layout, S.NOTE, self._note(), ui.TEXT_WIDTH) or [""]
        self.bottom = ui.foot_height(self.note)

    def _errors(self, layout):
        if self.state != 'ERROR':
            return []
        name = _name(self.wm.mixar_mcp_result_app or self.app)
        lines = [iface_("Could not add Mixar to {app}").format(app=name)]
        detail = self.wm.mixar_mcp_last_error
        if detail:
            # Static details are stored as msgids; formatted ones arrive as is.
            lines += S.wrap(layout, S.DANGER_TEXT, rpt_(detail), ui.TEXT_WIDTH)[:ERROR_DETAIL_LINES]
        return lines

    def _caption(self):
        if self.other:
            return iface_("ANY APP THAT RUNS A {server}").format(
                server=S.bright(iface_("LOCAL MCP SERVER")))
        name = S.bright(self.name.upper())
        if self.addable:
            return iface_("ADD MIXAR TO {app}").format(app=name)
        return iface_("SET UP MIXAR IN {app}").format(app=name)

    def _prompt(self):
        if self.addable:
            return iface_("Add Mixar to {app} in one click.").format(app=self.name)
        return iface_("Copy the setup into {app}.").format(app=self.name)

    def _note(self):
        if self.addable:
            return iface_("Then restart {app}'s MCP connection. The setup holds a launcher path, "
                          "never your account.").format(app=self.name)
        return iface_("Paste it where the line above says, then restart {app}'s MCP "
                      "connection.").format(app=self.name)

    def build(self, col, geo):
        _caption(col, self._caption())
        area = S.fixed(col, geo.area - self.strips_h)
        area.enabled = not self.busy
        if self.other:
            self._chips(area)
        _lines(area, self.how, S.NOTE)
        S.sep(area, S.GAP)
        dock = (ui.OP_COPY, self.copy_text) if self.addable else None
        copy = S.snippet(area, self.snippet, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, dock=dock)
        if copy is not None:
            copy.client = self.app
        for line in self.errors:
            S.label(S.row(col, S.STRIP_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN), line,
                    S.DANGER_TEXT, translate=False)
        ui.draw_status(col, self.status, self.on, self.ready, self.busy)
        ui.draw_switch(col, self.on and not self.busy, self.note_beside)
        self._actions(ui.foot(col, self._prompt(), self.note))

    def _chips(self, area):
        line = S.row(area, S.CHIP_H, left=S.RIGHT_INSET, packed=True)
        for key in app_configs.FORMATS:
            text = iface_(FORMAT_LABELS[key])
            S.choice(S.sized(line, S.text_width(line, S.CHIP, text) + 2 * S.CHIP_PAD),
                     ui.OP_PICK_FORMAT, text, S.CHIP,
                     lit=(key == self.wm.mixar_mcp_dialog_format), client=key)
        S.sep(area, S.GAP)

    def _actions(self, line):
        path = None if self.other else app_configs.config_path(self.app)
        if path is not None:
            ui.secondary(line, ui.OP_OPEN, iface_("Open {file}").format(file=path.name),
                         enabled=not self.busy).app = self.app
        if self.busy:
            name = _name(self.wm.mixar_mcp_result_app or self.app)
            # A disabled pill keeps the primary slot (and the default flag)
            # while the add runs; Return does nothing on it.
            ui.primary(line, ui.OP_ADD, iface_("Adding to {app}…").format(app=name),
                       enabled=False)
        elif self.addable:
            text = iface_("Try Again") if self.state == 'ERROR' else \
                iface_("Add to {app}").format(app=self.name)
            ui.primary(line, ui.OP_ADD, text).app = self.app
        else:
            ui.primary(line, ui.OP_COPY, iface_("Copy setup")).client = self.target


class RecapPlan:
    """ADDED: the add landed (added, updated or already there); one Done."""

    bottom = S.action_block_height()

    def __init__(self, layout, wm):
        self.name = _name(wm.mixar_mcp_result_app or wm.mixar_mcp_dialog_app)
        self.already = wm.mixar_mcp_result_status == 'already'
        if self.already:
            title = iface_("{app} already has Mixar")
            note = iface_("Nothing changed. Restart {app}'s MCP connection if Mixar's tools "
                          "are missing.")
        else:
            title = iface_("Mixar added to {app}")
            note = iface_("Restart {app}'s MCP connection to start using Mixar.")
        self.title = S.wrap(layout, S.BODY, title.format(app=self.name), ui.TEXT_WIDTH)
        self.note = S.wrap(layout, S.NOTE, note.format(app=self.name), ui.TEXT_WIDTH)
        self.need = len(self.title) * BODY_ROW + len(self.note) * S.NOTE_H

    def build(self, col, geo):
        name = S.bright(self.name.upper())
        _caption(col, iface_("ALREADY IN {app}").format(app=name) if self.already
                 else iface_("ADDED TO {app}").format(app=name))
        area = S.fixed(col, geo.area)
        _lines(area, self.title, S.BODY, height=BODY_ROW)
        _lines(area, self.note, S.NOTE)
        S.sep(col, S.NOTE_TO_INPUT)
        line = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, align='RIGHT')
        S.dismiss(S.sized(line, S.SAVE_W), iface_(S.DONE_TEXT), S.PRIMARY, default=True)


class SignedOutPlan:
    """No account: MCP acts for one, so the setup waits for a sign-in (a guest
    session counts); turning MCP off never needs one."""

    def __init__(self, layout, wm, state):
        self.state = state
        self.on = runtime.enabled()
        self.body = S.wrap(layout, S.BODY, iface_(
            "Mixar's MCP works for your Mixar account: AI apps see your scenes, and anything "
            "they generate uses your credits."), SIGNED_OUT_WIDTH)
        self.hint = S.wrap(layout, S.NOTE, iface_(
            "Pick an app on the left after signing in to see its exact setup."), ui.TEXT_WIDTH)
        self.status = ui.status_lines(layout, True, False) if self.on else []
        self.strips_h = len(self.status) * S.STRIP_H
        self.need = len(self.body) * BODY_ROW + S.GAP + len(self.hint) * S.NOTE_H + self.strips_h
        self.note = S.wrap(layout, S.NOTE, iface_(
            "A guest session works too. Turning MCP off never needs an account."),
            ui.TEXT_WIDTH) or [""]
        self.bottom = ui.foot_height(self.note)

    def build(self, col, geo):
        _caption(col, iface_("SIGN IN TO CONNECT {apps}").format(apps=S.bright(iface_("AI APPS"))))
        area = S.fixed(col, geo.area - self.strips_h)
        _lines(area, self.body, S.BODY, height=BODY_ROW)
        S.sep(area, S.GAP)
        _lines(area, self.hint, S.NOTE)
        if self.on:
            ui.draw_status(col, self.status, True, False, self.state in BUSY_STATES)
        line = ui.foot(col, iface_("Sign in to connect MCP."), self.note)
        ui.primary(line, ui.OP_LOGIN, iface_("Sign in"))


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
