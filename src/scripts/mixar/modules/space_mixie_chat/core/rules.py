# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scoped Rules stores, stable IDs, snapshots and legacy message prefixes.

File rules persist in scene.mixie_chat_rules; globals live in rules_global.
Snapshots include disabled entries. Legacy prefixes contain enabled text only
and change on a first send or when the ruleset changes, never in the visible
user bubble. Legacy text/list stores migrate IDs on their next mutation.
"""

import hashlib
import json
import uuid

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

RULES_HEADER = (
    "[PROJECT RULES — the user has defined these rules for this project. "
    "Follow them for the entire session.]"
)

RULES_UPDATE_HEADER = (
    "[PROJECT RULES UPDATED — the user has changed the project rules "
    "mid-session. The rules below are the CURRENT and COMPLETE set, and "
    "they REPLACE ALL project rules given earlier in this conversation. "
    "If an earlier rule conflicts with these, follow these. If an "
    "earlier rule is absent from this set, the user has removed or "
    "disabled it — stop following it. From now on, follow exactly these "
    "rules and no others.]"
)

RULES_REMOVED_NOTE = (
    "[PROJECT RULES REMOVED — the user has removed or disabled all "
    "project rules. Stop following every project rule given earlier in "
    "this conversation; from now on there are no project rules.]"
)

# Closes every rules block on the wire. The backend's generation gates
# extract the CURRENT ruleset from conversation history (so a rule like
# "only use Hunyuan Pro" suppresses model-choice asks on later turns) —
# this marker lets them cut the block exactly instead of swallowing the
# user's prompt that follows it.
RULES_END_MARKER = "[END PROJECT RULES]"


def parse_rules(raw: str, scope: str = "project") -> list:
    """Parse entries into ``[{"id": ..., "text": ..., "enabled": ...}]``.

    Accepts the JSON list format and, for backward compatibility, a legacy
    plain-text value (returned as a single enabled rule). Never raises.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                rules = []
                occurrences = {}
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get("text", "")).strip()
                    if text:
                        occurrence = occurrences.get(text, 0)
                        occurrences[text] = occurrence + 1
                        rule_id = item.get("id")
                        if not isinstance(rule_id, str) or not rule_id:
                            rule_id = legacy_rule_id(scope, text, occurrence)
                        rules.append({"id": rule_id, "text": text,
                                      "enabled": bool(item.get("enabled", True))})
                return rules
        except (ValueError, TypeError):
            logger.debug("rules store parse failed; treating as legacy text")
    return [{"id": legacy_rule_id(scope, raw, 0), "text": raw, "enabled": True}]


