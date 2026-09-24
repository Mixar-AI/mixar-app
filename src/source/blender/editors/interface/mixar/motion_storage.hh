/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "UI_mixar_motion.hh"
#include <memory>
#include <vector>

namespace blender::ui {
/** Native buttons are occasionally copied for event handling. Deep-copy that
 * rare case; ordinary redraws move storage and native controls allocate none. */
class MixarMotionStorage {
  std::unique_ptr<MixarButtonMotion> data_;

 public:
  MixarMotionStorage() = default;
  MixarMotionStorage(MixarMotionStorage &&) = default;
  MixarMotionStorage &operator=(MixarMotionStorage &&) = default;
  MixarMotionStorage(const MixarMotionStorage &other)
      : data_(other.data_ ? std::make_unique<MixarButtonMotion>(*other.data_) : nullptr)
  {
  }
  MixarMotionStorage &operator=(const MixarMotionStorage &other)
  {
    data_ = other.data_ ? std::make_unique<MixarButtonMotion>(*other.data_) : nullptr;
    return *this;
  }
  explicit operator bool() const
  {
    return bool(data_);
  }
  MixarButtonMotion &operator*()
  {
    return *data_;
  }
  const MixarButtonMotion &operator*() const
  {
    return *data_;
  }
  void reset()
  {
    data_.reset();
  }
  void ensure()
  {
    if (!data_) {
      data_ = std::make_unique<MixarButtonMotion>();
    }
  }
};

struct Block;
/** Preserve paint independently of native operator ownership/reuse. */
class MixarMotionRebuild {
  std::vector<MixarMotionStorage> states_;

 public:
  explicit MixarMotionRebuild(Block &block);
  void apply(Block &block);
};
}  // namespace blender::ui
