# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Is Blender's asynchronous render job (F12 machinery) alive right now?

A background render — the agent's fire-and-forget final render, a user's own
F12, a Director shot render — runs on Blender's job thread and reads the
scene's original datablocks (image buffers, material node trees, meshes)
while it goes. Python that mutates or frees that data from the main thread
in the meantime is the documented "modifying data during rendering" crash:
no exception, the process just dies. Every main-thread path that mutates
scene data on the agent's behalf (the sandbox script executor above all)
must ask this before it touches ``bpy.data``.

Kept ``bpy``-free at import so it can be used from the job queue and the
chat module alike; the ``bpy`` import is deferred to the call.
"""

from __future__ import annotations


def render_job_running() -> bool:
    """True only when Blender positively reports a RENDER job in flight.

    ``bpy.app.is_job_running`` is missing on very old builds and is a
    ``MagicMock`` under the standalone test suite — both must read as "no
    render", never as "wait forever", so the comparison is against the
    literal ``True``.
    """
    try:
        import bpy

        return bpy.app.is_job_running("RENDER") is True
    except Exception:
        return False
