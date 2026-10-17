<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Mixar

Mixar is an AI-powered 3D content creation tool built as a custom fork of [Blender](https://www.blender.org) 5.2. It adds an AI chat agent that can drive Blender, a layered texture-painting system, AI-assisted 3D generation, and a set of Mixar-native editor spaces — while keeping everything you already use from Blender.

This repository is the source for the **Mixar desktop app** (the Blender-side client). Mixar's hosted AI backend remains a separate, closed-source service; the app talks to it over the network.

> **Project status:** v2.0.0 — first public source release. Built on Blender 5.2.

---

## What you can do with Mixar

The app ships everything Blender already does. On top of that:

- **AI agent chat** — Mixie, an in-app chat agent that can plan and execute multi-step tasks against your scene: model from prompts, paint textures, set up materials, fix UVs, suggest fixes, etc.
- **Layer-based texture painting** — Photoshop-style stacked layers with node-driven materials, masks, modifiers, baking, UDIM support, procedural materials, decals, and asset export.
- **AI 3D generation** — text-to-3D and image-to-3D mesh generation via integrated providers (Hunyuan models and others), with retopology and auto-UV-unwrap.
- **Moodboards and scene generation** — drop reference images, generate scenes from boards, do 360° lookdev, image-to-3D.
- **Asset search** — neural embedding search across your asset library.
- **Bring-your-own-key (BYOK)** — plug in your own OpenAI / Anthropic / other provider API keys instead of using Mixar's hosted LLM credits.
- **Mixar-native editor spaces** — dedicated Layers, Properties, Assets, and Chat editors integrated into the Blender workspace.

The Blender features you already know (sculpting, animation, simulation, rendering, scripting) are unchanged and available alongside Mixar's additions.

## What you need to actually use AI features

Mixar's AI features (the chat agent, image-to-3D, hosted generation) call **Mixar's hosted backend**. To use those:

- You need a Mixar account at [mixar.app](https://www.mixar.app).
- The desktop app authenticates via browser SSO and talks to the backend over HTTPS/WebSocket.
- With **bring-your-own-key**, you can route the chat agent through your own provider account (OpenAI, Anthropic, etc.) without consuming Mixar credits.

The non-AI parts of the app (Blender features, the layered paint module, file IO, etc.) work without a Mixar account.

---

## Building from source

Mixar is a Blender fork with a custom overlay, so building it = building Blender + applying the Mixar overlay + linking a few extra C++ targets.

### Prerequisites

You need everything required to build Blender 5.2 itself. Follow Blender's official build instructions for your platform first, and confirm a clean Blender build works before adding Mixar:

- macOS / Linux / Windows — see <https://developer.blender.org/docs/handbook/building_blender/>

Mixar additionally needs **Python 3.11+** and **rsync** on the build host (macOS and Linux ship these; on Windows, install via WSL or Cygwin if missing).

The native Windows build (`scripts/windows/build.bat`) requires **Visual Studio
2022 17.14.14 or newer** with the C++ workload. Blender 5.2 embeds **Python 3.13**
from the pinned `upstream/lib/windows_x64` libraries; installing a newer host
Python does not replace those libraries. Old Python cache entries are cleared
automatically while compiled objects are kept.
Ninja builds select the Visual Studio installation's default toolset explicitly.
When that compiler changes, old CMake configuration is backed up under the build
directory's `.mixar-toolchain-backups/` before configuring again. Target objects
are retained; reapply any options previously set only in the CMake cache.

For Ubuntu, install the host dependencies used by the Linux build:

```bash
sudo apt-get install -y build-essential cmake gcc-14 g++-14 git git-lfs \
  ninja-build python3-dev python3-venv rsync pkg-config \
  libcurl4-openssl-dev libdbus-1-dev libegl-dev libgl-dev libice-dev libsm-dev \
  libwayland-dev libx11-dev libxcursor-dev libxext-dev libxi-dev \
  libxinerama-dev libxkbcommon-dev libxrandr-dev libxxf86vm-dev \
  patchelf wayland-protocols xz-utils xvfb zstd
```

Use a native Linux filesystem for the build checkout. Initialize the pinned
Blender source and Linux libraries without updating Blender to another commit:

```bash
git submodule update --init upstream
git -C upstream -c submodule.lib/linux_x64.update=checkout submodule update --init lib/linux_x64
git -C upstream/lib/linux_x64 lfs pull
```

Set `CC=gcc-14` and `CXX=g++-14` for the build. GPU-enabled builds additionally
need the CUDA toolkit and OptiX headers configured by the Linux release workflow;
`MIXAR_CUDA=0 make build` selects a local CPU-only Cycles build when those are
unavailable. This setting does not disable viewport GPU drawing.

### Quickstart

```bash
# 1. Clone with the upstream Blender submodule
git clone --recursive https://github.com/Mixar-AI/mixar-texture-painting.git
cd mixar-texture-painting

# 2. Initialise submodules and LFS-tracked assets (if your clone skipped recursive)
make init

# 3. Configure runtime environment (copy template, fill in any backend URLs you want to target)
cp .env.example .env
$EDITOR .env

# 4. Full build: overlay + CMake + compile + bundle
make build
```

Built binaries land under `build/<MIXAR_ENV>/bin/`. The default `MIXAR_ENV=Prod` produces a release-mode Mixar app pointed at `https://api.mixar.app`. Set `MIXAR_ENV=Dev` in `.env` for a dev build pointed at a development backend.

For GUI automation, `MIXAR_ENV=Dev` is required. If the QA harness should
sign in without opening a browser, also configure the internal
`DEV_BYPASS_*` values described in `.env.example` before building; those
values are baked into Dev bundles and are rejected for every other build
environment.

### Common build targets

```bash
make clean_build    # wipe the generated source/ tree and rebuild from scratch
make install        # install embedded Python packages into the built app
```

On Linux, create the portable distribution after a successful production
build with `scripts/unix/package_linux.sh --env Prod`. The archive is written
to `dist/`; extract it and run `./mixar` from the extracted directory. CI targets
Ubuntu 24.04 on x86_64 and bundles Python and Blender's pinned `lib/linux_x64`
libraries; normal Ubuntu desktop graphics and network libraries remain system
dependencies. CI can reconstruct the Blender bundle
from the exact upstream source and library gitlinks when its S3 cache is empty;
the cache is not a manual prerequisite.

**Do not run `cmake` or `make` directly inside `source/`** — that directory is generated by the overlay step. Always go through `make build`.

### Run and test

```bash
make run                 # launch build/Dev
make run Prod            # launch build/Prod

# Standalone tests run outside Blender; conftest.py supplies bpy stubs.
python -m pip install pytest Pillow numpy
python -m pytest -q
```

On Linux, the run target launches `build/<environment>/bin/mixar` directly;
on macOS, it opens the corresponding `Mixar.app`. To pass application options,
use `scripts/unix/run.sh Prod --background --factory-startup`.
If NVIDIA/Wayland reports `EGL_BAD_ALLOC` while creating the floating Agent
window, try `WAYLAND_DISPLAY= scripts/unix/run.sh Dev` to use X11/XWayland
instead.

To exercise an installed Linux build without a backend account, run
`build/Dev/bin/mixar --background --factory-startup --python-exit-code 1 --python tests/qa/linux_build_smoke.py`.
The smoke test checks runtime imports, a packed image material, saving and
reopening a scene, and a small CPU Cycles render. It writes the scene, render
and JSON verdict to a temporary directory, or to `MIXAR_SMOKE_OUT` when set.
Use an isolated `MIXAR_USER_RESOURCES` directory when running it.

Use a Python environment with the test dependencies installed; Blender's
embedded Python receives runtime packages during `make build`, but it does not
include pytest by default.

### Build flow

On macOS, `make build` finds an existing CMake in Homebrew's standard locations
or `/Applications/CMake.app` when a GUI terminal omits it from `PATH`. An existing
`cmake` on `PATH` takes precedence. Install CMake first if none is found.
Build and launch from the same checkout: `make build` defaults to Prod, so use
`make run Prod`. A Dock shortcut to `/Applications/Mixar.app` opens that installed
copy, not the app under this checkout's `build/Prod/bin/`.

Mixar uses an overlay pattern so version upgrades from upstream Blender stay clean:

```text
upstream/               Blender 5.2 source (git submodule)
src/                    Mixar's overlay source — Python addon + C++ additions
source/                 Generated working tree: upstream/ copied here, then src/ rsync'd on top
build/<env>/            CMake build directory
```

1. `make init` pulls the `upstream/` submodule.
2. `make build` invokes `scripts/unix/build.sh` (or `build.bat` on Windows), which:
   - rsyncs `upstream/` → `source/`
   - rsyncs `src/` over `source/`
   - generates `source/source/creator/mixar_env_config.h` from `.env`
   - configures and builds via CMake
   - installs Python packages into the embedded Blender Python

On Windows, both overlay passes replace files when their timestamps or sizes
differ, even when upstream is older than a previous branch's override. After
both copies succeed, files absent from both inputs move to
`build/.mixar-overlay-backups/`, preventing old headers from shadowing their
replacements. Generated environment headers and retained-file timestamps are
preserved. Every build reruns CMake after the overlay so restored CMake files
remove stale targets; existing object files are retained for incremental compilation.
Bundled configuration, package installation and import checks use Python's `-s`
flag, so packages in the user's Python installation cannot affect those steps.
The Mixar-owned `src/scripts/mixar/` package is mirrored separately to remove
retired Python directories, preserving the generated `_build_env.py` marker.
The mirror excludes local virtual environments and Python caches and refuses a
missing source package. Other input files retain their incremental copy behavior.

---

## Repository layout

```text
upstream/               Blender source submodule (huge — pulled with --recursive or `make init`)
src/                    Mixar overlay — what gets layered on top of Blender
  scripts/mixar/        Mixar's Blender Python addon (chat UI, paint, BYOK, etc.)
  source/blender/       C++ additions to Blender (Mixar editor spaces, paint kernel)
  source/creator/       Mixar startup / auth / native dialog code
cmake/mixar_overrides.cmake  Mixar-specific CMake configuration
scripts/unix/           macOS / Linux build scripts
scripts/windows/        Windows build scripts
tests/                  Pure-pytest tests (run from repo root with bpy stubbed)
```

## What's in this repository — and what isn't

**Included:**

- All Mixar desktop-app source (Python addon + C++ overlay)
- Build scripts for macOS, Linux, and Windows
- License documentation, SPDX metadata, asset provenance records
- Public contribution, security, and support documentation

**Not included (and won't be):**

- Mixar's hosted AI backend source code
- Production secrets, signing certificates, deployment configuration
- Internal release pipelines, CI infrastructure, and code-signing tooling
- Internal planning documents, roadmaps, or design RFCs

---

## License

Mixar source is published under **GPL-3.0-or-later**, the same license family as Blender. Per-file licensing is recorded via [SPDX headers](https://spdx.dev/) and [REUSE.toml](REUSE.toml):

- **Mixar-original code:** GPL-3.0-or-later
- **Blender-derived files** (modifications of upstream Blender source): GPL-2.0-or-later (inherited from upstream)
- **Files derived from [ucupaint](https://github.com/ucupumar/ucupaint)** (parts of the paint module): GPL-3.0-or-later, with attribution to ucupumar — see [NOTICE.md](NOTICE.md)
- **Mixar brand assets** (logos, icons, wordmarks): a separate non-GPL brand license — see [LICENSES/LicenseRef-Mixar-Brand.txt](LICENSES/LicenseRef-Mixar-Brand.txt) and [TRADEMARKS.md](TRADEMARKS.md)

For the canonical license map: file-level SPDX headers, [REUSE.toml](REUSE.toml), [LICENSE](LICENSE), and the texts in [LICENSES/](LICENSES/).

---

## Contributing

External pull requests are **not** open yet — see [CONTRIBUTING.md](CONTRIBUTING.md) for the current contribution status and what to expect when the CLA process launches. Bug reports and source-availability questions are welcome; security issues must be reported privately per [SECURITY.md](SECURITY.md).

## Community and support

- **Discord:** https://discord.gg/YVqvkQx8rX — fastest channel for build help, questions, and discussion with maintainers and other Mixar users.
- **GitHub issues:** for reproducible bugs from the public source, build problems, and license / documentation questions. See [SUPPORT.md](SUPPORT.md) for full scope.
- **Security:** report privately per [SECURITY.md](SECURITY.md).
- **Hosted Mixar service:** sign in at [mixar.app](https://www.mixar.app) for customer-account support.

## Acknowledgements

Mixar stands on shoulders. The Blender community built the renderer, sculpting, animation, modeling, and scripting foundations the entire app is layered on top of. The [ucupaint](https://github.com/ucupumar/ucupaint) project by ucupumar inspired and seeded large parts of the layer-based paint system. Open-source 3D-generation models from the Hunyuan and Stable Diffusion ecosystems power image and mesh generation. Thank you.
