# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Native LLM message gate for local-model relay traffic.

Runs inside mixar.exe on the relay path (local_models/core/relay.py) — the
single choke point every BYOK / local-LLM chat-completions request passes
through — and replaces the optional ``rag/mixar-rag-server.py`` bridge:

* :func:`inspect_request` — quarantines hallucinated ``tool_calls`` from
  the conversation history BEFORE the request reaches the local server. A
  call is quarantined when its name is not in the request's declared
  ``tools`` list or its ``arguments`` are not valid JSON (the tool-result
  message that answered a quarantined call is removed too, so the history
  stays a valid OpenAI pairing). Schema / required-key mismatches and
  script bodies are audited (logged) but never touched.
* :func:`inspect_response` — log-only audit of the model output: every
  fenced Python block and every script argument of a returned
  ``tool_call`` is run through the space_mixie_chat attribute validator (the
  same advisory check the executor runs before dispatch — it reports, it
  never blocks).
* Goal-boundary detection inside :func:`inspect_request` — the last user
  message is hashed; when it changes, the relay may clear the local
  server's prompt cache so a fresh goal doesn't start with the previous
  goal's KV cache.

Design law (same as the whole relay): this module NEVER blocks a turn.
Every failure mode degrades to "log and pass through". It must stay
bpy-free: it runs on the relay worker thread.
"""

import hashlib
import json
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

LOG_PREFIX = "[MessageGate]"

# Tool-call parameter keys whose value is an executable Mixar script.
_SCRIPT_PARAM_KEYS = ("script", "code", "bpy_script", "python_code", "source")

# ```python / ```py fenced blocks (the form the generation model emits).
_FENCED_RE = re.compile(r"```(?:python|py)\b[^\n]*\n(.*?)```",
                        re.IGNORECASE | re.DOTALL)

# How many validator issues we log per script block. This is telemetry only:
# the attribute check is advisory everywhere, including in the executor.
_MAX_LOGGED_ISSUES = 5

_state_lock = threading.Lock()
_last_goal_hash: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _script_issues(source: str) -> List[str]:
    """Run the Mixar script validator over one source block.

    The import is lazy (it pulls in the truth-table machinery) and any
    failure degrades to an empty issue list — the gate must never raise
    into the relay. The script validator itself is blind-safe: with no
    truth table it reports nothing rather than guessing."""
    try:
        from mixar.modules.space_mixie_chat.core import script_validator
        issues = script_validator.validate_bpy_properties(source)
        return [str(issue) for issue in (issues or [])]
    except Exception as exc:  # noqa: BLE001 — telemetry must not raise
        logger.warning("%s script validation unavailable (%s)",
                       LOG_PREFIX, exc)
        return []


def _log_script_issues(source: str, label: str) -> None:
    issues = _script_issues(source)
    for issue in issues[:_MAX_LOGGED_ISSUES]:
        logger.warning("%s %s script issue: %s", LOG_PREFIX, label, issue)


def _declared_tool_names(request_obj: dict) -> set:
    """Tool names the request declared (``tools[].function.name``)."""
    names = set()
    tools = request_obj.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function")
            if isinstance(function, dict) \
                    and isinstance(function.get("name"), str):
                names.add(function["name"])
            elif isinstance(tool.get("name"), str):
                names.add(tool["name"])
    return names


def _tool_schemas(request_obj: dict) -> Dict[str, dict]:
    """name -> parameters schema, for the log-only schema audit."""
    schemas: Dict[str, dict] = {}
    tools = request_obj.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function")
            if isinstance(function, dict) \
                    and isinstance(function.get("name"), str) \
                    and isinstance(function.get("parameters"), dict):
                schemas[function["name"]] = function["parameters"]
    return schemas


def _audit_tool_call(call: dict, declared: set, schemas: dict) -> bool:
    """Audit one tool_call. Returns True when the call is QUARANTINED
    (undeclared name or unparseable / non-object arguments). Schema /
    required-key mismatches and script bodies are logged only — dropping
    such a call would orphan its tool-result message and break the
    pairing."""
    function = call.get("function")
    if not isinstance(function, dict):
        return True          # malformed beyond repair — quarantine
    name = function.get("name")
    if not isinstance(name, str) or (declared and name not in declared):
        logger.warning("%s quarantining undeclared tool_call: %r",
                       LOG_PREFIX, name)
        return True
    args = function.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            logger.warning("%s quarantining tool_call %s: arguments are not "
                           "valid JSON", LOG_PREFIX, name)
            return True
    if args is None:
        args = {}
    elif not isinstance(args, dict):
        logger.warning("%s quarantining tool_call %s: arguments are not a "
                       "JSON object", LOG_PREFIX, name)
        return True
    # ---- log-only: schema mismatch ----
    schema = schemas.get(name)
    if isinstance(schema, dict):
        props = schema.get("properties")
        props = props if isinstance(props, dict) else {}
        required = schema.get("required")
        required = required if isinstance(required, list) else []
        missing = [k for k in required if k not in args]
        unknown = [k for k in args if props and k not in props]
        if missing or unknown:
            logger.warning("%s tool_call %s schema mismatch: missing=%s "
                           "unknown=%s", LOG_PREFIX, name, missing, unknown)
    # ---- log-only: the script body itself ----
    for key in _SCRIPT_PARAM_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            _log_script_issues(value, f"tool_call {name}.{key}")
    return False


def _quarantine(messages: list, declared: set, schemas: dict) -> Tuple[list, int]:
    """Remove hallucinated tool_calls (and the tool results that answer
    them) so the history stays a valid OpenAI pairing."""
    out: List[Any] = []
    removed_ids = set()
    quarantined = 0
    for message in messages:
        if not isinstance(message, dict):
            out.append(message)
            continue
        if message.get("role") == "tool":
            # orphaned tool result for a quarantined call -> drop
            cid = message.get("tool_call_id")
            if isinstance(cid, str) and cid in removed_ids:
                continue
            out.append(message)
            continue
        calls = message.get("tool_calls")
        if message.get("role") != "assistant" or not isinstance(calls, list):
            out.append(message)
            continue
        kept: List[Any] = []
        for call in calls:
            if not isinstance(call, dict):
                quarantined += 1
                continue
            if _audit_tool_call(call, declared, schemas):
                cid = call.get("id")
                if isinstance(cid, str):
                    removed_ids.add(cid)
                quarantined += 1
                continue
            kept.append(call)
        if len(kept) == len(calls):
            out.append(message)
            continue
        reduced = dict(message)
        if kept:
            reduced["tool_calls"] = kept
            out.append(reduced)
        elif message.get("content") not in (None, ""):
            # every call quarantined: keep the content, drop the key
            reduced.pop("tool_calls", None)
            out.append(reduced)
    return out, quarantined


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inspect_request(body: bytes) -> Tuple[bytes, bool]:
    """Gate one inbound chat-completions request body.

    Returns ``(body_out, goal_changed)``: ``body_out`` is the body to send
    upstream (quarantined history re-serialized only when something was
    removed), ``goal_changed`` is True when the last user message differs
    from the one seen on the previous request — a goal boundary where the
    relay may clear the local server's prompt cache. Never raises; a body
    that cannot be parsed is returned untouched with ``goal_changed``
    False."""
    global _last_goal_hash
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:
        return body, False
    if not isinstance(obj, dict):
        return body, False

    # ---- goal-boundary detection (last user message) ----
    goal_changed = False
    last_user = None
    messages = obj.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "user":
                last_user = message.get("content")
    text = ""
    if isinstance(last_user, str):
        text = last_user
    elif isinstance(last_user, list):        # content-parts form
        text = " ".join(
            part.get("text", "")
            for part in last_user
            if isinstance(part, dict) and part.get("type") == "text"
        )
    if text.strip():
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        with _state_lock:
            # The first goal ever seen is NOT a boundary (there is no
            # previous goal whose cache could leak into it).
            goal_changed = (_last_goal_hash is not None
                            and digest != _last_goal_hash)
            _last_goal_hash = digest

    # ---- quarantine pass (re-serializes only when something changed) ----
    if not isinstance(messages, list):
        return body, goal_changed
    declared = _declared_tool_names(obj)
    schemas = _tool_schemas(obj)
    out_messages, quarantined = _quarantine(messages, declared, schemas)
    if not quarantined:
        return body, goal_changed
    logger.info("%s quarantined %d hallucinated tool_call(s) from history",
                LOG_PREFIX, quarantined)
    new_obj = dict(obj)
    new_obj["messages"] = out_messages
    new_body = json.dumps(new_obj, ensure_ascii=False).encode("utf-8")
    return new_body, goal_changed


def inspect_response(body: bytes) -> None:
    """Log-only audit of a chat-completions RESPONSE body (never mutates,
    never raises): fenced Python blocks in the message content and script
    arguments of returned tool_calls are run through the Mixar script
    validator."""
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:
        return
    if not isinstance(obj, dict):
        return
    choices = obj.get("choices")
    if not isinstance(choices, list):
        return
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        _audit_message_payload(message)


def _audit_message_payload(message: dict) -> None:
    content = message.get("content")
    if isinstance(content, str):
        for block in _FENCED_RE.findall(content):
            _log_script_issues(block, "response content")
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return
    for call in calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        args = function.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                logger.warning("%s response tool_call %s: arguments are not "
                               "valid JSON", LOG_PREFIX, name)
                continue
        if not isinstance(args, dict):
            continue
        for key in _SCRIPT_PARAM_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                _log_script_issues(value,
                                   f"response tool_call {name}.{key}")


def reset_state() -> None:
    """Drop the goal-boundary state (tests / session teardown)."""
    global _last_goal_hash
    with _state_lock:
        _last_goal_hash = None
