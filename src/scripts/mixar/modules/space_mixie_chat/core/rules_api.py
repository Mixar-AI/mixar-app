# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Project Rules — store mutation API.

The SINGLE mutation surface for the rules stores, used by BOTH:

  * the UI operators (``ui/operators/rules_ops.py`` — dispatched by the
    C++ rules overlay), and
  * the agent tools (backend PROJECT_RULES domain — its Blender script
    template calls :func:`run_agent_tool`).

Keeping caps, unified-index resolution, and the WM-mirror refresh here
means the overlay and the agent can never drift: an agent-added rule
appears in an open overlay immediately, and both paths enforce the same
store caps.

Unified index contract (matches the C++ overlay and the WM mirror):
GLOBAL rules first (``~/.mixar/global_rules.json``), then this file's
rules (``scene.mixie_chat_rules``).

No top-level ``bpy`` import — everything except :func:`refresh_rules_ui`
is pure logic, unit-testable outside Blender.
"""

import uuid

from mixar.config.logging_config import get_logger

from .rules import get_raw_rules, parse_rules, serialize_rules, rules_snapshot, rules_fit_store
from .rules_global import load_global_rules, save_global_rules

logger = get_logger(__name__)

SCOPE_GLOBAL = "global"
SCOPE_PROJECT = "project"


# =============================================================================
# Store primitives
# =============================================================================

def list_unified(scene) -> list:
    """All rules as ``[{index, text, enabled, scope}]``, globals first."""
    unified = []
    for rule in load_global_rules():
        unified.append({
            "index": len(unified),
            "id": rule["id"],
            "text": rule["text"],
            "enabled": rule["enabled"],
            "scope": SCOPE_GLOBAL,
        })
    for rule in parse_rules(get_raw_rules(scene)):
        unified.append({
            "index": len(unified),
            "id": rule["id"],
            "text": rule["text"],
            "enabled": rule["enabled"],
            "scope": SCOPE_PROJECT,
        })
    return unified


def resolve_rule(scene, index: int = -1, rule_id=None):
    """Resolve a stable ID, or a legacy UI index; ambiguous IDs fail closed."""
    globals_ = load_global_rules()
    projects = parse_rules(get_raw_rules(scene))
    if rule_id is not None:
        matches = [(is_global, rules, local)
                   for is_global, rules in ((True, globals_), (False, projects))
                   for local, rule in enumerate(rules) if rule["id"] == rule_id]
        return matches[0] if len(matches) == 1 else None
    if 0 <= index < len(globals_):
        return True, globals_, index
    local = index - len(globals_)
    if 0 <= local < len(projects):
        return False, projects, local
    return None


def write_project_rules(scene, rules: list) -> bool:
    """Serialize + persist the FILE rule list; False when over the cap."""
    raw = serialize_rules(rules)
    if not rules_fit_store(rules, raw):
        return False
    try:
        scene.mixie_chat_rules = raw  # RNA callback mirrors across scenes
        return True
    except (AttributeError, RuntimeError, TypeError):
        logger.exception("failed to save project rules")
        return False


def save_store(scene, is_global: bool, rules: list) -> bool:
    if is_global:
        return save_global_rules(rules)
    return write_project_rules(scene, rules)


# =============================================================================
# Mutations — each returns {"success", "error", "rules": <fresh list>}
# =============================================================================

_ERR_FULL = "Rules could not be saved — store may be full or unavailable"


def _result(scene, success: bool, error: str = "") -> dict:
    out = {"success": success, "rules": list_unified(scene),
           "rules_snapshot": rules_snapshot(scene)}
    if error:
        out["error"] = error
    return out


def add_rule(scene, text: str, scope: str = SCOPE_PROJECT) -> dict:
    text = (text or "").strip()
    if not text:
        return _result(scene, False, "Rule text is empty")
    if scope not in (SCOPE_PROJECT, SCOPE_GLOBAL):
        return _result(scene, False,
                       f"Unknown scope {scope!r} — use 'project' or 'global'")
    is_global = (scope == SCOPE_GLOBAL)
    rules = load_global_rules() if is_global else parse_rules(get_raw_rules(scene))
    rules.append({"id": str(uuid.uuid4()), "text": text, "enabled": True})
    if not save_store(scene, is_global, rules):
        return _result(scene, False, _ERR_FULL)
    return _result(scene, True)


def update_rule(scene, index: int = -1, text=None, enabled=None, scope=None,
                rule_id=None) -> dict:
    if text is None and enabled is None and scope is None:
        return _result(scene, False,
                       "Nothing to change — pass text, enabled, and/or scope")
    resolved = resolve_rule(scene, index, rule_id=rule_id)
    if resolved is None:
        return _result(scene, False,
                       f"Rule {rule_id if rule_id is not None else index} is missing or ambiguous — list rules again")
    is_global, rules, local = resolved

    if text is not None:
        text = str(text).strip()
        if not text:
            return _result(scene, False, "Rule text is empty")
        rules[local]["text"] = text
    if enabled is not None:
        rules[local]["enabled"] = bool(enabled)

    if scope is not None and scope not in (SCOPE_PROJECT, SCOPE_GLOBAL):
        return _result(scene, False,
                       f"Unknown scope {scope!r} — use 'project' or 'global'")
    want_global = (scope == SCOPE_GLOBAL) if scope is not None else is_global

    if want_global == is_global:
        if not save_store(scene, is_global, rules):
            return _result(scene, False, _ERR_FULL)
        return _result(scene, True)

    # Scope move: append to the destination store FIRST — if it is full,
    # the rule must stay where it was (same semantics as the overlay chip).
    rule = rules[local]
    if want_global:
        dest = load_global_rules()
        dest.append(rule)
        if not save_global_rules(dest):
            return _result(scene, False, "Global rules could not be saved — store may be full or unavailable")
    else:
        dest = parse_rules(get_raw_rules(scene))
        dest.append(rule)
        if not write_project_rules(scene, dest):
            return _result(scene, False, "File rules could not be saved — store may be full or unavailable")
    # The two stores are disjoint, so the destination write above cannot
    # have invalidated the in-memory source list — pop and persist it.
    rules.pop(local)
    if not save_store(scene, is_global, rules):
        # Undo the destination append if source removal fails; report any
        # rollback failure honestly instead of claiming the move succeeded.
        rollback_ok = save_store(scene, want_global, dest[:-1])
        error = "Rule move failed; original rule was kept"
        if not rollback_ok:
            error += "; destination rollback failed, so a duplicate may remain"
        return _result(scene, False, error)
    return _result(scene, True)


def remove_rule(scene, index: int = -1, rule_id=None) -> dict:
    resolved = resolve_rule(scene, index, rule_id=rule_id)
    if resolved is None:
        return _result(scene, False,
                       f"Rule {rule_id if rule_id is not None else index} is missing or ambiguous — list rules again")
    is_global, rules, local = resolved
    rules.pop(local)
    if not save_store(scene, is_global, rules):
        return _result(scene, False, "Rule could not be removed — store is unavailable")
    return _result(scene, True)


# =============================================================================
# UI refresh (best-effort) + agent dispatcher
# =============================================================================

def refresh_rules_ui() -> None:
    """Rebuild the WM rule-entries mirror + repaint chat surfaces.

    Best-effort by design: runs after agent-driven mutations (script
    context) as well as UI operators, and must be a silent no-op in
    headless/mock contexts. Persistence is the source of truth — an open
    rules overlay reads the mirror, a closed one rebuilds on open.
    """
    try:
        import bpy

        wm = bpy.context.window_manager
        entries = wm.mixie_chat_rule_entries
        entries.clear()
        scene = bpy.context.scene
        for rule in load_global_rules():
            entry = entries.add()
            entry.text = rule["text"]
            entry.enabled = rule["enabled"]
            entry.is_global = True
        for rule in parse_rules(get_raw_rules(scene)):
            entry = entries.add()
            entry.text = rule["text"]
            entry.enabled = rule["enabled"]
            entry.is_global = False

        from .ui_utils import redraw_chat_areas
        redraw_chat_areas()
    except Exception:
        logger.debug("rules UI refresh skipped", exc_info=True)


def run_agent_tool(scene, tool_name: str, params: dict) -> dict:
    """Dispatch one agent rules tool (backend PROJECT_RULES domain).

    Same pattern as ``operation_history/core/tools.py:run_tool`` — the
    backend script template calls this with a tool name + params dict and
    forwards the returned JSON-serializable dict verbatim.
    """
    params = params or {}
    if tool_name == "list_rules":
        rules = list_unified(scene)
        return {"success": True, "rules": rules, "count": len(rules),
                "rules_snapshot": rules_snapshot(scene)}

    index = -1
    if tool_name in ("update_rule", "remove_rule") and params.get("rule_id") is None:
        try:
            index = int(params.get("index", -1))
        except (TypeError, ValueError):
            return _result(scene, False, "Supply a rule_id or a valid rule index")

    if tool_name == "add_rule":
        result = add_rule(scene, params.get("text", ""),
                          params.get("scope", SCOPE_PROJECT))
    elif tool_name == "update_rule":
        result = update_rule(scene, index,
                             text=params.get("text"),
                             enabled=params.get("enabled"),
                             scope=params.get("scope"), rule_id=params.get("rule_id"))
    elif tool_name == "remove_rule":
        result = remove_rule(scene, index,
                             rule_id=params.get("rule_id"))
    else:
        return {"success": False, "error": f"unknown rules tool: {tool_name}"}

    refresh_rules_ui()
    return result
