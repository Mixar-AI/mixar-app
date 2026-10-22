<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Isolated replay fixtures

These replays require an isolated `MIXAR_QA=1` profile with the harness's
in-memory credential backend. Never run provider-setting fixtures against a
normal app profile.

- `profile_provider_settings_e2e` and `modal_dialog_docks_lock_e2e` establish
  explicit member UI state, including the account name, and restore Guest/name
  state. They do not authenticate a member or contact a provider.
- `moodboard_deferred_mesh_e2e` begins with an empty authoritative catalog:
  Add Mesh remains available; unavailable generation templates are hidden.
- `moodboard_drawer_resize_links_e2e` and `video_reference_modes_e2e` use the
  harness's synthetic catalog fixture. The fixture blocks queue submission;
  video-reference coverage additionally blocks HTTP/WebSocket writes and uses
  the local send probe. These prove native UI behavior, not provider delivery.
- `local_model_name_privacy_e2e` uses a synthetic Windows path on every host.
  `PureWindowsPath` derives its request basename on macOS/Linux too; a failed
  relay is asserted before attempting to decode a response body. Its successful
  local-store stub does not create a credential record, so the saved sheet can
  show “Key needed on this computer”; this replay certifies basename privacy,
  not activation or device credential persistence.

The native Splat pane (`agent_ui_tabsplat_state.cc`) requires both `p_mode`
and `p_lod` RNA enums before exposing its picker. The synthetic World Labs
model supplies `mode` and `lod` enum parameters; the video-reference replay
checks the registered RNA schema before interacting with the pane. A generic
quality-only model is not a valid native Splat fixture. No cached production
catalog or local backend is required.

The video replay parks the real connection manager before installing its local
send probe. Otherwise the transport fence causes reconnect callbacks to reset
the scene to OFFLINE after the probe sets IDLE. This is process-scoped and does
not reconnect on cleanup: only the disposable app is shut down afterwards. The
real `can_send` predicate remains intact; clean-draft readiness is asserted both
before inserting legacy movie attachments and after removing them.
