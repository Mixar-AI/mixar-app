# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""One generation callback for all accepted jobs in a synchronous fan-out.

The backend deduplicates by generation_id, so stamping siblings alone would
still wake it on the first completion. Keep terminal metadata until every
accepted member settles, including members already cleared from the UI.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import weakref

from .job import TERMINAL_STATES

_active_batch = ContextVar('agent_generation_batch', default=None)


class AgentBatch:
    def __init__(self, ref):
        self.ref = ref
        self.members = {}
        self.outcomes = {}
        self.sealed = False
        self.retained = False

    def add(self, job):
        self.members[job.id] = weakref.ref(job)
        job._agent_batch = self

    def result(self):
        from .agent_results import build_agent_result_params

        for key, job_ref in self.members.items():
            job = job_ref()
            if key not in self.outcomes and job is not None and job.state in TERMINAL_STATES:
                self.outcomes[key] = build_agent_result_params(job)
        if not self.sealed or not self.members or len(self.outcomes) != len(self.members):
            return None
        outcomes = [self.outcomes[key] for key in self.members]
        params = dict(outcomes[0])
        if len(outcomes) > 1:
            params['label'] = ', '.join(p['label'] for p in outcomes)
            # No single backend job represents the whole batch.
            params['backend_job_id'] = ''
            params['result_names'] = list(dict.fromkeys(
                name for p in outcomes for name in p['result_names']))
            statuses = {p['status'] for p in outcomes}
            params['status'] = ('failed' if 'failed' in statuses else
                                'cancelled' if 'cancelled' in statuses else 'succeeded')
            params['error'] = '; '.join(
                f"{p['label']}: {p['error'] or p['status']}"
                for p in outcomes if p['status'] != 'succeeded')
        return params


def current_agent_batch():
    return _active_batch.get()


@contextmanager
def agent_generation_batch(context):
    """Claim once per invocation; duplicates never consume a sibling's ref.

    Only this synchronous scope shares the identity. On exit, even after an
    exception, stop accepting members before attempting terminal delivery.
    """
    from mixar.modules.common.utils.agent_feedback import take_agent_ref

    ref = take_agent_ref(context)
    batch = AgentBatch(ref) if ref else None
    token = _active_batch.set(batch)
    try:
        yield
    finally:
        _active_batch.reset(token)
        if batch is not None:
            batch.sealed = True
            from .agent_results import report_agent_batch

            report_agent_batch(batch)
