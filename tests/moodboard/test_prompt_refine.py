# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Refine / Revert beside every generation prompt.

Three things are load-bearing and none of them is visible from a happy-path
click:

- a refinement must target the model the prompt will actually be SENT to,
  resolved through the same catalog helpers the tab's own Mode/Model
  dropdowns use — refining an image prompt as if it were a video prompt is
  worse than not refining at all;
- what the user wrote must survive the round trip, so Revert restores the
  exact text the backend refined rather than whatever is in the field when
  a slow answer lands;
- a failed or no-op refinement must leave the field alone and must NOT offer
  a Revert, which would promise an undo of a change that never happened.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
TILE_CONTROLS = (
    ROOT
    / "src/source/blender/editors/space_mixie"
    / "mixie_draw_moodboard_node_tile_controls.cc"
)

sys.path.insert(0, str(ROOT / "src/scripts"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _targets():
    from mixar.modules.moodboard.core import prompt_refine_targets

    return prompt_refine_targets


def _engine():
    from mixar.modules.moodboard.core import prompt_refine

    return prompt_refine


# ---------------------------------------------------------------------------
# Target coverage
# ---------------------------------------------------------------------------


def test_every_enter_dispatchable_tab_can_also_refine():
    """The two tables answer the same question — "which tab owns this
    prompt" — so a tab Enter can submit must also be one Refine can target.
    """
    from mixar.modules.moodboard.core import prompt_submit

    targets = _targets()
    missing = set(prompt_submit.PROMPT_TAB_DISPATCH) - set(
        targets.SIDEBAR_PROMPT_TARGETS
    )
    assert not missing, (
        f"tab PropertyGroups that can submit but not refine: {sorted(missing)}"
    )


def test_every_target_path_is_rooted_somewhere_real():
    """A typo'd data path silently removes the button from that tab."""
    targets = _targets()
    for owner, target in targets.SIDEBAR_PROMPT_TARGETS.items():
        assert target.path, f"{owner} has no data path"
        head = target.path.split(".")[0]
        assert head in {"mixie_moodboard_sidebar", "hunyuan"}, (
            f"{owner} is rooted at an unknown scene property: {head}"
        )


def test_hunyuan_pro_refines_as_the_service_it_submits_as():
    """Pro's prompt submits job_type image_to_3d (generation_enqueue), so
    that is the profile it must be refined against."""
    targets = _targets()
    pro = targets.SIDEBAR_PROMPT_TARGETS["MixieHunyuanProProps"]
    assert pro.fallback_service == "image_to_3d"


# ---------------------------------------------------------------------------
# Service/model resolution
# ---------------------------------------------------------------------------


def _scene_with(owner_type, **props):
    """A stand-in scene exposing one tab at its declared path."""
    targets = _targets()
    target = targets.SIDEBAR_PROMPT_TARGETS[owner_type]
    leaf = SimpleNamespace(**props)
    parts = target.path.split(".")
    node = leaf
    for part in reversed(parts[1:]):
        node = SimpleNamespace(**{part: node})
    return SimpleNamespace(**{parts[0]: node})


def test_an_unknown_owner_is_not_refinable():
    targets = _targets()
    scene = SimpleNamespace()
    assert targets.sidebar_generation_target(scene, "SomethingElse") is None
    assert targets.sidebar_generation_target(scene, "") is None


def test_a_missing_tab_is_not_refinable():
    """A path that does not resolve must produce no target rather than a
    half-built one addressed at None."""
    targets = _targets()
    assert (
        targets.sidebar_generation_target(SimpleNamespace(), "MixieMoodboardTabVideoGenProps")
        is None
    )


def test_the_fallback_service_answers_when_the_catalog_cannot(monkeypatch):
    """Offline / pre-auth: the tab still refines, against its own service."""
    targets = _targets()
    monkeypatch.setattr(
        targets, "sidebar_generation_target",
        targets.sidebar_generation_target,
    )
    scene = _scene_with("MixieMoodboardTabVideoGenProps", prompt="", mode="", model="")
    service, _model = targets.sidebar_generation_target(
        scene, "MixieMoodboardTabVideoGenProps"
    )
    # resolve_service_key returns None with no catalog loaded under the mock.
    assert service == "video_gen"


# ---------------------------------------------------------------------------
# Refine / Revert behaviour
# ---------------------------------------------------------------------------


class _FakeSlot:
    """A prompt field with no Blender behind it."""

    def __init__(self, text="a knight"):
        self.text = text
        self.key = "fake"
        self.service_key = "image_gen"
        self.model_slug = "some-model"
        self._stash = None
        self.running = False

    def read(self):
        return self.text

    def write(self, text):
        self.text = text

    def stash(self, original):
        self._stash = original

    def stashed(self):
        return self._stash or ""

    def has_stash(self):
        return self._stash is not None

    def clear_stash(self):
        self._stash = None

    def set_running(self, running):
        self.running = running

    def is_running(self):
        return self.running

    def alive(self):
        return True


def _install_service(monkeypatch, responder):
    """Route refine_async at *responder(prompt) -> payload | Exception*."""
    engine = _engine()

    class _Service:
        def refine_async(self, prompt, *, service_key="", model_slug="",
                         on_success=None, on_error=None, timeout=None):
            outcome = responder(prompt)
            if isinstance(outcome, Exception):
                on_error(outcome)
            else:
                on_success(SimpleNamespace(data={"data": outcome}))

    # A stub module rather than the real package: importing the API client
    # under the bpy mock drags in auth/keyring, and none of it is what these
    # tests are about.
    import types

    stub = types.ModuleType("mixar.modules.common.api.services")
    stub.get_prompt_refine_service = lambda: _Service()
    monkeypatch.setitem(
        sys.modules, "mixar.modules.common.api.services", stub
    )
    monkeypatch.setattr(engine, "redraw_prompt_surfaces", lambda: None)
    return engine


def test_a_refinement_replaces_the_prompt_and_can_be_reverted(monkeypatch):
    engine = _install_service(
        monkeypatch,
        lambda prompt: {"prompt": "A knight at dusk", "original_prompt": prompt},
    )
    slot = _FakeSlot("a knight")
    seen = []
    engine.refine(slot, lambda ok, msg: seen.append((ok, msg)))

    assert slot.text == "A knight at dusk"
    assert seen and seen[0][0] is True
    assert engine.revert(slot) is True
    assert slot.text == "a knight"
    # Reverting twice is not a second undo into nothing.
    assert engine.revert(slot) is False
    assert slot.text == "a knight"


def test_revert_restores_what_was_REFINED_not_what_is_in_the_field(monkeypatch):
    """The user can keep typing while the call is out. Reverting to a prompt
    that was never refined is not a revert."""
    engine = _install_service(
        monkeypatch,
        lambda prompt: {"prompt": "refined", "original_prompt": "the sent text"},
    )
    slot = _FakeSlot("the sent text")
    engine.refine(slot, lambda ok, msg: None)
    engine.revert(slot)
    assert slot.text == "the sent text"


def test_a_failed_refinement_leaves_the_prompt_alone(monkeypatch):
    engine = _install_service(monkeypatch, lambda prompt: RuntimeError("boom"))
    slot = _FakeSlot("a knight")
    seen = []
    engine.refine(slot, lambda ok, msg: seen.append((ok, msg)))

    assert slot.text == "a knight"
    assert seen and seen[0][0] is False
    assert slot.stashed() == ""
    assert slot.running is False


def test_an_empty_rewrite_never_reaches_the_field(monkeypatch):
    engine = _install_service(
        monkeypatch, lambda prompt: {"prompt": "  ", "original_prompt": prompt}
    )
    slot = _FakeSlot("a knight")
    engine.refine(slot, lambda ok, msg: None)
    assert slot.text == "a knight"
    assert slot.stashed() == ""


def test_an_unchanged_rewrite_offers_no_revert(monkeypatch):
    """Nothing happened; a Revert button would promise an undo of nothing."""
    engine = _install_service(
        monkeypatch,
        lambda prompt: {"prompt": "a knight", "original_prompt": "a knight"},
    )
    slot = _FakeSlot("a knight")
    seen = []
    engine.refine(slot, lambda ok, msg: seen.append((ok, msg)))
    assert slot.stashed() == ""
    assert seen[0][0] is True


def test_an_empty_prompt_is_never_sent(monkeypatch):
    sent = []
    engine = _install_service(
        monkeypatch,
        lambda prompt: sent.append(prompt) or {"prompt": "x", "original_prompt": prompt},
    )
    slot = _FakeSlot("   ")
    assert engine.refine(slot, lambda ok, msg: None) is False
    assert not sent


def test_a_second_click_while_one_is_in_flight_is_dropped(monkeypatch):
    engine = _engine()
    monkeypatch.setattr(engine, "redraw_prompt_surfaces", lambda: None)
    slot = _FakeSlot("a knight")
    slot.running = True
    assert engine.refine(slot, lambda ok, msg: None) is False


def test_the_in_flight_flag_is_cleared_on_every_path(monkeypatch):
    for responder in (
        lambda prompt: {"prompt": "b", "original_prompt": prompt},
        lambda prompt: RuntimeError("boom"),
        lambda prompt: {"prompt": "", "original_prompt": prompt},
    ):
        engine = _install_service(monkeypatch, responder)
        slot = _FakeSlot("a knight")
        engine.refine(slot, lambda ok, msg: None)
        assert slot.running is False


def test_a_409_says_the_feature_is_off_rather_than_inviting_a_retry():
    engine = _engine()
    message = engine._error_message(SimpleNamespace(status_code=409))
    assert "unavailable" in message.lower()
    assert "try again" not in message.lower()


# ---------------------------------------------------------------------------
# Node surface
# ---------------------------------------------------------------------------


def _annotated_members(path: Path, class_name: str) -> dict:
    """`name: Prop(...)` members of a class, as source text.

    Blender properties are ANNOTATIONS, not assignments — ``AnnAssign.value``
    is None and the declaration lives in ``.annotation``. Reading ``.value``
    here silently finds nothing, which makes a pin like this pass forever.
    """
    members = {}
    for node in ast.walk(ast.parse(_read(path))):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                target = getattr(stmt, "target", None)
                annotation = getattr(stmt, "annotation", None)
                if isinstance(target, ast.Name) and annotation is not None:
                    members[target.id] = ast.unparse(annotation)
    return members


class _NodeCollection(list):
    """A bpy CollectionProperty of graph nodes: ``remove(index)`` is what
    makes a held element pointer dangle."""

    def remove(self, index):
        del self[index]


def _graph_node(node_id="node-1", prompt="a knight"):
    return SimpleNamespace(
        # RNA answers `bl_rna` off the wrapper's cached TYPE, without ever
        # dereferencing the element -- which is why it keeps answering for a
        # collection entry that has been removed, and why a liveness check
        # built on it reads True on freed memory.
        bl_rna=object(),
        node_id=node_id,
        prompt=prompt,
        prompt_pre_refine="",
        prompt_refined=False,
        prompt_refining=False,
        show_prompt=True,
        service_key_id="image_gen",
        model_slug="flux",
    )


def test_a_node_slot_addresses_its_node_by_id_not_by_held_pointer():
    """A refine is a live round trip, and the node can be deleted while it is
    out. A collection element's RNA pointer dangles the moment the collection
    is edited, and ``bl_rna`` cannot see it -- it answers off the cached type
    without dereferencing the element -- so a liveness check through a stored
    pointer reads True and the write that follows lands on freed memory.
    Every other async path here re-resolves by id; so must this one."""
    engine = _engine()
    nodes = _NodeCollection([_graph_node()])
    scene = SimpleNamespace(mixie_moodboard_action_nodes=nodes)

    slot = engine.node_slot(scene, "node-1")
    assert slot is not None and slot.alive()
    assert slot.read() == "a knight"

    # The user deletes the card while the refinement is in flight.
    detached = nodes[0]
    nodes.remove(0)

    assert slot.alive() is False
    assert slot.read() == ""
    assert slot.has_stash() is False
    assert slot.is_running() is False

    # And every write is a no-op rather than a dangling assignment.
    slot.write("refined")
    slot.stash("a knight")
    slot.set_running(True)
    assert detached.prompt == "a knight"
    assert detached.prompt_pre_refine == ""
    assert detached.prompt_refining is False


def test_a_node_slot_survives_a_sibling_being_deleted():
    """Removing an earlier element shifts every later one down. Re-resolving
    by id has to keep addressing the SAME card, not whatever now sits at the
    index the slot was built from."""
    engine = _engine()
    nodes = _NodeCollection([_graph_node("node-0", "first"),
                             _graph_node("node-1", "second")])
    scene = SimpleNamespace(mixie_moodboard_action_nodes=nodes)

    slot = engine.node_slot(scene, "node-1")
    nodes.remove(0)

    assert slot.alive() is True
    slot.write("refined")
    assert nodes[0].node_id == "node-1"
    assert nodes[0].prompt == "refined"


def test_a_refinement_landing_after_the_node_is_gone_changes_nothing(monkeypatch):
    engine = _install_service(
        monkeypatch,
        lambda prompt: {"prompt": "A knight at dusk", "original_prompt": prompt},
    )
    nodes = _NodeCollection([_graph_node()])
    scene = SimpleNamespace(mixie_moodboard_action_nodes=nodes)
    slot = engine.node_slot(scene, "node-1")

    seen = []
    # The card is deleted between the click and the answer.
    detached = nodes[0]
    nodes.remove(0)
    engine.refine(slot, lambda ok, msg: seen.append((ok, msg)))

    assert nodes == []
    # An empty prompt is never sent, so the click reports rather than
    # refining a card that is no longer there.
    assert seen and seen[0][0] is False
    assert detached.prompt == "a knight"


def test_node_refine_state_lives_on_the_node_because_cpp_paints_the_card():
    """C++ chooses Refine vs Revert from RNA, so these props must exist and
    must not be serialized into the .blend."""
    members = _annotated_members(
        MOODBOARD / "ui/moodboard_graph_properties.py", "MixieMoodboardActionNode"
    )
    assert members, "expected the action node to declare properties"
    for name in ("prompt_pre_refine", "prompt_refined", "prompt_refining"):
        assert name in members, f"{name} missing from the action node"
        assert "SKIP_SAVE" in members[name], (
            f"{name} must be SKIP_SAVE — a reopened file offering to revert "
            f"to a previous session's prompt is a data loss, not an undo"
        )


def test_the_node_tile_draws_refine_and_revert_from_those_props():
    source = _read(TILE_CONTROLS)
    assert "MIXIE_OT_refine_prompt" in source
    assert "MIXIE_OT_revert_prompt" in source
    assert 'RNA_boolean_get(node, "prompt_refined")' in source
    assert 'RNA_boolean_get(node, "prompt_refining")' in source
    # Scoped to THIS node, like every other per-card button.
    assert source.count('RNA_string_set(ui::button_operator_ptr_ensure(refine), "node_id"')


def test_the_refine_operators_keep_their_props_skip_save():
    """REGISTER operators refill unset props from the previous run, so an
    unscoped Refine would re-refine whichever node was refined last."""
    path = MOODBOARD / "ui/operators/prompt_refine_ops.py"
    checked = 0
    for class_name in ("MIXIE_OT_refine_prompt", "MIXIE_OT_revert_prompt"):
        members = _annotated_members(path, class_name)
        assert {"node_id", "owner"} <= set(members), (
            f"{class_name} must address a node OR a sidebar tab"
        )
        for prop in ("node_id", "owner"):
            assert "SKIP_SAVE" in members[prop], (
                f"{class_name}.{prop} must be SKIP_SAVE"
            )
            checked += 1
    assert checked == 4


def test_the_sidebar_row_is_drawn_by_the_one_shared_prompt_helper():
    """Every tab prompt goes through draw_prompt_section, which is why the
    button is added there and not in each drawer. The row itself lives in its
    own module only because of the 500-line rule."""
    assert "draw_prompt_refine_row" in _read(MOODBOARD / "ui/sidebar_ui_helpers.py")
    row = _read(MOODBOARD / "ui/prompt_refine_drawer.py")
    assert "mixie.refine_prompt" in row and "mixie.revert_prompt" in row


# ---------------------------------------------------------------------------
# Refine survives its own success — both surfaces, one stash
# ---------------------------------------------------------------------------

def test_a_second_refinement_still_reverts_to_the_USERS_words(monkeypatch):
    """Refine stays available after a rewrite, so it can run again. Revert
    means "put back what I wrote", never "step back one refinement"."""
    engine = _install_service(
        monkeypatch,
        lambda prompt: {"prompt": prompt + "+", "original_prompt": prompt},
    )
    slot = _FakeSlot("a knight")
    engine.refine(slot, lambda ok, msg: None)
    assert slot.text == "a knight+"
    engine.refine(slot, lambda ok, msg: None)
    assert slot.text == "a knight++"

    assert engine.revert(slot) is True
    assert slot.text == "a knight"


def test_an_unchanged_SECOND_rewrite_keeps_the_first_revert(monkeypatch):
    """The no-op branch must not clear a stash it did not create — that undo
    is still real."""
    replies = iter(
        [
            {"prompt": "refined", "original_prompt": "a knight"},
            {"prompt": "refined", "original_prompt": "refined"},
        ]
    )
    engine = _install_service(monkeypatch, lambda prompt: next(replies))
    slot = _FakeSlot("a knight")
    engine.refine(slot, lambda ok, msg: None)
    engine.refine(slot, lambda ok, msg: None)

    assert engine.revert(slot) is True
    assert slot.text == "a knight"


def test_reverting_to_an_empty_prompt_is_a_real_revert(monkeypatch):
    """`has_stash` exists precisely so "" is not read as "nothing to undo".

    Revert is asked directly: `refine` never stashes an empty original (it
    falls back to the text it sent, and an empty prompt is never sent), but
    the node's stash is a capped RNA string and a prompt can legitimately be
    written back to nothing.
    """
    engine = _engine()
    monkeypatch.setattr(engine, "redraw_prompt_surfaces", lambda: None)
    slot = _FakeSlot("refined")
    slot.stash("")
    assert engine.revert(slot) is True
    assert slot.text == ""
    # And the stash is spent, so a second press is not an undo into nothing.
    assert engine.revert(slot) is False


def test_the_node_tile_keeps_refine_beside_revert():
    """A refined card draws BOTH: Revert takes the user's words back, Refine
    runs another pass. Refine is never swapped out for Revert."""
    source = _read(TILE_CONTROLS)
    # One unconditional Refine button, and a Revert added only when refined.
    assert source.count('"MIXIE_OT_refine_prompt"') == 1
    assert source.count('"MIXIE_OT_revert_prompt"') == 1
    assert 'refined ? "MIXIE_OT_revert_prompt" : "MIXIE_OT_refine_prompt"' not in (
        source
    ), "the two buttons must coexist, not alternate"
    # Both are scoped to THIS card.
    assert 'RNA_string_set(ui::button_operator_ptr_ensure(refine), "node_id"' in source
    assert 'RNA_string_set(ui::button_operator_ptr_ensure(revert), "node_id"' in source


def test_the_sidebar_row_keeps_refine_beside_revert():
    """Same shape as the card, and Refine's disabled state must not reach
    Revert — a Revert you cannot press is the one affordance that must
    survive once a rewrite has landed."""
    row = _read(MOODBOARD / "ui/prompt_refine_drawer.py")
    assert "return" not in row.split("can_revert = ")[1].split("if can_revert")[0], (
        "drawing Revert must not short-circuit the Refine button"
    )
    assert "refine_row.enabled" in row, (
        "Refine needs its own sub-row; `enabled` applies to a whole layout item"
    )


def test_revert_refuses_while_a_refinement_is_in_flight(monkeypatch):
    """Reverting mid-flight would clear the stash, and the landing response
    would then re-stash the PREVIOUS refinement as if it were the user's
    words — so the guard is in the engine, not in either UI surface."""
    engine = _engine()
    monkeypatch.setattr(engine, "redraw_prompt_surfaces", lambda: None)
    slot = _FakeSlot("refined once")
    slot.stash("a knight")
    slot.running = True
    assert engine.revert(slot) is False
    assert slot.text == "refined once" and slot.stashed() == "a knight"
    slot.running = False
    assert engine.revert(slot) is True
    assert slot.text == "a knight" and slot.has_stash() is False


def test_sidebar_state_is_scoped_to_the_owning_scene():
    """The sidebar props are registered per Scene, so a stash keyed by tab
    alone would let Scene B revert to Scene A's prompt."""
    engine = _engine()
    engine.forget_sidebar_state()
    owner_a = SimpleNamespace(prompt="x", id_data=SimpleNamespace(name="Scene A", session_uid=11))
    owner_b = SimpleNamespace(prompt="y", id_data=SimpleNamespace(name="Scene B", session_uid=12))
    slot_a = engine.SidebarSlot(owner_a, "MixieTab", "image_gen", "m")
    slot_a.stash("a knight")
    slot_a.set_running(True)
    try:
        assert engine.sidebar_can_revert(owner_a, "MixieTab") is True
        assert engine.sidebar_is_refining(owner_a, "MixieTab") is True
        assert engine.sidebar_can_revert(owner_b, "MixieTab") is False
        assert engine.sidebar_is_refining(owner_b, "MixieTab") is False
        engine.forget_sidebar_state(owner_b, "MixieTab")
        assert engine.sidebar_can_revert(owner_a, "MixieTab") is True
        # A rename within the session does not orphan the stash.
        owner_a.id_data.name = "Scene A renamed"
        assert engine.sidebar_can_revert(owner_a, "MixieTab") is True
    finally:
        engine.forget_sidebar_state()
    assert engine.sidebar_can_revert(owner_a, "MixieTab") is False
