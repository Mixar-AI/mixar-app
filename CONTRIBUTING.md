<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Contributing

Mixar is publishing the Blender-side client source first. External pull requests are not open for general contribution yet.

For questions, build help, and general discussion, the fastest channel is the **Mixar Discord**: https://discord.gg/HJNMUesyp. Use GitHub issues for the specific reports listed under "Before Opening An Issue" below.

## Current Contribution Status

- Public source: open
- Public issues: limited to source-availability, build, license, and security-process questions
- External pull requests: not accepted until Mixar publishes the CLA workflow
- Contributor agreement: CLA required before Mixar accepts substantial external contributions

Pull requests opened before the CLA process is published may be closed without review.

## Before Opening An Issue

Check whether the issue is about this public client repository.

Use this repository for:

- Client-side build problems
- Source availability questions
- License and notice questions
- Blender-side client behavior that can be reproduced from public source

Do not post:

- Security vulnerabilities or suspected secrets; follow [SECURITY.md](SECURITY.md)
- Mixar account credentials, API keys, tokens, logs containing secrets, or private scene data
- Requests for Mixar backend source code

## Development Rules

Follow the same structure used by the repo:

- Put durable Mixar source changes under `src/`
- Put Python module code under `src/scripts/mixar/modules/`
- Put C/C++ Blender customizations under `src/source/blender/`
- Keep reusable logic in the relevant module or `common`
- Use the build scripts instead of building directly from generated `source/`
- Keep environment variables in `.env` locally and never commit `.env`

## License Requirements

Every new file must carry SPDX license metadata.

For source files, add an inline SPDX header. For binary assets or formats that cannot carry comments, add an entry to `REUSE.toml`.

### How SPDX Headers Get Added

You can add headers manually using the commands below, or install [pre-commit](https://pre-commit.com/) to have them added at commit time. CI runs `reuse lint` on every PR and will fail the build if any file lacks copyright or license information.

### Optional: Local Pre-Commit Hook

```bash
pip install pre-commit
pre-commit install
```

Configured hooks live in `.pre-commit-config.yaml`. This is purely a developer convenience and is not required.

### Manual Commands

```bash
# Add headers in place to a specific file
python3 scripts/open_source/apply_spdx_headers.py --write path/to/file.py

# Apply across all changed files using sibling-license inference
python3 scripts/open_source/apply_spdx_headers.py --write --infer-from-siblings $(git diff --name-only)

# Full REUSE compliance check (same as CI)
reuse --no-multiprocessing lint
```

## Audit Checks

For open-source publication checks, use:

```bash
scripts/open_source/run_phase1_audit.sh
```
