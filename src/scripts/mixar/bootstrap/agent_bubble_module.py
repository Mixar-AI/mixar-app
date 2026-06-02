# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Bubble Bootstrap

Wires the floating agent bubble into Blender's startup:

1. Registers the bubble menu type (MIXIE_CHAT_MT_agent_bubble) SYNCHRONOUSLY
   instead of through the deferred UI loader. The deferred loader spreads
   ~415 modules across many frames at a 4 ms/frame budget; menus land in
   the last priority bucket, so they often aren't ready when the auto-show
   timer fires. Synchronous registration here removes the race.

2. Schedules an auto-show timer that retries until the bubble actually
   appears, surviving the splash + workspace bounce that closes popups on
   first launch.

3. Installs a load_post handler so the bubble re-shows after the user
   loads a new file or hits "General" in the splash (which calls
   wm.read_homefile and tears down all popups).

4. Subscribes via msgbus to window.workspace changes so the bubble
   re-shows after the Zen Mode / Engine Mode switch operators bounce
   workspaces (the bounce destroys popups too, just like read_homefile).

5. Appends an "Open Agent" button to the right side of Blender's
   top bar (between ViewLayer and the user/profile dropdown), so the
   user always has a guaranteed manual way to bring the bubble back
   — whether it's been closed entirely or minimised to the status
   pill — no matter how the auto-show pipeline ends up.

