# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Export card's foot: the destination and the one action, by state.

  IDLE / RUNNING   File name + Folder (browse docked), then Export
                   (a disabled "Exporting…" while the export runs)
  CONFIRM          a file of that name exists: Cancel / Replace
  DONE             what was written (size, the re-import check, a
                   warning) or that the render runs in the background:
                   Show in folder, Export again, Done
  ERROR            what went wrong: Back to settings

Publish to Web draws its own foot (`export_card_web.foot`). Every state has
exactly one active-default button (the sheet's one-action contract)."""

import os

from mixar.modules.common.i18n import iface_, n_
from mixar.modules.common.sheet import kit as S

from ... import constants as C
from ...core import state, targets
from . import export_card_web
from .export_card_ui import Rows, metrics

FIELD_GAP = 24
EXT_W = 90


def plan(layout, context, p):
    rows = Rows()
    rows.gap(metrics().foot_gap)
    if p.target == C.WEB:
        export_card_web.foot(rows, context, foot_row, note_line)
    elif p.state in (C.IDLE, C.RUNNING):
        _destination(rows, p)
        busy = p.state == C.RUNNING
        verb = _verb(p.target)
        foot_row(rows, [], (C.OP_RUN, iface_("Exporting…") if busy else verb, {}),
                 enabled=not busy)
    elif p.state == 'CONFIRM':
        facts = state.result()
        note_line(rows, iface_("{name} is already in this folder. Replace it?").format(
            name=facts.get("name", "")), S.BODY)
        foot_row(rows, [(C.OP_AGAIN, iface_("Cancel"), S.SECONDARY, False, {})],
                 (C.OP_RUN, iface_("Replace"), {"replace": True}))
    elif p.state == C.DONE:
        _done(rows, layout)
    else:
        facts = state.result()
        message = iface_(facts.get("error") or n_("The export did not finish."))
        try:
            message = message.format(**(facts.get("error_args") or {}))
        except (KeyError, IndexError, ValueError):
            pass
        note_line(rows, message, S.DANGER_TEXT)
        if facts.get("detail"):
            for line in S.wrap(layout, S.NOTE, facts["detail"], metrics().text_w)[:2]:
                note_line(rows, line, S.NOTE)
        foot_row(rows, [], (C.OP_AGAIN, iface_("Back to settings"), {}))
    rows.gap(S.BOTTOM)
    return rows


def _verb(target_id):
    if target_id == C.IMAGE:
        return iface_("Render image")
    if target_id == C.VIDEO:
        return iface_("Render video")
    if target_id in C.PROJECT_TARGETS:
        return iface_("Save copy")
    return iface_("Export {format}").format(format=targets.get(target_id).tile)


# ---------------------------------------------------------------------------
# Builders (shared with export_card_web)
# ---------------------------------------------------------------------------

def note_line(rows, text, kind=S.NOTE):
    """One line of already-translated text over the action row."""
    rows.add(S.NOTE_H if kind == S.NOTE else S.STRIP_H, lambda col: S.label(
        S.row(col, S.NOTE_H if kind == S.NOTE else S.STRIP_H, left=S.PROMPT_INSET,
              right=S.RIGHT_MARGIN), text, kind, translate=False))


def foot_row(rows, secondaries, primary, enabled=True, done=False):
    """The right-aligned action row: ``secondaries`` = ``(op, text, kind,
    _unused, props)`` pills, then the state's one default — ``primary`` =
    ``(op, text, props)``, or with ``done`` a Done dismiss."""
    rows.gap(S.NOTE_TO_INPUT)

    def draw(col):
        line = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, align='RIGHT')
        for op, text, kind, _unused, props in secondaries:
            slot = S.sized(line, S.text_width(line, kind, text) + 2 * S.BUTTON_PAD)
            pill = S.button(slot, op, text, kind)
            for name, value in props.items():
                setattr(pill, name, value)
            S.gap(line, S.GAP)
        if done:
            S.dismiss(S.sized(line, S.SAVE_W * 0.8), iface_(S.DONE_TEXT), S.PRIMARY,
                      default=True)
            return
        op, text, props = primary
        slot = S.sized(line, max(S.SAVE_W, S.text_width(line, S.PRIMARY, text) + 2 * S.BUTTON_PAD))
        slot.enabled = enabled
        button = S.button(slot, op, text, S.PRIMARY, default=True)
        for name, value in props.items():
            setattr(button, name, value)
    rows.add(S.INPUT_H, draw)


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

def _destination(rows, p):
    extension = targets.extension(p.target, p.gltf_file, p.usd_file, p.render_format)

    def labels(col):
        line = S.row(col, S.NOTE_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
        S.label(S.sized(line, metrics().name_w + EXT_W + FIELD_GAP), n_("File name"), S.NOTE)
        S.label(line, n_("Folder"), S.NOTE)

    def fields(col):
        line = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
        line.enabled = p.state != C.RUNNING
        S.input_field(S.sized(line, metrics().name_w), p, "file_name")
        S.label(S.sized(line, EXT_W), " " + extension, S.BODY, translate=False)
        S.gap(line, FIELD_GAP)
        # The folder field carries Blender's browse button, docked inside it.
        S.input_field(line, p, "folder", docked_w=S.UNIT_DP)

    rows.add(S.NOTE_H, labels)
    rows.add(S.INPUT_H, fields)


def _size_text(size):
    if size >= 1024 * 1024:
        return iface_("{size} MB").format(size=f"{size / (1024 * 1024):.1f}")
    return iface_("{size} KB").format(size=max(1, size // 1024))


def _done(rows, layout):
    facts = state.result()
    name = facts.get("name", "")

    def headline(col, text):
        line = S.row(col, S.STRIP_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN)
        S.status_dot(line, S.STATUS_ON)
        S.label(line, text, S.BODY, translate=False)

    if facts.get("kind") == "render":
        text = iface_("Rendering {name} in the background.").format(name=name)
        rows.add(S.STRIP_H, lambda col: headline(col, text))
        note_line(rows, iface_("You can keep working. A notification says when it is saved."))
    else:
        text = iface_("Saved {name} · {size}").format(name=name,
                                                      size=_size_text(int(facts.get("size", 0))))
        rows.add(S.STRIP_H, lambda col: headline(col, text))
        if facts.get("dropped"):
            note_line(rows, iface_("Agent chat removed from the copy ({count} messages).").format(
                count=facts["dropped"]))
        if facts.get("non_manifold"):
            note_line(rows, iface_("Not watertight: {count} open edges. A slicer may refuse "
                                   "it.").format(count=facts["non_manifold"]), S.DANGER_TEXT)
        elif facts.get("checked") and facts.get("passed"):
            note_line(rows, iface_("Checked: Mixar opened the file again and it matches."))
        if facts.get("warning"):
            # The lane's warnings run long (glTF lighting advice): wrap, never clip.
            for line in S.wrap(layout, S.NOTE, facts["warning"], metrics().text_w)[:3]:
                note_line(rows, line)
    folder = facts.get("folder") or os.path.dirname(facts.get("path", ""))
    secondaries = [(C.OP_AGAIN, iface_("Export again"), S.SECONDARY, False, {})]
    if folder:
        secondaries.insert(0, (C.OP_REVEAL, iface_("Show in folder"), S.SECONDARY, False, {}))
    foot_row(rows, secondaries, None, done=True)


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
