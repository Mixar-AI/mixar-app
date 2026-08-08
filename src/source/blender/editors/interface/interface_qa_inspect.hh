/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar QA harness: serialize every live UI widget (uiBut) of every window —
 * regular regions, global areas (topbar/statusbar) and screen-level popup
 * regions — to JSON, so external test drivers can target widgets by meaning
 * (operator idname, property, label) instead of guessed pixel coordinates.
 *
 * Read-only introspection over already-built uiBlocks; never mutates UI state.
 * Consumed by ``WindowManager.mixar_qa_ui_dump`` (rna_wm_mixar.cc).
 */

#pragma once

#include <string>

struct wmWindowManager;

std::string Mixar_ui_qa_inspect_json(const wmWindowManager *wm);
