# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared agent script execution boundary (harness v3, PR 1).

One request value type (:mod:`request`), one worker identity model
(:mod:`identity`) and one set of main-thread pump helpers (:mod:`pump`) used
by BOTH the GUI executor (``space_mixie_chat/core/main_thread_executor.py``)
and the headless worker pump (``headless/headless_main.py``). Before this
package the two pumps disagreed on the queue envelope (six fields produced,
four consumed) and the worker silently raised on its first script.

Nothing here imports ``bpy`` at module level, so the contract is testable
outside Blender.
"""
