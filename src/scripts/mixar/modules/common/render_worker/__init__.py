# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Heavy agent jobs in a separate background Mixar process.

A render, an export package or a material bake runs native code that has
crashed the user's app (render job thread on a freed scene or depsgraph, the
OpenImageDenoise kernel, ``new_from_object`` on a dangling material). Here the
job runs in a second Mixar (``<bundle binary> --background``) on a SNAPSHOT of
the document, so a crash costs one retry and never the user's session, and
the user's main thread is free while it works.

- :mod:`snapshot` (parent) writes the snapshot: ``save_as_mainfile(copy=True)``
  plus the pixels of every unsaved (dirty) image, which a .blend does not carry.
- :mod:`supervisor` (parent) owns the worker processes: spawn, a warm worker
  per job kind, idle reaping, kill on cancel and on exit, a crash detected and
  retried once on a fresh worker.
- :mod:`tasks` (parent) is what callers use: submit a job, poll it from the
  main thread, cancel it. A worker that cannot start falls back to the caller's
  in-process path.
- :mod:`worker_main` / :mod:`worker_jobs` (child) read jobs from stdin, load the
  snapshot and run the SAME client code the in-process path runs.
- :mod:`protocol` is the line framing both sides share.

Nothing here imports ``bpy`` at module level except :mod:`snapshot` and the
child modules, so the process logic is testable outside Blender.
"""
