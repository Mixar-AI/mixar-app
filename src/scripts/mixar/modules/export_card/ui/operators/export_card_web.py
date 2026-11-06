# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish to Web on the Export card (the former Export menu popover).

The form edits the scene's publish settings (``scene.mixar_web_publish``);
the foot follows the publish pipeline's state (`web_publish.core.publish_state`
— a lock-guarded snapshot, read-only here): Publish, the upload's progress
with Cancel, a failure with Try again, or the live link with Copy, Open,
Unpublish and Publish new version. Runtime text from the pipeline arrives as
untranslated templates and is translated here."""

from mixar.modules.common.i18n import iface_, n_
from mixar.modules.common.sheet import kit as S

from ... import constants as C

FIELD_W = 640
OP_PUBLISH = "mixar.web_publish"
_STATUS = {
    "EXPORTING": n_("Exporting the scene…"),
    "UPLOADING": n_("Uploading…"),
    "FINALIZING": n_("Finishing…"),
}


def _props(context):
    return getattr(context.scene, "mixar_web_publish", None)


def _publish_state():
    try:
        from mixar.modules.web_publish.core.publish_state import get_publish_state
        return get_publish_state()
    except Exception:  # noqa: BLE001 - a build without Publish to Web
        return None


def _field(owner, prop, placeholder):
    def control(line):
        slot = S.sized(line, FIELD_W)
        slot.prop(owner, prop, text="", placeholder=iface_(placeholder))
        S.tag(slot, S.INPUT)
    return control


def form(rows, layout, context, p, setting, chips):
    props = _props(context)
    if props is None:
        rows.add(S.NOTE_H, lambda col: S.label(
            S.row(col, S.NOTE_H, left=S.PROMPT_INSET), n_("Publish to Web is not available."),
            S.NOTE))
        return
    setting(rows, n_("Title"), _field(props, "title", n_("Scene title")), S.FIELD_H)
    setting(rows, n_("Description"), _field(props, "description", n_("Optional")), S.FIELD_H)
    setting(rows, n_("Who can open it"), chips(props, "visibility", (
        ('public', n_("Anyone, listed in your gallery")),
        ('unlisted', n_("Only people with the link"))), prefix="web."))
    setting(rows, n_("Animation"), chips(props, "include_animation", (
        (True, n_("Include")), (False, n_("Leave out"))), prefix="web."))
    link = props.link if props.is_published else ""
    if link:
        status = iface_("Live · version {revision}").format(revision=props.revision)
        if props.last_published:
            status += " · " + props.last_published

        def live(col):
            line = S.row(col, S.STRIP_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN)
            S.status_dot(line, S.STATUS_ON)
            S.label(line, status, S.BODY, translate=False)
        rows.add(S.STRIP_H, live)
        rows.gap(8)
        height = S.snippet_height(1)
        rows.add(height, lambda col: S.snippet(
            col, [link], left=S.RIGHT_INSET, right=S.RIGHT_MARGIN,
            dock=("mixar.web_publish_copy_link", iface_("Copy link"))))


# ---------------------------------------------------------------------------
# Foot
# ---------------------------------------------------------------------------

def foot(rows, context, foot_row, note_line):
    """The web target's foot; ``foot_row`` / ``note_line`` are the card
    foot's builders (`export_card_foot`)."""
    props = _props(context)
    publish = _publish_state()
    if props is None or publish is None:
        return
    progress, _result = publish.snapshot()
    mine = publish.scene_name == context.scene.name
    if publish.busy:
        text = (iface_(_STATUS.get(progress.status, n_("Publishing…"))) if mine
                else iface_("Publishing another scene…"))
        note_line(rows, text, S.BODY)
        foot_row(rows, [("mixar.web_publish_cancel", iface_("Cancel"), S.SECONDARY, False, {})]
                 if mine else [],
                 (OP_PUBLISH, iface_("Publishing…"), {}), enabled=False)
        return
    if mine and progress.status in ("ERROR", "CANCELLED"):
        from mixar.modules.web_publish.core.publish_state import format_message
        if progress.status == "CANCELLED":
            note_line(rows, iface_("Publish cancelled."), S.BODY)
        else:
            note_line(rows, format_message(iface_(progress.error), progress.error_args),
                      S.DANGER_TEXT)
        foot_row(rows, [("mixar.web_publish_dismiss", iface_("Dismiss"), S.SECONDARY, False, {})],
                 (OP_PUBLISH, iface_("Try again"), {"update_existing": props.is_published}))
        return
    if props.is_published:
        if mine and progress.status == "DONE" and progress.warning:
            note_line(rows, progress.warning, S.NOTE)
        foot_row(rows, [
            ("mixar.web_publish_open", iface_("Open"), S.SECONDARY, False, {}),
            ("mixar.web_publish_unpublish", iface_("Unpublish"), S.DANGER_BUTTON, False, {}),
        ], (OP_PUBLISH, iface_("Publish new version"), {"update_existing": True}))
        return
    note_line(rows, iface_("Uploads this scene and gives you a link to share. "
                           "Needs a Mixar account."), S.NOTE)
    foot_row(rows, [], (C.OP_RUN, iface_("Publish to Web"), {}))


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