The C++ operator that actually shows the popup is registered by the
SpaceMixieChat editor's spacetype init (mixie_chat_operatortypes in
space_mixie_chat.cc) — that path runs during Blender startup, before any
Python addon. So by the time anything in this file runs, bpy.ops.mixie_chat
.agent_bubble_show is callable.
"""

import sys

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.agent_bubble.core import pill_icons
from mixar.modules.agent_bubble.core.bubble_autoshow import (
    arm_autoshow as _arm_autoshow,
    autoshow_bubble as _autoshow_bubble,
    try_invoke_bubble as _try_invoke_bubble,
)
from mixar.modules.agent_bubble.core.bubble_lifecycle import (
    close_restored_agent_bubble_windows as _close_restored_agent_bubble_windows,
    has_agent_bubble_windows as _has_agent_bubble_windows,
    is_agent_bubble_window as _is_agent_bubble_window,
    load_autoshow_tick as _load_autoshow_tick,
    on_save_post as _on_save_post,
    on_save_pre as _on_save_pre,
    reset_restored_bubbles_after_load as _reset_restored_bubbles_after_load,
    restore_bubble_after_save as _restore_bubble_after_save,
)
from mixar.modules.agent_bubble.core.bubble_splash_watch import (
    SPLASH_POLL_S as _SPLASH_POLL_S,
    splash_watch_tick as _splash_watch_tick,
)
from mixar.modules.agent_bubble.core import bubble_state as _st
from mixar.modules.agent_bubble.ui.menus.agent_bubble_menu import (
    classes as bubble_menu_classes,
)
from mixar.modules.agent_bubble.ui.operators.bubble_close_op import (
    classes as bubble_close_op_classes,
)
from mixar.modules.agent_bubble.ui.operators.bubble_header_drag_op import (
    classes as bubble_header_drag_classes,
)
from mixar.modules.agent_bubble.ui.operators.bubble_history_ops import (
    classes as bubble_op_classes,
)
from mixar.modules.agent_bubble.ui.operators.window_ops import (
    classes as window_op_classes,
)
from mixar.modules.agent_bubble.ui.header import (
    classes as header_classes,
)
from mixar.modules.agent_bubble.ui.panels.footer_panel import (
    classes as footer_panel_classes,
)
from mixar.modules.agent_bubble.ui.panels.history_panel import (
    classes as history_panel_classes,
)

logger = get_logger(__name__)

# Streaming redraws
_STREAMING_STATES = {"BUSY", "MODIFYING", "AWAITING_INPUT", "CONNECTING"}
_STREAMING_TICK_BUSY = 0.1
_STREAMING_TICK_ACTIVE = 0.25
_STREAMING_TICK_IDLE = 1.0

# Owner sentinel for our msgbus subscription.
_MSGBUS_OWNER = object()

# Track the keymap items we register.
_keymap_items = []


def mark_user_closed() -> None:
    """Public API used by MIXAR_OT_bubble_close."""
    _st.user_explicitly_closed = True
    logger.info("agent_bubble: user dismissal recorded — autoshow muted")


def mark_user_opened() -> None:
    """Public API: clear the dismissal flag so autoshow paths fire again."""
    if _st.user_explicitly_closed:
        logger.info("agent_bubble: user dismissal cleared — autoshow re-armed")
    _st.user_explicitly_closed = False


def _streaming_redraw_tick():
    """Persistent timer: keep the agent bubble + status pill in sync."""
    try:
        scene = bpy.context.scene
        state = (
            getattr(scene, "mixie_chat_state", "OFFLINE")
            if scene is not None
            else "OFFLINE"
        )
        streaming = state in _STREAMING_STATES
        has_bubble = False
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'AGENT_BUBBLE':
                    has_bubble = True
                    area.tag_redraw()
                    for region in area.regions:
                        region.tag_redraw()
                elif streaming and area.type == 'VIEW_3D':
                    area.tag_redraw()
                    for region in area.regions:
                        region.tag_redraw()
        if not has_bubble:
            return _STREAMING_TICK_IDLE
        return _STREAMING_TICK_BUSY if streaming else _STREAMING_TICK_ACTIVE
    except Exception:  # noqa: BLE001 — timer must never raise
        return _STREAMING_TICK_IDLE


def _on_workspace_change() -> None:
    """msgbus callback: workspace changed → autoshow the bubble."""
    if _has_agent_bubble_windows():
        logger.debug(
            "agent_bubble: workspace change preserved existing bubble/pill state"
        )
        return

    if _st.user_explicitly_closed:
        logger.debug(
            "agent_bubble: workspace change → reopening in pill-only state"
        )
        _arm_autoshow(reset=True, start_minimised=True)
        return
    _arm_autoshow(reset=True)


def _subscribe_workspace_changes() -> None:
    """Subscribe to window.workspace changes via msgbus. Idempotent."""
    bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    try:
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.Window, "workspace"),
            owner=_MSGBUS_OWNER,
            args=(),
            notify=_on_workspace_change,
        )
        logger.info("agent_bubble: subscribed to window.workspace changes")
    except Exception as e:  # noqa: BLE001 — never break startup
        logger.warning("agent_bubble: msgbus subscription failed: %s", e)


def _register_bubble_keymap() -> None:
    """Bind ESC (close), RMB (block), LEFTMOUSE (header drag)."""
    global _keymap_items

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        logger.warning(
            "agent_bubble: addon keyconfig unavailable, retrying in 0.5s"
        )
        return 0.5

    for km, kmi in _keymap_items:
        try:
            km.keymap_items.remove(kmi)
        except (ValueError, ReferenceError):
            pass
    _keymap_items = []

    # ESC → close.
    try:
        km = kc.keymaps.new(name="Window", space_type='EMPTY')
        kmi = km.keymap_items.new(
            idname="mixar.bubble_close",
            type='ESC',
            value='PRESS',
        )
        _keymap_items.append((km, kmi))
    except Exception as e:  # noqa: BLE001
        logger.warning("agent_bubble: ESC keymap bind failed: %s", e)

    # RIGHTMOUSE in bubble/pill -> consume.
    try:
        km = kc.keymaps.new(name="Window", space_type='EMPTY')
        for value in ('PRESS', 'CLICK'):
            kmi = km.keymap_items.new(
                idname="mixar.bubble_block_context_menu",
                type='RIGHTMOUSE',
                value=value,
            )
            _keymap_items.append((km, kmi))
    except Exception as e:  # noqa: BLE001
        logger.warning("agent_bubble: RMB block keymap bind failed: %s", e)

    # LEFTMOUSE PRESS → drag-resize.
    try:
        km = kc.keymaps.new(name="Window", space_type='EMPTY')
        kmi = km.keymap_items.new(
            idname="mixar.bubble_header_drag",
            type='LEFTMOUSE',
            value='PRESS',
        )
        _keymap_items.append((km, kmi))
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "agent_bubble: header-drag keymap bind failed: %s", e
        )

    # Cmd+Shift+B (macOS) / Ctrl+Shift+B (Windows/Linux) → toggle the bubble
    # between the full window and the floating pill. Global (space_type
    # EMPTY) and the operator has no space poll, so it works from any editor.
    try:
        is_macos = sys.platform == 'darwin'
        km = kc.keymaps.new(name="Window", space_type='EMPTY')
        kmi = km.keymap_items.new(
            idname="mixar.bubble_toggle_minimise",
            type='B',
            value='PRESS',
            shift=True,
            oskey=is_macos,
            ctrl=not is_macos,
        )
        _keymap_items.append((km, kmi))
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "agent_bubble: minimise-toggle keymap bind failed: %s", e
        )

    logger.info(
        "agent_bubble: keymaps registered "
        "(ESC + RMB block + header drag + minimise toggle): %d items",
        len(_keymap_items),
    )


def _unregister_bubble_keymap() -> None:
    global _keymap_items
    for km, kmi in _keymap_items:
        try:
            km.keymap_items.remove(kmi)
        except (ValueError, ReferenceError):
            pass
    _keymap_items = []


@persistent
def _on_load_post(_dummy_arg) -> None:
    """Re-subscribe msgbus + re-bind ESC + autoshow after file load."""
    mark_user_opened()
    _subscribe_workspace_changes()
    _register_bubble_keymap()
    if bpy.app.timers.is_registered(_autoshow_bubble):
        bpy.app.timers.unregister(_autoshow_bubble)
    if not bpy.app.timers.is_registered(_reset_restored_bubbles_after_load):
        bpy.app.timers.register(_reset_restored_bubbles_after_load, first_interval=0.0)


# ---------------------------------------------------------------------------
# Topbar-right entry — "Open Agent" button.
# ---------------------------------------------------------------------------

def _draw_topbar_open_agent(self, context):
    region = getattr(context, "region", None)
    if region is None or region.alignment != 'RIGHT':
        return
    layout = self.layout
    layout.separator()
    layout.operator(
        "mixar.agent_bubble_open_window",
        text="Open Mixie",
        icon='OUTLINER_OB_LIGHT',
    )


_topbar_hook_appended = False


def _install_topbar_hook() -> None:
    global _topbar_hook_appended
    if _topbar_hook_appended:
        return
    parent = getattr(bpy.types, "TOPBAR_HT_upper_bar", None)
    if parent is None:
        logger.warning("agent_bubble: TOPBAR_HT_upper_bar not available")
        return
    try:
        parent.append(_draw_topbar_open_agent)
        _topbar_hook_appended = True
    except Exception as e:  # noqa: BLE001
        logger.warning("agent_bubble: topbar hook failed: %s", e)


def _uninstall_topbar_hook() -> None:
    global _topbar_hook_appended
    if not _topbar_hook_appended:
        return
    parent = getattr(bpy.types, "TOPBAR_HT_upper_bar", None)
    if parent is None:
        _topbar_hook_appended = False
        return
    try:
        parent.remove(_draw_topbar_open_agent)
    except (ValueError, Exception):  # noqa: BLE001
        pass
    _topbar_hook_appended = False


# ---------------------------------------------------------------------------
# Bootstrap entry points
# ---------------------------------------------------------------------------

def register():
    """Register menu + schedule auto-show + install all triggers."""
    logger.info("agent_bubble: register() — installing menu + autoshow timer")

    if not bpy.app.timers.is_registered(pill_icons.register):
        bpy.app.timers.register(pill_icons.register, first_interval=1.0)

    all_classes = (
        bubble_op_classes
        + window_op_classes
        + bubble_close_op_classes
        + bubble_header_drag_classes
        + bubble_menu_classes
        + header_classes
        + footer_panel_classes
        + history_panel_classes
    )
    for cls in all_classes:
        try:
            bpy.utils.register_class(cls)
            print(f"[agent_bubble] registered {cls.__name__}")
            logger.info("agent_bubble: registered %s", cls.__name__)
        except ValueError as e:
            if "already registered" not in str(e):
                print(f"[agent_bubble] FAILED to register {cls.__name__}: {e}")
                logger.warning("Failed to register %s: %s", cls.__name__, e)
        except Exception as e:  # noqa: BLE001
            print(f"[agent_bubble] FAILED to register {cls.__name__}: {e!r}")
            logger.warning("Failed to register %s: %s", cls.__name__, e)

    _install_topbar_hook()

    if not hasattr(bpy.types.Scene, "mixar_bubble_history_lines"):
        bpy.types.Scene.mixar_bubble_history_lines = bpy.props.IntProperty(
            name="Agent Bubble History Lines",
            description="Number of chat history rows visible in the floating bubble",
            default=0,
            min=0,
            max=200,
            options={'SKIP_SAVE'},
        )

    if not hasattr(bpy.types.Scene, "mixar_bubble_history_active_index"):
        bpy.types.Scene.mixar_bubble_history_active_index = bpy.props.IntProperty(
            name="Agent Bubble History Active Index",
            description="Active row in the floating bubble's chat history list",
            default=0,
            options={'SKIP_SAVE'},
        )

    if not bpy.app.timers.is_registered(_splash_watch_tick):
        bpy.app.timers.register(_splash_watch_tick, first_interval=_SPLASH_POLL_S)

    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if _on_save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_on_save_pre)
    if _on_save_post not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_on_save_post)

    if not bpy.app.timers.is_registered(_subscribe_workspace_changes):
        bpy.app.timers.register(_subscribe_workspace_changes, first_interval=0.8)
    if not bpy.app.timers.is_registered(_register_bubble_keymap):
        bpy.app.timers.register(_register_bubble_keymap, first_interval=0.8)

    if not bpy.app.timers.is_registered(_streaming_redraw_tick):
        bpy.app.timers.register(
            _streaming_redraw_tick, first_interval=_STREAMING_TICK_IDLE
        )


def unregister():
    """Tear down all hooks."""

    pill_icons.unregister()

    if hasattr(bpy.types.Scene, "mixar_bubble_history_lines"):
        try:
            del bpy.types.Scene.mixar_bubble_history_lines
        except Exception as e:  # noqa: BLE001
            logger.warning("agent_bubble: removing history flag failed: %s", e)

    if hasattr(bpy.types.Scene, "mixar_bubble_history_active_index"):
        try:
            del bpy.types.Scene.mixar_bubble_history_active_index
        except Exception as e:  # noqa: BLE001
            logger.warning("agent_bubble: removing active-index flag failed: %s", e)

    _uninstall_topbar_hook()
    _unregister_bubble_keymap()

    try:
        bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    except Exception as e:  # noqa: BLE001
        logger.warning("agent_bubble: msgbus clear failed: %s", e)

    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if _on_save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_on_save_pre)
    if _on_save_post in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(_on_save_post)

    if bpy.app.timers.is_registered(_autoshow_bubble):
        bpy.app.timers.unregister(_autoshow_bubble)

    if bpy.app.timers.is_registered(_streaming_redraw_tick):
        bpy.app.timers.unregister(_streaming_redraw_tick)

    if bpy.app.timers.is_registered(_splash_watch_tick):
        bpy.app.timers.unregister(_splash_watch_tick)

    if bpy.app.timers.is_registered(_reset_restored_bubbles_after_load):
        bpy.app.timers.unregister(_reset_restored_bubbles_after_load)

    if bpy.app.timers.is_registered(_load_autoshow_tick):
        bpy.app.timers.unregister(_load_autoshow_tick)

    if bpy.app.timers.is_registered(_restore_bubble_after_save):
        bpy.app.timers.unregister(_restore_bubble_after_save)

    if bpy.app.timers.is_registered(pill_icons.register):
        bpy.app.timers.unregister(pill_icons.register)

    if bpy.app.timers.is_registered(_subscribe_workspace_changes):
        bpy.app.timers.unregister(_subscribe_workspace_changes)

    if bpy.app.timers.is_registered(_register_bubble_keymap):
        bpy.app.timers.unregister(_register_bubble_keymap)
    
    # Cancel deferred-init one-shots if they have not fired yet — their
    # closures keep references to torn-down keymaps/msgbus state.
    for _deferred in (_subscribe_workspace_changes, _register_bubble_keymap):
        try:
            if bpy.app.timers.is_registered(_deferred):
                bpy.app.timers.unregister(_deferred)
        except Exception:
            pass

    for cls in reversed(
        bubble_menu_classes
        + bubble_op_classes
        + window_op_classes
        + bubble_close_op_classes
        + bubble_header_drag_classes
        + header_classes
        + footer_panel_classes
        + history_panel_classes
    ):
        try:
            if getattr(cls, "is_registered", False):
                bpy.utils.unregister_class(cls)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to unregister %s: %s", cls.__name__, e)
