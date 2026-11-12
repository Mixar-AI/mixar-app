# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker-thread bridge to the unmodified Claude Code CLI. No token access.

Each call is stateless. Claude selects Mixar tools as structured output, with
its own tools/MCP/customizations disabled. Only Mixar's graph executes tools.
The local per-user provider record is the grant to run inference here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading

from mixar.modules.common.i18n import n_

PROVIDER = "claude_code"
MODE = "claude_code_v1"
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT = 600
_slots = threading.BoundedSemaphore(4)


class ClaudeCodeError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def executable() -> str:
    """Find the CLI in GUI-app PATHs as well as normal terminal installs."""
    found = shutil.which("claude")
    if not found:
        for folder in (Path.home() / ".local/bin", Path.home() / ".claude/local",
                       Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
            candidate = folder / ("claude.exe" if os.name == "nt" else "claude")
            if candidate.is_file() and os.access(candidate, os.X_OK):
                found = str(candidate)
                break
    if not found:
        raise ClaudeCodeError("claude_not_installed", n_("Install Claude Code, then run `claude auth login` in your terminal."))
    return found


def _run(args, payload="", timeout=TIMEOUT):
    # A fresh directory prevents project instructions or prior conversations
    # entering inference. Output is spooled to disk, never unbounded RAM.
    with tempfile.TemporaryDirectory(prefix="mixar-claude-") as cwd, \
            tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)  # GUI launched from a CLI session
        proc = subprocess.Popen([executable(), *args], stdin=subprocess.PIPE,
                                stdout=stdout, stderr=stderr, cwd=cwd, env=env,
                                start_new_session=os.name != "nt")
        try:
            proc.communicate(payload.encode(), timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(proc)
            raise ClaudeCodeError("claude_timeout", n_("Claude Code did not respond in time.")) from None
        if stdout.tell() > MAX_BYTES:
            raise ClaudeCodeError("claude_output_limit", n_("Claude Code's reply exceeded the size limit."))
        stdout.seek(0)
        output = stdout.read().decode("utf-8")
        if proc.returncode:
            # Never relay stdout/stderr: CLI errors can contain paths or account data.
            raise ClaudeCodeError("claude_failed", n_("Claude Code could not complete this request. Check its sign-in and usage limits in your terminal."))
        return output


def _kill(proc):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait()


def check_ready():
    """Ask Claude Code for sign-in status; never read its credential store."""
    try:
        status = json.loads(_run(["auth", "status", "--json"], timeout=15))
    except ClaudeCodeError as exc:
        if exc.code == "claude_not_installed":
            raise
        raise ClaudeCodeError("claude_login_required", n_("Run `claude auth login` in your terminal, then Save & Activate.")) from None
    except (ValueError, TypeError):
        raise ClaudeCodeError("claude_failed", n_("Update Claude Code, then try again.")) from None
    if not isinstance(status, dict) or not status.get("loggedIn") or status.get("authMethod") != "claude.ai":
        raise ClaudeCodeError("claude_login_required", n_("Run `claude auth login` with your Claude subscription, then Save & Activate."))


def _schema(tools):
    names = [t["function"]["name"] for t in tools]
    name = {"type": "string", "enum": names} if names else {"type": "string"}
    return {"type": "object", "properties": {
        "content": {"type": "string"},
        "tool_calls": {"type": "array", "maxItems": 32 if names else 0,
                       "items": {"type": "object", "properties": {
                           "name": name, "args": {"type": "object"}},
                           "required": ["name", "args"], "additionalProperties": False}}},
        "required": ["content", "tool_calls"], "additionalProperties": False}


def _prompt(params):
    images = []
    messages = []
    for message in params["messages"]:
        copy = dict(message)
        content = message.get("content")
        if isinstance(content, list):
            blocks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") in ("image", "image_url"):
                    source = block.get("source")
                    if not source:
                        url = block.get("image_url", {})
                        url = url.get("url") if isinstance(url, dict) else url
                        match = re.fullmatch(r"data:(image/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)", url or "")
                        if not match:
                            raise ClaudeCodeError("claude_image_format", n_("Claude Code requires an inline image attachment."))
                        source = {"type": "base64", "media_type": match[1], "data": match[2]}
                    if source.get("type") != "base64":
                        raise ClaudeCodeError("claude_image_format", n_("Claude Code requires an inline image attachment."))
                    images.append({"type": "image", "source": source})
                    blocks.append({"type": "text", "text": f"[Attached image {len(images)}]"})
                else:
                    blocks.append(block)
            copy["content"] = blocks
        messages.append(copy)
    instruction = (
        "You are the inference engine for Mixar. Continue the supplied conversation for ONE assistant step. "
        "Follow its system instructions. Tools described below are executed by Mixar, not by this CLI. "
        "Return content and tool_calls as structured output. To call a tool, put its exact name and JSON "
        "arguments in tool_calls; do not claim it ran. Mixar will return results in the next conversation. "
        "When answering without tools, return an empty tool_calls array. Respect tool_choice: "
        "required/any means at least one call; none means no calls; a named tool must be called. "
        "Images follow in their numbered order. Conversation and available tools:\n"
    )
    text = instruction + json.dumps({"messages": messages, "tools": params.get("tools", []),
                                    "tool_choice": params.get("tool_choice")}, ensure_ascii=False)
    return json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "text", "text": text}, *images]}}) + "\n"


def infer(params):
    model = params.get("model")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", model):
        raise ClaudeCodeError("claude_invalid_request", n_("Choose a Claude model in AI Provider Settings."))
    if not isinstance(params.get("messages"), list) or not isinstance(params.get("tools", []), list):
        raise ClaudeCodeError("claude_invalid_request", n_("Invalid Claude Code request."))
    if len(json.dumps(params).encode()) > MAX_BYTES:
        raise ClaudeCodeError("claude_input_limit", n_("Claude Code request exceeds the size limit."))
    check_ready()
    args = ["--print", "--safe-mode", "--tools", "", "--strict-mcp-config",
            "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
            "--no-session-persistence", "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose", "--model", model,
            "--json-schema", json.dumps(_schema(params.get("tools", [])))]
    effort = params.get("effort")
    if effort:
        if effort not in ("low", "medium", "high", "xhigh", "max"):
            raise ClaudeCodeError("claude_effort", n_("This thinking level is not supported by Claude Code."))
        args.extend(["--effort", effort])
    output = _run(args, _prompt(params))
    result = None
    for line in output.splitlines():
        item = json.loads(line)
        if isinstance(item, dict) and item.get("type") == "result":
            result = item
    if not result or result.get("is_error") or not isinstance(result.get("structured_output"), dict):
        raise ClaudeCodeError("claude_failed", n_("Claude Code returned no valid completion. Check its sign-in and usage limits in your terminal."))
    return {"output": result["structured_output"], "usage": result.get("usage") or {}}


def handle_request(params, respond):
    """Called on the relay worker, gated by this user's saved device grant."""
    if not _slots.acquire(blocking=False):
        respond({"error": {"code": "claude_busy"}})
        return
    try:
        from . import credential_state, key_store
        state = credential_state.snapshot()
        record = key_store.load()
        if (not state.get("byok_is_active") or state.get("byok_current_provider") != PROVIDER
                or not record or record.get("provider") != PROVIDER):
            raise ClaudeCodeError("claude_not_enabled", n_("Activate Claude Code on this computer."))
        result = infer(params)
        respond(result)
    except ClaudeCodeError as exc:
        respond({"error": {"code": exc.code}})
    except Exception:
        respond({"error": {"code": "claude_failed"}})
    finally:
        _slots.release()
