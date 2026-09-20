<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Local agent archive

`~/.mixar/agent_history/<session_id>/manifest.json` links an authenticated owner's
conversation to `scene.mixar_op_history_id`. `events/*.jsonl` is an ordered,
segmented journal; each event includes run/task identifiers. Full message bodies,
scripts and attachments live in content-addressed `blobs/` files. No SQLite.

A background authenticated WebSocket pull writes and fsyncs records before
acknowledging them. Retries are idempotent. When the backend advertises
`agent_history_v2`, image bytes never travel on the agent socket: sync frames carry
a `{seq, bytes, sha256}` reference and the archive thread fetches each image over
`GET /api/v1/agent/history/blob`, verifies it, and rebuilds the original record
before writing. A pending sync reply is awaited for as long as its connection lives;
it is never abandoned on a timer and re-requested. A process lock serializes local writes;
an incomplete final JSONL line is repaired before appending. Corrupt complete
records fail explicitly. No automatic age-based pruning is applied to local history.
The UI chat archive and scene operation history remain separate views.

Disk failures or expired backend delivery produce a warning toast and are never
an excuse to rerun tool effects. Transient transport states (a slow reply, a dropped
connection) are logged only; they retry on their own and the connection indicator
already shows them. Gap state is persisted in the session manifest.
Absolute local paths never leave the client. The backend's existing execution
checkpoints/traces have independent retention; this archive does not delete them.
