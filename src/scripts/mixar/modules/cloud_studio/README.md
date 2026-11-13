<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# cloud_studio

How Mixar Game Studio drives this app when it runs in a cloud workstation.

A person directs a game project from a web page. The work is done by the agent in this app,
running in a GPU sandbox next to a Godot editor. The backend (`mixar-backend/modules/studio`)
uploads a small **bridge** into the sandbox when the workstation starts; the bridge runs inside
the app on a timer and passes requests in and the conversation out through files. This module is
what the bridge calls.

```text
web page ─▶ backend ─▶ files in the sandbox ─▶ bridge (app timer) ─▶ cloud_studio.api ─▶ the app's own operators
```

## Why it is here

The bridge used to reach into the chat's internals directly (`scene.mixie_chat_messages`, the
session manager, `rules_api`, operator names). Those change with the app; the bridge ships with
the backend. `api` is the one place where the two meet, kept and tested with the app:

| Function | Does |
| --- | --- |
| `chat_state(scene)` | `state`, `phase` (`idle` / `working` / `asking`), `run_open`, `can_send`, `why_not` |
| `conversation(scene, limit)` | The last bubbles as plain data: text, plan items, steps, choices |
| `session_id(scene)` | The agent session of the scene's chat |
| `send(scene, text, images, folder)` | The person's message, with images from the bridge's own folder attached |
| `choose(bubble_id, value)` · `stop()` | Press a choice the agent offered · stop the turn |
| `set_context_rule(scene, mark, text)` | Add or replace the one global rule starting with `mark` (the project's bible) |
| `save_scene(path, root)` · `open_scene(path, root)` | Save / open a `.mixar` under `root` and nowhere else |

Acting functions return `(ok, error)`. They call the same operators the UI does
(`mixie_chat.send_message`, `mixie_chat.add_image_from_file`, `mixie_chat.select_slot_action`,
`mixie_chat.abort_session`, `wm.save_as_mainfile`, `wm.open_mainfile`) inside a
`temp_override` of the main window.

## Rules

- Nothing here starts by itself, opens a port, or talks to the backend. A desktop that is not a
  cloud workstation never calls it.
- A path from outside is never trusted: `shape.scene_file` accepts a `.mixar` inside the given
  folder only; `shape.attachable` accepts an existing file directly inside the bridge's folder only.
- The rule the studio sets must start with its mark; anything else is refused, so the bridge can
  never rewrite a person's own rules.
- Add functions, never change what one returns. Bump `API_VERSION` when you add: the bridge
  checks it and falls back to its own older code for a build that predates a function.

## Tests

`tests/test_cloud_studio.py` covers the pure parts (`shape.py`) outside the app. The acting
functions are covered in the real app by the backend's bridge scenario
(`studio_bridge_e2e`, run in a sandbox with the QA harness).
