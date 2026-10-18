# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auto-assign: score ASSEMBLIES (``assemblies.Hierarchy``) by the root's
name and its parts' names, and tag the root.

    score(role) = Σ weight of the role's words in the root name
                + 2 × (share of parts whose names hold one of the role's words)

A role needs ``THRESHOLD``. Some roles refuse an assembly whose name or
parts mostly say it is something else (``NEGATIVE``): a "PickupSign" built
of Board/Plinth/Pole parts is a sign, not a collectible. ``player``,
``goal`` and ``spawn`` go to the single best-scoring assembly (a Finish
beats a mailbox flag; exactly one player); the others go to every
assembly over the threshold — except that once an assembly is NAMED as a
role (a root word of weight ``STRONG_WORD``: Token, Coin…), weak matches
for that role (a "DeliveryPickup" station) are dropped. A one-part assembly that is a large flat mesh
is ground (``static``). Explicitly tagged assemblies are left alone unless
``overwrite``.
"""

from __future__ import annotations

from .assemblies import Hierarchy
from .roles import get_role, is_large_flat, name_words

VOCAB = {
    "player": {"hero": 3, "player": 3, "character": 3, "avatar": 3, "protagonist": 3,
               "bike": 3, "bicycle": 3, "car": 2, "vehicle": 2, "kart": 2},
    "collectible": {"token": 3, "coin": 3, "gem": 3, "orb": 3, "star": 3, "crystal": 3, "jewel": 3,
                    "collectible": 3, "pickup": 2, "bolt": 1},
    "goal": {"finish": 4, "goal": 4, "exit": 3, "portal": 3, "dropoff": 2, "flag": 1},
    "spawn": {"spawn": 4, "spawnpoint": 4, "start": 3},
    "hazard": {"spike": 3, "lava": 3, "hazard": 3, "trap": 3, "acid": 3, "saw": 2, "pothole": 2},
    "enemy": {"enemy": 3, "monster": 3, "zombie": 3, "slime": 3, "foe": 3, "goblin": 3},
    "prop": {"crate": 2, "barrel": 2, "box": 1, "ball": 2, "cone": 2},
    "decor": {"cloud": 2, "grass": 2, "flower": 2, "decor": 3, "decoration": 3},
}
# Words that say "this is a sign/fixture", refusing the role when they name
# the root or at least half of the parts.
NEGATIVE = {"collectible": {"sign", "board", "plinth", "pole", "post", "poster", "banner", "stand"}}
SINGLE = ("player", "goal", "spawn")  # one assembly each
THRESHOLD = 2.0
PART_WEIGHT = 2.0
STRONG_WORD = 3  # a root word this heavy names the role outright


def _root_words(root) -> set:
    return set(name_words(getattr(root, "name", "")))


def score_assembly(root, parts) -> dict:
    """``{role: score}`` for one assembly (roles scoring 0 omitted)."""
    root_words = _root_words(root)
    part_words = [set(name_words(getattr(p, "name", ""))) for p in parts if p is not root]
    scores = {}
    for role, vocab in VOCAB.items():
        score = sum(weight for word, weight in vocab.items() if word in root_words)
        if part_words:
            share = sum(1 for words in part_words if words & vocab.keys()) / len(part_words)
            score += PART_WEIGHT * share
        negative = NEGATIVE.get(role)
        if negative and (root_words & negative or (
                part_words and sum(1 for w in part_words if w & negative) >= 0.5 * len(part_words))):
            score = 0.0
        if score > 0:
            scores[role] = round(score, 3)
    return scores


def _root_weight(root, role: str) -> int:
    words = _root_words(root)
    return max((w for word, w in VOCAB.get(role, {}).items() if word in words), default=0)


def _best(scores: dict):
    role = max(scores, key=lambda r: (scores[r], -list(VOCAB).index(r)), default=None)
    return (role, scores[role]) if role and scores[role] >= THRESHOLD else (None, 0.0)


def suggest_role(name: str, obj_type: str, dimensions=(0.0, 0.0, 0.0)) -> tuple[str | None, str]:
    """Single loose object: ``(role, reason)`` from its name / shape."""
    if obj_type not in ("MESH", "EMPTY"):
        return None, ""
    if obj_type == "MESH" and is_large_flat(dimensions):
        return "static", "large flat mesh"
    scores = score_assembly(type("Loose", (), {"name": name})(), [])
    if obj_type == "EMPTY":
        scores = {r: s for r, s in scores.items() if r == "spawn"}
    role, _score = _best(scores)
    return (role, "name") if role else (None, "")


def _tagged(hierarchy: Hierarchy, root) -> bool:
    """The user decided this asset: its root is tagged, or a part inside it
    was tagged on purpose ("This part only"). A part tag without that mark
    is stale (the old per-part auto-assign) and does not count."""
    from .roles import is_deliberate_part
    return bool(get_role(root)) or any(get_role(p) and is_deliberate_part(p)
                                       for p in hierarchy.descendants(root))


def _deliberate(obj) -> bool:
    from .roles import is_deliberate_part
    return is_deliberate_part(obj)


def suggest_roles(objects, overwrite: bool = False) -> list[dict]:
    """Suggestions ``[{object, role, reason, parts}]`` for the assemblies of
    ``objects`` (``object`` is the assembly root to tag)."""
    hierarchy = Hierarchy(objects)
    candidates, taken = [], {role: False for role in SINGLE}
    for root in hierarchy.assemblies():
        if getattr(root, "type", "") not in ("MESH", "EMPTY"):
            continue
        if _tagged(hierarchy, root) and not overwrite:
            for role in SINGLE:
                if get_role(root) == role or any(get_role(o) == role and _deliberate(o)
                                                 for o in hierarchy.descendants(root)):
                    taken[role] = True
            continue
        parts = hierarchy.parts(root)
        if hierarchy.is_container(root) or (not parts and getattr(root, "type", "") != "EMPTY"):
            continue
        if not hierarchy.children(root):  # a loose object
            role, reason = suggest_role(root.name, root.type, tuple(getattr(root, "dimensions", (0, 0, 0))))
            score = THRESHOLD if role else 0.0
        else:
            role, score = _best(score_assembly(root, parts))
            reason = "assembly name and parts"
        if role:
            candidates.append({"object": root.name, "role": role, "reason": reason,
                               "parts": len(parts), "score": score,
                               "strong": _root_weight(root, role) >= STRONG_WORD})
    # When an assembly is NAMED a clear collectible (Token, Coin, Gem…), ones
    # that only match weakly (a "Pickup" station, a part called Bolt) are not.
    strong = {c["role"] for c in candidates if c["strong"]}
    for item in candidates:
        if item["role"] in strong and item["role"] not in SINGLE and not item["strong"]:
            item["role"], item["reason"] = None, f"weaker than the assets named as a {item['role']}"
    for role in SINGLE:  # the best one only
        group = [c for c in candidates if c["role"] == role]
        if not group:
            continue
        best = max(group, key=lambda c: c["score"])
        for item in group:
            if item is not best or taken[role]:
                item["role"] = None
                item["reason"] = (f"another assembly is already the {role}" if taken[role]
                                  else f"{best['object']} is a better {role}")
    return [{k: v for k, v in c.items() if k not in ("score", "strong")} for c in candidates]
