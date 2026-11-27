# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins two Vulkan overlays, each upstream's file plus one hunk fenced by
`/* MIXAR-2149 begin */ ... /* MIXAR-2149 end */`:

- `src/source/blender/gpu/vulkan/vk_pixel_buffer.cc`: `VKPixelBuffer::get_native_handle`
  (Cycles' Vulkan GPU-interop display buffer) ignored a failed allocation.
  `VKBuffer::create` leaves `allocation_` null when VMA cannot allocate, and
  `export_memory_get` handed that null allocation to `vmaGetAllocationInfo`, which
  crashed in `VmaAllocator_T::GetAllocationInfo` (mixar-backend#2149, Windows/NVIDIA,
  a Cycles viewport). The overlay returns no handle; Cycles releases the interop
  buffer, the path it already takes without external-memory support.
- `src/source/blender/gpu/vulkan/vk_texture.cc`: Cycles then falls back to mapping the
  same pixel buffer (which fails) and still uploads it to the display texture.
  `VKTexture::update_sub` recorded a copy from its null VkBuffer, which crashed inside
  the NVIDIA Vulkan driver. The overlay skips that upload.

Both were reproduced on a 4 GB NVIDIA card by filling device memory before
switching a Cycles GPU viewport to Rendered."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
MARKED = re.compile(r"[ \t]*/\* MIXAR-2149 begin \*/\n.*?[ \t]*/\* MIXAR-2149 end \*/\n\n?", re.S)
FILES = ("vk_pixel_buffer.cc", "vk_texture.cc")


def _overlay(name: str) -> Path:
    return ROOT / "src/source/blender/gpu/vulkan" / name


def _upstream(name: str):
    # A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout
    # of its own; read the main checkout's, as `settings.sh` does.
    for base in (ROOT, ROOT.parents[1]):
        path = base / "upstream/source/blender/gpu/vulkan" / name
        if path.exists():
            return path
    return None


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _body(text: str, signature: str) -> str:
    start = text.index(signature)
    return text[start : text.index("\n}\n", start)]


def test_an_unallocated_pixel_buffer_is_never_exported():
    body = _body(_read(_overlay("vk_pixel_buffer.cc")),
                 "GPUPixelBufferNativeHandle VKPixelBuffer::get_native_handle()\n{")
    create = body.index("  create(true);\n")
    guard = body.index("  if (!buffer_.is_allocated()) {\n", create)
    export = body.index("buffer_.export_memory_get(memory_size)")
    assert create < guard < export
    assert "return native_handle;" in body[guard : body.index("/* MIXAR-2149 end */")]


def test_an_unallocated_pixel_buffer_is_never_uploaded():
    text = _read(_overlay("vk_texture.cc"))
    body = _body(text, "void VKTexture::update_sub(int mip,\n                           int offset_[3],")
    guard = body.index("    if (!pixel_buffer->buffer_get().is_allocated()) {\n      return;\n    }\n")
    use = body.index("    buffer = pixel_buffer->buffer_get().resource();\n")
    record = body.index("context.render_graph().add_node(copy_buffer_to_image);")
    assert guard < use < record


@pytest.mark.parametrize("name", FILES)
def test_the_overlay_only_differs_from_upstream_in_the_marked_hunk(name):
    """Keep each overlay a one-hunk patch so an upstream bump is a re-copy."""
    upstream = _upstream(name)
    if upstream is None:
        pytest.skip("no upstream checkout")
    up = _read(upstream)
    ov = _read(_overlay(name))
    assert MIXAR_SPDX in ov
    assert len(MARKED.findall(ov)) == 1
    assert MARKED.sub("", ov.replace(MIXAR_SPDX, "", 1)) == up
