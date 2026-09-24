# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Default slot, hold, size and grip of an Assemble part, read from its name.

Only AUTO rows use these, and only as a fallback: the Character Sheet template
writes explicit rows, and a generic label such as "Left-hand item" carries no
keyword at all. Matching is whole-word and case-insensitive, and the first
matching rule wins, so longer phrases ("greatsword", "crossbow") come before
the words they contain. Sizes are the longest dimension as a percentage of the
body height, or of the head width for head slots. ``grip`` is the fraction of
the length from the grip end; None holds the part at its bounding-box centre.
"""

from collections import namedtuple
import re

Rule = namedtuple("Rule", "keywords cls slot hold size_pct grip keep_axis")


def _rule(keywords, cls, slot, hold, size_pct, grip=None, keep_axis=False):
    return Rule(tuple(keywords), cls, slot, hold, float(size_pct), grip, keep_axis)


KEYWORD_RULES = (
    _rule(("dagger", "knife", "katar", "kukri", "dirk", "khanjar"),
          'long', 'HAND_R', 'POINT', 18, 0.18),
    _rule(("greatsword", "claymore", "zweihander", "two-handed sword"),
          'long', 'HAND_R', 'POINT', 72, 0.14),
    _rule(("sword", "talwar", "tulwar", "khanda", "sabre", "saber", "scimitar",
           "katana", "cutlass", "rapier", "blade"),
          'long', 'HAND_R', 'POINT', 52, 0.10),
    _rule(("greataxe", "battleaxe", "battle axe", "halberd"),
          'long', 'HAND_R', 'UPRIGHT', 100, 0.30),
    _rule(("warhammer", "maul"), 'long', 'HAND_R', 'POINT', 70, 0.25),
    _rule(("axe", "hatchet"), 'long', 'HAND_R', 'POINT', 32, 0.18),
    _rule(("mace", "club"), 'long', 'HAND_R', 'POINT', 38, 0.18),
    _rule(("wrench", "spanner", "hammer"), 'long', 'HAND_R', 'POINT', 25, 0.18),
    _rule(("screwdriver",), 'long', 'HIP_R', None, 12),
    _rule(("wand",), 'long', 'HAND_R', 'POINT', 17, 0.25),
    _rule(("scepter", "sceptre"), 'long', 'HAND_R', 'UPRIGHT', 35, 0.30),
    _rule(("lance",), 'long', 'HAND_R', 'POINT', 180, 0.25),
    _rule(("spear", "javelin", "trident"), 'long', 'HAND_R', 'UPRIGHT', 120, 0.40),
    _rule(("walking stick",), 'long', 'HAND_R', 'UPRIGHT', 55, 0.95),
    _rule(("staff", "stave"), 'long', 'HAND_R', 'UPRIGHT', 105, 0.45),
    _rule(("crossbow",), 'long', 'HAND_R', 'POINT', 45, 0.30),
    _rule(("longbow",), 'long', 'HAND_L', 'UPRIGHT', 100, 0.50),
    _rule(("bow", "dhanush", "recurve"), 'long', 'HAND_L', 'UPRIGHT', 72, 0.50),
    _rule(("tower shield",), 'flat', 'FOREARM_L', 'FACE_OUT', 80),
    _rule(("kite shield", "heater"), 'flat', 'FOREARM_L', 'FACE_OUT', 55),
    _rule(("buckler",), 'flat', 'HAND_L', 'FACE_OUT', 20),
    _rule(("dhal",), 'flat', 'HAND_L', 'FACE_OUT', 30),
    _rule(("shield",), 'flat', 'FOREARM_L', 'FACE_OUT', 48),
    _rule(("quiver", "tarkash"), 'long', 'BACK', None, 45),
    _rule(("scabbard", "sheath", "myaan"), 'long', 'HIP_L', None, 55),
    _rule(("backpack", "rucksack", "pack"), 'compact', 'BACK', None, 32),
    # A bedroll lies across the back: never stand its long axis up.
    _rule(("bedroll",), 'long', 'BACK', None, 38, keep_axis=True),
    _rule(("saddlebag", "pannier"), 'compact', 'HIP_L', None, 25),
    _rule(("pouch", "satchel", "bag"), 'compact', 'HIP_R', None, 10),
    _rule(("orb", "crystal ball", "sphere"), 'compact', 'FLOAT_L', None, 11),
    _rule(("lantern",), 'compact', 'HAND_L', 'AS_IS', 20),
    _rule(("book", "tome", "grimoire"), 'compact', 'HAND_L', 'AS_IS', 17),
    _rule(("goggles",), 'compact', 'HEAD_FRONT', None, 95),
    _rule(("crown", "circlet", "tiara"), 'compact', 'HEAD_TOP', None, 100),
    _rule(("sarpech", "kalgi", "plume", "turban ornament", "jewel", "brooch"),
          'compact', 'HEAD_FRONT', None, 90),
)

# Enclose a joint or replace a body surface: these belong to the body mesh.
BODY_WORDS = frozenset({
    "turban", "pagri", "safa", "sash", "patka", "kamarband", "belt", "gauntlet",
    "glove", "bracer", "boot", "helmet", "hood", "mask", "horn", "pauldron",
    "armour", "armor", "robe", "cloak", "cape", "hair", "beard", "tail",
    "necklace",
})


# Anatomical regions of the body itself. A generated head, torso or hand is
# skin that must be JOINED into one mesh before the rig (the agent's region
# mode); bone-parenting it like a prop tears at the seam, so AUTO skips it.
REGION_WORDS = frozenset({
    "head", "face", "skull", "neck", "torso", "chest", "trunk", "abdomen", "body",
    "arm", "upper arm", "forearm", "hand", "fist", "palm", "leg", "thigh", "shin",
    "calf", "foot", "feet", "pelvis", "waist", "upper body", "lower body",
})
# Words that make a label an ITEM even when it names a region ("Right-hand item").
_ITEM_WORDS = frozenset({"item", "items", "prop", "props", "weapon", "tool", "ornament",
                         "jewel", "accessory", "gear", "equipment"})


def normalize_label(label: str) -> str:
    """Lower case with hyphens, underscores and runs of spaces folded to one space."""
    return " ".join(re.sub(r"[_\-]+", " ", str(label or "")).lower().split())


def _pattern(words) -> "re.Pattern":
    phrases = sorted({normalize_label(word) for word in words}, key=len, reverse=True)
    body = "|".join(re.escape(phrase) for phrase in phrases)
    # A plural still names the item ("Swords", "Axes").
    return re.compile(rf"\b(?:{body})(?:e?s)?\b")


_RULE_PATTERNS = tuple((_pattern(rule.keywords), rule) for rule in KEYWORD_RULES)
_BODY_PATTERNS = tuple((_pattern((word,)), word) for word in sorted(BODY_WORDS))
_LEFT_HANDED = re.compile(r"\bleft handed\b")
_HAND_SIDE = re.compile(r"\b(left|right) hand\b")
_SIDE = re.compile(r"\b(left|right)\b")
_SLOT_WORDS = (
    (re.compile(r"\bback\b"), 'BACK'),
    (re.compile(r"\b(?:hip|belt)\b"), 'HIP_L'),
    (re.compile(r"\bhead\b"), 'HEAD_FRONT'),
)


def match_rule(label: str):
    """The first keyword rule whose word or phrase occurs in *label*, or None."""
    text = normalize_label(label)
    return next((rule for pattern, rule in _RULE_PATTERNS if pattern.search(text)), None)


def side_override(label: str) -> dict:
    """What the label's side words say about the slot.

    ``slot`` is a whole slot named by the label ("right hand" -> HAND_R, "back"
    -> BACK, "belt" -> HIP_L, "head" -> HEAD_FRONT), ``side`` a bare side word
    ('R'/'L') applied to whatever sided slot is chosen, and ``swap_hands`` asks
    for every sided slot to move to the other side ("left-handed").
    """
    text = normalize_label(label)
    swap = bool(_LEFT_HANDED.search(text))
    text = _LEFT_HANDED.sub(" ", text)
    out = {'slot': '', 'side': '', 'swap_hands': swap}
    hand = _HAND_SIDE.search(text)
    side = _SIDE.search(text)
    if side is not None:
        out['side'] = 'L' if side.group(1) == 'left' else 'R'
    if hand is not None:
        out['side'] = 'L' if hand.group(1) == 'left' else 'R'
        out['slot'] = f"HAND_{out['side']}"
        return out
    for pattern, slot in _SLOT_WORDS:
        if pattern.search(text):
            out['slot'] = slot
            break
    return out


def body_word(label: str):
    """The stays-on-body word that occurs first in *label*, or None."""
    text = normalize_label(label)
    hits = [(match.start(), word) for pattern, word in _BODY_PATTERNS
            if (match := pattern.search(text))]
    return min(hits)[1] if hits else None


_REGION_PATTERN = None


def region_word(label: str):
    """The body-region word *label* names, or None when it names an item.

    A label that matches a keyword rule ("hand axe", "head goggles") or carries
    an item word ("Right-hand item") is an item, never a region.
    """
    global _REGION_PATTERN
    if _REGION_PATTERN is None:
        _REGION_PATTERN = _pattern(REGION_WORDS)
    text = normalize_label(label)
    if match_rule(text) is not None or body_word(text) is not None:
        return None
    if _ITEM_WORDS & set(text.split()):
        return None
    match = _REGION_PATTERN.search(text)
    return match.group(0) if match else None


def region_note(label: str) -> str:
    """Why Assemble skips a body-region part on an AUTO slot ('' for an item)."""
    region = region_word(label)
    if not region:
        return ""
    return (f"'{region}' is part of the body: join it into the body mesh before Auto Rig "
            "(Assemble attaches rigid props only; pick a Slot to force it)")
