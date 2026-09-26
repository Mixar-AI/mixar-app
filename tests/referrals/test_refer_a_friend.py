# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Refer a Friend: email parsing, reply summaries and the wiring contracts.

Operators are MagicMocks under the stubbed ``bpy``, so the card button,
operator ids and dialog footer are pinned from source.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.referrals import constants as C
from mixar.modules.referrals.core import invites

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src/scripts/mixar/modules/referrals"
OPS_PY = MODULE / "ui/operators/referral_ops.py"
DIALOG_PY = MODULE / "ui/operators/referral_dialog_ui.py"
CARD_CC = ROOT / "src/source/blender/editors/interface/interface_mixar_profile_card.cc"
ICONS_CC = ROOT / "src/source/blender/editors/interface/interface_mixar_card_icons.cc"
STYLE_CC = ROOT / "src/source/blender/editors/interface/mixar/style.cc"
TYPES_HH = ROOT / "src/source/blender/editors/include/UI_mixar_types.hh"
TOPBAR_PY = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/topbar.py"


def test_parse_splits_dedupes_and_flags_bad_addresses():
    valid, invalid = invites.parse_emails(
        "A@x.com, b@y.org; a@x.com\n<c@z.io>  nope  also@bad")
    assert valid == ["a@x.com", "b@y.org", "c@z.io"]
    assert invalid == ["nope", "also@bad"]
    assert invites.parse_emails("  ") == ([], [])


def test_summary_all_sent_clears_details():
    payload = {"results": [{"email": "a@x.com", "status": "sent"},
                           {"email": "b@x.com", "status": "sent"}]}
    assert invites.summarize(payload) == ("Invite sent to 2 friends", [], True)


def test_summary_partial_lists_what_was_not_sent():
    payload = {"results": [
        {"email": "a@x.com", "status": "sent"},
        {"email": "b@x.com", "status": "skipped", "message": "Already invited, or already on Mixar"},
    ]}
    headline, lines, all_sent = invites.summarize(payload)
    assert headline == "Sent 1 of 2 invites" and not all_sent
    assert lines == ["b@x.com: Already invited, or already on Mixar"]
    headline, _, _ = invites.summarize({"results": [payload["results"][1]]})
    assert headline == "No invites were sent"


def test_unwrap_reads_the_backend_envelope():
    response = SimpleNamespace(data={"status": "success", "data": {"invite_url": "u"}})
    assert invites.unwrap(response) == {"invite_url": "u"}
    assert invites.unwrap(SimpleNamespace(data=None)) == {}


def test_user_facing_backend_messages_are_shown():
    from mixar.modules.common.api.exceptions import ServerError, ValidationError

    err = ValidationError("'x' is not a valid email address", status_code=422)
    assert invites.error_message(err, "fallback") == "'x' is not a valid email address"
    err = ServerError("Email invites are temporarily unavailable", status_code=503)
    assert invites.error_message(err, "fallback") == "Email invites are temporarily unavailable"
    # A 500's text is not written for users — the shared classifier answers.
    assert invites.error_message(ServerError("Traceback …", status_code=500), "f") != "Traceback …"


def test_profile_card_offers_refer_a_friend_with_its_own_glyph():
    card = CARD_CC.read_text(encoding="utf-8")
    assert '"MIXAR_OT_refer_friend", "Refer a Friend", MixarCardIcon::Gift' in card
    assert "Gift," in TYPES_HH.read_text(encoding="utf-8")
    assert "case MixarCardIcon::Gift:" in ICONS_CC.read_text(encoding="utf-8")
    # The payload → icon clamp must reach the newest glyph, or Gift draws as Cross.
    assert "int(MixarCardIcon::Gift)" in STYLE_CC.read_text(encoding="utf-8")
    assert '"mixar.refer_friend"' in TOPBAR_PY.read_text(encoding="utf-8")


def test_operator_ids_match_what_the_card_and_dialog_call():
    tree = ast.parse(OPS_PY.read_text(encoding="utf-8"))
    ids = {
        node.value.value
        for cls in tree.body if isinstance(cls, ast.ClassDef)
        for node in cls.body
        if isinstance(node, ast.Assign) and node.targets[0].id == "bl_idname"
    }
    dialog = DIALOG_PY.read_text(encoding="utf-8")
    for op in ("mixar.referral_copy_link", "mixar.referral_send_invites", "mixar.referral_reload"):
        assert op in ids and f'"{op}"' in dialog
    assert "mixar.refer_friend" in ids


def test_every_dialog_state_has_one_default_action():
    """A state without an active-default button brings back the native OK row."""
    dialog = DIALOG_PY.read_text(encoding="utf-8")
    tree = ast.parse(dialog)
    for name in ("_footer", "draw_dialog"):
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        assert "default=True" in ast.get_source_segment(dialog, fn), name


def test_client_cap_mirrors_backend():
    assert C.MAX_INVITES_PER_SEND == 5
