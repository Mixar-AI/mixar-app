/* SPDX-FileCopyrightText: 2001-2002 NaN Holding BV. All rights reserved.
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup DNA
 */

#pragma once

#include <cstdint>

namespace blender {

/**
 * FileGlobal stores a part of the current user-interface settings at
 * the moment of saving, and the file-specific settings.
 */
struct FileGlobal {
  /** Needs to be here, for human file-format recognition (keep first!). */
  char subvstr[4] = "";

  short subversion = 0;
  short minversion = 0, minsubversion = 0;

  /* Mixar file version fields, repurposing the original 6-byte _pad.
   * SDNA handles the field rename: old files (which had char _pad[6]) read as 0,
   * new files store actual Mixar version values.
   * 3 shorts = 6 bytes = same size as the original _pad[6]. */
  short mixar_version = 0;     /* MIXAR_FILE_VERSION when saved; 0 for pre-versioning files */
  short mixar_subversion = 0;  /* MIXAR_FILE_SUBVERSION when saved */
  short mixar_min_version = 0; /* Minimum Mixar version that can read this file */

  struct bScreen *curscreen = nullptr;
  struct Scene *curscene = nullptr;
  struct ViewLayer *cur_view_layer = nullptr;
  void *_pad1 = nullptr;

  int fileflags = 0;
  int globalf = 0;
  /** Commit timestamp from `buildinfo`. */
  uint64_t build_commit_timestamp = 0;
  /** Hash from `buildinfo`. */
  char build_hash[16] = "";
  /** File path where this was saved, for recover. */
  char filepath[/*FILE_MAX*/ 1024] = "";

  /* Working colorspace, for automatic conversion. Note the matrix is
   * the source of truth, the name is only for user interface and diagnosis. */
  char colorspace_scene_linear_name[/*MAX_COLORSPACE_NAME*/ 64] = "";
  float colorspace_scene_linear_to_xyz[3][3] = {};
  int _pad2[3] = {};
};

/* minversion: in file, the oldest past blender version you can use compliant */
/* example: if in 2.43 the meshes lose mesh data, minversion is 2.43 then too */
/* or: in 2.42, subversion 1, same as above, minversion then is 2.42, min subversion 1 */
/* (defines for version are in the BKE_blender_version.h file, for historic reasons) */

}  // namespace blender
