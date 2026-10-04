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
`agent.history_sync` and acknowledges only after durable local writes. With
`agent_history_v2` the request adds `blobs: "reference"`; `core/blobs.py` fetches each
referenced image over HTTP on the archive thread, checks length and SHA-256 against
the descriptor, re-inserts the base64 and lets `store.write_batch` verify the
unchanged `event_id`. An unfetchable blob is not acknowledged and is re-delivered.
The reply wait is bound to the connection (`REPLY_WAIT_SECONDS` is only a guard):
abandoning a slow reply on a timer re-queues the same batch behind the one in
flight and starves keepalive pings and tool replies on slow links. When one blob
fails, the records before it are still archived and acknowledged, and the poll
interval backs off (up to `BACKOFF_MAX_SECONDS`) instead of re-downloading every
two seconds. Only image records are materialized, and only in reference mode. Known
session IDs let a restarted app discover pending records under a new instance ID.
Disk/sequence/owner failures never acknowledge or execute saved content. A changed
epoch records a gap. A missing manifest beside an existing journal fails closed.

Idle sync keeps the two-second transport poll but discovers historical sessions
from disk at most once per 30 seconds; current scene sessions are included on
every poll. Repeated empty, available packets reuse only a successfully committed
cursor. Under the archive lock, `core/idle_cache.py` checks the manifest, events
directory and final journal's file identities before reuse, avoiding journal
re-parsing and unchanged manifest fsyncs. Any disk or scene binding change,
incoming record, gap, epoch change, or process restart uses the full validation
and recovery path. The cache is bounded to 128 sessions and stores no record data.

`MIXAR_AGENT_HISTORY_DIR` overrides the default `~/.mixar/agent_history` root.
QA launches must set it to an isolated directory: a Blender profile alone does
not isolate the archive. Fixtures and benchmarks use temporary roots exclusively.

The module follows the operation-history file approach but has its own retention:
no automatic 15-day pruning and no silent best-effort acknowledgement. Full-history
backfill, Windows runtime QA and recovery from permanent server gaps are separate
work. Live backend checkpoints/traces are not deleted by this feature.

Validation: `tests/test_agent_history.py`, `tests/test_agent_history_sync.py`,
`tests/test_agent_history_blobs.py`; in a QA app execute
`tests/qa/agent_history_smoke.py` through `runpy.run_path`, wait for two syncs, call
`request_read()`, then `finish()`. Capture and inspect the viewport after assertions.
This smoke fixture uses this checkout's source and a deterministic transport, not
a paid-model run or a rebuilt release bundle.
`tests/qa/agent_history_idle_probe.py` replays empty polls against temporary large
journals, asserts zero warm journal reads/manifest writes and verifies that a
subsequent real record still commits; its timings isolate the archive hot path.
