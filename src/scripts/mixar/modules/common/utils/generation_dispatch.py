# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded reasons across nested bpy operators, scoped to one dispatch.

Blender turns an inner ERROR report into RuntimeError, even for expected
input validation. Never infer a reason from translated/user-provided text.
"""

from contextlib import contextmanager
from contextvars import ContextVar

REASONS = frozenset({
    'tab_unavailable', 'catalog_unavailable', 'model_unavailable',
    'missing_input', 'missing_image', 'invalid_multi_view',
    'image_processing_failed', 'duplicate_job', 'enqueue_failed',
})
_current = ContextVar('mixar_generation_dispatch', default=None)


@contextmanager
def dispatch_scope():
    feedback = {}
    token = _current.set(feedback)
    try:
        yield feedback
    finally:
        _current.reset(token)


def record_reason(reason):
    feedback = _current.get()
    if feedback is not None and reason in REASONS:
        feedback.setdefault('reason', reason)
