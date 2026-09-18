<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Archive client architecture

`core/sync.py` runs one polling writer per authenticated WebSocket lifecycle and routes
bounded read requests off the receive thread. Blender scene-ID discovery alone is
scheduled on the main thread; a capture that fails or is dropped returns promptly and
honours stop, so the poll loop retries rather than stalling. `core/store.py` has no
bpy or networking dependency.
Blobs commit before the append-only JSONL index; the manifest cursor commits last.
Replaying after a torn final line or a lost acknowledgement cannot duplicate a
sequence. Reads never execute saved scripts. Server owner ID must match the local
manifest. Metadata and blob paths are locally derived from validated opaque IDs.

Both peers negotiate `agent_history_v1`. The authenticated background writer uses
`agent.history_sync` and acknowledges only after durable local writes. Known
session IDs let a restarted app discover pending records under a new instance ID.
Disk/sequence/owner failures never acknowledge or execute saved content. A changed
epoch records a gap. A missing manifest beside an existing journal fails closed.

The module follows the operation-history file approach but has its own retention:
no automatic 15-day pruning and no silent best-effort acknowledgement. Full-history
backfill, Windows runtime QA and recovery from permanent server gaps are separate
work. Live backend checkpoints/traces are not deleted by this feature.

Validation: `tests/test_agent_history.py`; in a QA app execute
`tests/qa/agent_history_smoke.py` through `runpy.run_path`, wait for two syncs, call
`request_read()`, then `finish()`. Capture and inspect the viewport after assertions.
This smoke fixture uses this checkout's source and a deterministic transport, not
a paid-model run or a rebuilt release bundle.
