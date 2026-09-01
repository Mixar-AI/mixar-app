# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent UI control — the backend agent operates the real Mixar UI.

Trusted add-on code (never the sandboxed script executor). The backend's
``ui.*`` JSON-RPC family (capability ``ui_control_v1``) is dispatched here:
semantic widget targeting over ``WindowManager.mixar_qa_ui_dump``, real input
injection through ``Window.event_simulate``, screenshots, and an interruptible
main-thread generator pump. Contract: mixar-backend/docs/agent/ui-control.md.
"""

from .service import AgentUIService, get_agent_ui_service

__all__ = ("AgentUIService", "get_agent_ui_service")
