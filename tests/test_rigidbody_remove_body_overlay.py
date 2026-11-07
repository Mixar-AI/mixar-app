# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins `src/intern/rigidbody/rb_bullet_api.cpp`, upstream's file plus the
hunks fenced by `/* MIXAR-1822 begin */ ... /* MIXAR-1822 end */` and lines
tagged `/* MIXAR-1822 */` (mixar-backend#1822). An add-on's tests that delete
rigid bodies aborted the app mid-verification:

* `RB_dworld_remove_body` leaves a Bullet world alone unless the body is in
  it. Deleting a rigid-body object's ID (`bpy.data.objects.remove`) calls it
  for EVERY scene's world, and Bullet's `removeCollisionObject` assumes
  ownership: it destroyed the body's broadphase proxy inside another scene's
  broadphase and swap-removed an unrelated object from that world.
* A constraint keeps its bodies alive. Blender frees a constraint's bodies and
  the constraint in any order (the bodies' objects before the constraint's,
  the world or scene first, a batch delete, closing the file) and frees a
  constraint without taking it out of its world, so Bullet read freed bodies
  in `RB_constraint_delete` or stepped a freed constraint. A deleted body now
  takes its constraints out of their worlds and stays allocated until its last
  constraint is deleted; a deleted constraint leaves its world first.

Delete a hunk once upstream fixes its bug. Replayed in the app by the QA
harness (ADDON-11 to ADDON-13)."""

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/intern/rigidbody/rb_bullet_api.cpp"
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_CANDIDATES = (
    ROOT / "upstream/intern/rigidbody/rb_bullet_api.cpp",
    ROOT.parents[1] / "upstream/intern/rigidbody/rb_bullet_api.cpp",
)
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
MARKED = re.compile(r"[ \t]*/\* MIXAR-1822 begin \*/\n.*?[ \t]*/\* MIXAR-1822 end \*/\n", re.S)
TAGGED = re.compile(r"^[^\n]*/\* MIXAR-1822 \*/\n", re.M)
REMOVE_CALL = "  world->dynamicsWorld->removeRigidBody(body);\n"
GUARD = (
    "  const btCollisionObjectArray &objects = world->dynamicsWorld->getCollisionObjectArray();\n"
    "  const int index = body->getWorldArrayIndex();\n"
    "  if (index < 0 || index >= objects.size() || objects[index] != body) {\n"
    "    return;\n"
    "  }\n"
)
CONSTRAINT_RETURN = "  return (rbConstraint *)con;\n"
LINK_BODIES = "  mixar_constraint_link_bodies(con); /* MIXAR-1822 */\n"
# sha256 (first 16 hex) of upstream's text of the functions whose constraint
# lifetimes the overlay changes, at the v5.2.0 pin (fbe6228777e7).
LIFETIME_FUNCTIONS = {
    "RB_body_delete": "f5824e47746883ff",
    "RB_constraint_delete": "a7ad7eea9ffa4141",
}

LOCK = "std::lock_guard<std::mutex> lock(mixar_links_mutex());"

def _strip_comments(text: str) -> str:
    return re.sub(r"[ \t]*/\*.*?\*/\n?", "", text, flags=re.S)


def _function(text: str, name: str) -> str:
    start = text.index(f" {name}(")
    start = text.rindex("\n", 0, start) + 1
    return text[start:text.index("\n}\n", start) + 3]


def _overlay_function(name: str) -> str:
    return _strip_comments(_function(OVERLAY.read_text(encoding="utf-8"), name))


def _unpatched(text: str) -> str:
    return TAGGED.sub("", MARKED.sub("", text.replace(MIXAR_SPDX, "", 1)))


def _ordered(text: str, *parts: str) -> bool:
    positions = [text.find(part) for part in parts]
    return -1 not in positions and positions == sorted(positions)


def test_remove_body_checks_the_world_holds_the_body_first():
    body = _overlay_function("RB_dworld_remove_body")
    assert _ordered(body, GUARD, REMOVE_CALL)
    assert body.count("removeRigidBody") == 1


def test_a_deleted_body_stays_allocated_while_a_constraint_uses_it():
    body = _overlay_function("RB_body_delete")
    assert _ordered(
        body,
        LOCK,
        "body->removeConstraintRef(con);",
        "mixar_body_links().find(body)",
        "mixar_constraint_leave_world(con);",
        "it->second.deleted = true;",
        "body->setMotionState(nullptr);",
        "delete object;\n    return;",
        "  delete body;\n  delete object;\n}",
    )
    assert body.count("delete body;") == 1
    # RB_constraint_delete edits the same constraint refs: one lock, held to the end.
    assert body.count("lock_guard") == 1


def test_a_deleted_constraint_leaves_its_world_then_frees_deleted_bodies():
    body = _overlay_function("RB_constraint_delete")
    assert _ordered(
        body,
        LOCK,
        "mixar_body_a = &constraint->getRigidBodyA();",
        "mixar_body_b = &constraint->getRigidBodyB();",
        "mixar_constraint_leave_world(constraint);",
        "removeConstraintRef(constraint);",
        "delete constraint;",
        "for (btRigidBody *body : {mixar_body_a, mixar_body_b})",
        "cons.erase(pos);",
        "if (deleted) {\n        delete body;",
    )
    # A constraint whose bodies are one body must not free it twice.
    assert _ordered(body, "mixar_body_links().erase(it);", "if (deleted)")
    # Copy-on-eval frees run on several threads: no unlocked gap between the two hunks.
    assert body.count("lock_guard") == 1


def test_every_constraint_constructor_links_its_bodies():
    text = OVERLAY.read_text(encoding="utf-8")
    returns = text.count(CONSTRAINT_RETURN)
    assert returns == 9
    assert text.count(LINK_BODIES + CONSTRAINT_RETURN) == returns
    assert text.count("mixar_constraint_link_bodies(") == returns + 1


def test_worlds_track_the_constraints_added_to_them():
    add = _overlay_function("RB_dworld_add_constraint")
    # A constraint built on a deleted body never goes back into a world.
    assert _ordered(
        add,
        LOCK,
        "mixar_body_deleted(&constraint->getRigidBodyA())",
        "mixar_body_deleted(&constraint->getRigidBodyB())",
        "return;",
        "addConstraint(constraint",
        "mixar_constraint_worlds()[constraint] =",
    )
    assert add.count("lock_guard") == 1
    remove = _overlay_function("RB_dworld_remove_constraint")
    assert _ordered(remove, "removeConstraint(constraint)", "mixar_constraint_worlds().erase(it)")
    delete = _overlay_function("RB_dworld_delete")
    assert _ordered(delete, "worlds.erase(it)", "delete world->dynamicsWorld;")


def test_the_overlay_is_upstream_plus_the_marked_hunks():
    """Keep every change fenced so an upstream bump is a re-copy plus re-apply."""
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        pytest.skip("upstream submodule not checked out")
    up = upstream.read_text(encoding="utf-8")
    if "getWorldArrayIndex" in _function(up, "RB_dworld_remove_body"):
        pytest.fail("upstream now guards RB_dworld_remove_body: delete the overlay's guard hunk")
    for name, digest in LIFETIME_FUNCTIONS.items():
        if hashlib.sha256(_function(up, name).encode()).hexdigest()[:16] != digest:
            pytest.fail(
                f"upstream changed {name}: if it now keeps a constraint's bodies alive until the "
                "constraint is deleted (mixar-backend#1822), delete the overlay's lifetime hunks; "
                "otherwise re-copy the file, re-apply the MIXAR-1822 hunks and update the digest"
            )
    ov = OVERLAY.read_text(encoding="utf-8")
    assert ov.count("/* MIXAR-1822 begin */") == ov.count("/* MIXAR-1822 end */") > 0
    assert MIXAR_SPDX in ov
    unpatched = _unpatched(ov)
    if unpatched != up:
        old, new = unpatched.splitlines(), up.splitlines()
        line = next((i for i, pair in enumerate(zip(old, new)) if pair[0] != pair[1]), min(len(old), len(new)))
        pytest.fail(
            "upstream rb_bullet_api.cpp changed (first difference at upstream line "
            f"{line + 1}), or an overlay edit is not fenced: re-copy the upstream file and "
            "re-apply the MIXAR-1822 hunks",
            pytrace=False,
        )
