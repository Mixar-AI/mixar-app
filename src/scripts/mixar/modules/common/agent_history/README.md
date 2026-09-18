<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Local agent archive

`~/.mixar/agent_history/<session_id>/manifest.json` links an authenticated owner's
conversation to `scene.mixar_op_history_id`. `events/*.jsonl` is an ordered,
segmented journal; each event includes run/task identifiers. Full message bodies,
scripts and attachments live in content-addressed `blobs/` files. No SQLite.

A background authenticated WebSocket pull writes and fsyncs records before
acknowledging them. Retries are idempotent. A process lock serializes local writes;
an incomplete final JSONL line is repaired before appending. Corrupt complete
records fail explicitly. No automatic age-based pruning is applied to local history.
The UI chat archive and scene operation history remain separate views.

Disk failures or expired backend delivery produce a warning toast and are never
an excuse to rerun tool effects. Gap state is persisted in the session manifest.
Absolute local paths never leave the client. The backend's existing execution
checkpoints/traces have independent retention; this archive does not delete them.
