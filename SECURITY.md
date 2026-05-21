<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Security Policy

## Reporting A Vulnerability

Report security issues privately to:

- Rahul `<rahul@mixar.app>`

Do not open a public GitHub issue for vulnerabilities, secrets, credential leaks, exploit details, or private user data.

Include:

- A concise description of the issue
- Affected version, commit, or release artifact
- Reproduction steps, if safe to share privately
- Impact and any known workaround

Do not include real Mixar account passwords, API keys, production tokens, private scene data, or third-party secrets in reports.

## Scope

In scope:

- Mixar Blender-side client code in this repository
- Build, packaging, update, and source-distribution behavior for this client
- Client-side handling of tokens, local credentials, user files, and network requests

Out of scope for this public repository:

- Mixar hosted backend service source code
- Mixar production infrastructure
- Third-party platform vulnerabilities unless they directly affect the Mixar client

## Supported Versions

The current public source release is the supported security review target.

For release source mapping, see [SOURCE_CORRESPONDENCE.md](SOURCE_CORRESPONDENCE.md).
