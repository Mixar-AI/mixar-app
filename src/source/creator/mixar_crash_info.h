/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup creator
 *
 * The symbolication block of the crash log (`mixar.crash.txt`).
 *
 * Blender's crash log names frames as symbol + offset, which a stripped
 * release binary can only answer with the nearest global symbol (macOS,
 * Linux) or nothing at all (Windows without a PDB). This block adds what an
 * offline symbolizer needs to turn every frame into function + file:line:
 *
 *   # mixar symbolication v1
 *   mixar_version 4.3.7
 *   git_sha 0123456789abcdef...
 *   arch arm64
 *   image base=0x100a4c000 vmaddr=0x100000000 size=0x7a1c000 id=<debug id> name=Mixar
 *   frame 0 0x0000000102a52578
 *   ...
 *
 * `id` is the debug id the release pipeline files the symbols under: the
 * Mach-O LC_UUID (macOS), the GNU build-id (Linux) or the PDB GUID + age
 * (Windows), all lower-case hex without separators. Only images that hold a
 * frame are listed, by file name only (never a path).
 *
 * Written from inside the crash handler, after the existing backtrace, with
 * fixed-size buffers and no allocation.
 */

#pragma once

#include <cstdio>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Append the symbolication block to `fp`.
 * \param os_info: `EXCEPTION_POINTERS *` on Windows (frames are walked from
 * the faulting context), unused elsewhere (the current stack is walked).
 */
void mixar_crash_info_write(FILE *fp, const void *os_info);

#ifdef __cplusplus
}
#endif
