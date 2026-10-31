# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generations that were running when Mixar closed.

The client queue lives in memory only, so a job that finishes while the app
is dead is charged and never imported. Each save point records the submitted
jobs (they have a backend job id). After a restore, the generic jobs —
``AsyncGLBJob``, ``SyncImageJob`` and ``StreamingVideoJob``, which carry
every catalog and agent generation — are rebuilt from that record and
adopted by their queue in ``RUNNING_POLL``; ``job.get`` then imports a result
that is already done. Their post-import hooks were Python callables and are
gone: the result lands the default way (a model in the scene, an image on the
moodboard). Bespoke queues are only named in the restore notice.
"""

from __future__ import annotations

GENERIC_CLASSES = ("AsyncGLBJob", "SyncImageJob", "StreamingVideoJob")

# Plain fields that rebuild a generic job; everything else is runtime state.
_FIELDS = (
    "feature_key", "label", "scene_name", "service", "origin_capability_key",
    "graph_node_id", "model", "backend_job_id", "backend_api_type", "origin",
    "agent_ref", "display_label", "job_type", "fail_message", "name_prefix",
    "prompt_text", "undo_message", "base_name",
)
_ACTIVE_STATES = ("RUNNING_SUBMIT", "RUNNING_POLL", "RUNNING_DOWNLOAD", "PAUSED_AUTH")


def _state_name(job) -> str:
    state = getattr(job, "state", "")
    return str(getattr(state, "value", state) or "")


def describe(jobs) -> list:
    """JSON-safe records of the submitted, unfinished jobs."""
    records = []
    for job in jobs:
        if _state_name(job) not in _ACTIVE_STATES or not getattr(job, "backend_job_id", ""):
            continue
        record = {"cls": type(job).__name__}
        for name in _FIELDS:
            if hasattr(job, name):
                value = getattr(job, name)
                if isinstance(value, (str, int, float, bool)) or value is None:
                    record[name] = value
                elif isinstance(value, dict):
                    record[name] = {str(k): v for k, v in value.items()
                                    if isinstance(v, (str, int, float, bool)) or v is None}
        records.append(record)
    return records


def rebuild(record: dict, classes: dict):
    """A job ready for ``FeatureQueue.adopt``, or None for a bespoke job."""
    cls = classes.get(record.get("cls", ""))
    if cls is None or not record.get("backend_job_id"):
        return None
    kwargs = {}
    fields = getattr(cls, "__dataclass_fields__", {})
    for name in _FIELDS:
        if name in record and name in fields:
            kwargs[name] = record[name]
    try:
        return cls(**kwargs)
    except TypeError:
        return None


def split(records: list) -> tuple:
    """``(adoptable, other)`` by class."""
    adoptable = [r for r in records if r.get("cls") in GENERIC_CLASSES and r.get("backend_job_id")]
    other = [r for r in records if r not in adoptable]
    return adoptable, other
