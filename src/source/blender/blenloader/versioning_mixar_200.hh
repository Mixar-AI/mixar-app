/* SPDX-FileCopyrightText: 2024 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup blenloader
 *
 * Mixar-specific versioning declarations.
 */

#pragma once

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct Main;

/**
 * Run Mixar-specific versioning on file load.
 * Called from blo_do_versions_500() in versioning_500.cc.
 */
void blo_do_versions_mixar(Main *bmain);

}  // namespace blender
