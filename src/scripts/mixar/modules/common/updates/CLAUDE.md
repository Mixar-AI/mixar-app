<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Self-Update (`modules/common/updates/`)

One **Restart & Update** click stages the release installer, spawns a detached helper, quits, and relaunches; the downloads page is the fallback. Decisions live in `core/install_flow.py` (`plan_restart`, `apply_and_restart`) so they are testable under the `bpy` mock; config is `mixar.json` → `updates.{channel,check_delay_seconds,auto_download,downloads_url}`. Install paths carry no version (pinned by `tests/test_update_packaging_paths.py`). Windows staging lives in `%ProgramData%\Mixar\Updates` (a per-machine MSI runs elevated and must read the installer from a shared location); the installer is trusted only after the backend `sha256` matches AND its signature matches the running app's; the detached helper never lives in the install directory; a quit that does not happen is recovered by a 15s watchdog that returns state to READY.
