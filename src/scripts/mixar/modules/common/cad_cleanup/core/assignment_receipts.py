# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Read backend acceptance receipts; contains no CAD semantic policy."""
def current(run):
    receipt=run.get('backend_summary',{})
    return (receipt.get('revision')==run['revision'] and receipt.get('fingerprint')==run['fingerprint']
            and receipt.get('assignment_revision')==run.get('assignment_revision',0))
def accepted(run,row):
    return current(run) and row.get('_backend_accepted') is True
def leaves(profile):
    return set(profile['assignable_paths'])
