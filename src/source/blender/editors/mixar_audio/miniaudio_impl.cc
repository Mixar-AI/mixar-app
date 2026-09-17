/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edmixaraudio
 *
 * The one translation unit that compiles miniaudio's implementation.
 *
 * It carries nothing of its own: the configuration (every `MA_NO_*` opt-out)
 * lives in `mixar_audio_miniaudio.hh` so that this TU and the capture TU
 * compile the same declarations. Defining those macros here instead would
 * give the two files different `ma_device` layouts.
 */

#define MA_IMPLEMENTATION

#include "mixar_audio_miniaudio.hh"