def legacy_rule_id(scope: str, text: str, occurrence: int) -> str:
    """Stable until first mutation persists IDs; unrelated rules cannot shift it."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(
        ["mixar-rule-v1", scope, text, occurrence], ensure_ascii=False)))


def serialize_rules(rules: list) -> str:
    """Serialize the rule list back into the compact JSON store string."""
    payload = [
        {"id": r.get("id") or str(uuid.uuid4()),
         "text": r["text"], "enabled": bool(r.get("enabled", True))}
        for r in rules
        if str(r.get("text", "")).strip()
    ]
    if not payload:
        return ""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def rules_fit_store(rules: list, raw: str) -> bool:
    """Budget user text separately from migration IDs and JSON metadata."""
    from ..constants import CHAT_RULES_MAXLEN, CHAT_RULES_STORE_MAXLEN, CHAT_RULES_MAX_ENTRIES

    return (len(rules) <= CHAT_RULES_MAX_ENTRIES
            and sum(len(r["text"].encode("utf-8")) for r in rules) < CHAT_RULES_MAXLEN
            and len(raw.encode("utf-8")) < CHAT_RULES_STORE_MAXLEN)


def get_raw_rules(scene) -> str:
    """The scene's raw store string, falling back to any non-empty scene.

    Rules are mirrored across scenes on every edit, but a scene created
    AFTER the last edit starts empty — the fallback keeps per-scene
    parallel-agent chats consistent with the rest of the file.
    """
    raw = (getattr(scene, 'mixie_chat_rules', '') or '').strip()
    if raw:
        return raw
    try:
        import bpy
        for scn in bpy.data.scenes:
            other = (getattr(scn, 'mixie_chat_rules', '') or '').strip()
            if other:
                return other
    except Exception:
        logger.debug("rules fallback scan failed", exc_info=True)
    return ""


def rules_snapshot(scene) -> dict:
    """Complete scoped state; empty lists explicitly clear remembered rules."""
    from .rules_global import load_global_rules
    return {"version": 1, "global": load_global_rules(),
            "project": parse_rules(get_raw_rules(scene))}


def get_project_rules(scene) -> str:
    """All ENABLED rules concatenated for the wire, or "" when none.

    Global rules (``core/rules_global.py`` — they apply to every .mixar
    file) come first, then this file's rules. Because the mid-session
    update fingerprint hashes THIS text, any global-rule edit or a
    project<->global scope move propagates on the next send exactly like
    a project-rule edit.
    """
    from .rules_global import load_global_rules  # lazy: avoids import cycle

    rules = load_global_rules() + parse_rules(get_raw_rules(scene))
    return "\n\n".join(r["text"] for r in rules if r.get("enabled", True))


def rules_fingerprint(rules_text: str) -> str:
    """Stable fingerprint of the enabled-rules wire text ("" when empty)."""
    if not rules_text:
        return ""
    return hashlib.sha256(rules_text.encode('utf-8')).hexdigest()[:32]


def mark_rules_sent(scene) -> None:
    """Record which ruleset this scene's session has been given.

    Called AFTER a send actually goes out (chat_ops / quick_prompt_ops) so
    a failed stream start never swallows a pending rules update.
    """
    try:
        scene.mixie_chat_rules_sent_hash = rules_fingerprint(get_project_rules(scene))
    except Exception:
        logger.debug("mark_rules_sent failed", exc_info=True)


def compose_wire_message(scene, message_text: str) -> str:
    """Compose the wire message, injecting project rules where due.

    Must be called BEFORE ``SessionManager.start_session`` — that call
    generates ``scene.mixie_session_id``, which is exactly the signal that
    distinguishes a first message from a continuation.

    - NEW session: the full enabled ruleset rides along with the first
      message.
    - CONTINUATION where the enabled ruleset changed since it was last
      sent to this session (edit/add/delete/toggle — tracked via the
      per-scene ``mixie_chat_rules_sent_hash`` fingerprint stamped by
      :func:`mark_rules_sent`): the CURRENT complete set is re-sent under
      a strict supersede header, or a removal note when the rules were
      cleared. Diffs are deliberately not sent — the old rules are
      already in the conversation history; the model only needs an
      unambiguous "use the latest set" instruction, which also covers
      deletions and disables that have no "new text".

    Modify / input-response sends never pass through here, so an answer
    to an agent question is never polluted with a rules block.
    """
    rules = get_project_rules(scene)

    if not getattr(scene, 'mixie_session_id', ''):
        # New session: plain first-message injection.
        if not rules:
            return message_text
        prefix = f"{RULES_HEADER}\n{rules}\n{RULES_END_MARKER}"
        return f"{prefix}\n\n{message_text}" if message_text else prefix

    # Continuation: only inject when the enabled ruleset changed since the
    # last send on this session.
    sent = getattr(scene, 'mixie_chat_rules_sent_hash', '')
    current = rules_fingerprint(rules)
    if current == sent:
        return message_text

    if rules:
        prefix = f"{RULES_UPDATE_HEADER}\n{rules}\n{RULES_END_MARKER}"
    elif sent:
        prefix = RULES_REMOVED_NOTE
    else:
        return message_text
    return f"{prefix}\n\n{message_text}" if message_text else prefix
