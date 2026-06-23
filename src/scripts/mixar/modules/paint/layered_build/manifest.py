# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure manifest helpers for the layered-material builder (no bpy required).

Encodes the map->channel binding rules verified against the paint module:
- basecolor -> "Color" channel, sRGB, regular override slot ("source")
- roughness -> "Roughness", Non-Color, regular slot
- metallic  -> "Metallic", Non-Color, regular slot
- normal    -> "Normal" channel, tangent-space normal slot ("source_1"), NORMAL_MAP
- height    -> "Normal" channel (NORMAL is the height channel), regular slot, BUMP_MAP
- ao        -> "Ambient Occlusion", Non-Color, regular slot
"""

from dataclasses import dataclass
from typing import Optional


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class ChannelBinding:
    channel_name: str
    non_color: bool
    override_slot: str            # "source" (regular/override) or "source_1" (override_1)
    normal_map_type: Optional[str]  # None | "BUMP_MAP" | "NORMAL_MAP"


_BINDINGS = {
    "basecolor": ChannelBinding("Color", False, "source", None),
    "roughness": ChannelBinding("Roughness", True, "source", None),
    "metallic":  ChannelBinding("Metallic", True, "source", None),
    "ao":        ChannelBinding("Ambient Occlusion", True, "source", None),
    "normal":    ChannelBinding("Normal", True, "source_1", "NORMAL_MAP"),
    "height":    ChannelBinding("Normal", True, "source", "BUMP_MAP"),
}


def map_to_channel_binding(map_key: str) -> ChannelBinding:
    if map_key not in _BINDINGS:
        raise ManifestError(f"unknown PBR map key: {map_key!r}")
    return _BINDINGS[map_key]


def validate_manifest(manifest: dict) -> None:
    layers = manifest.get("layers") or []
    if not layers:
        raise ManifestError("manifest has no layers")
    base = [l for l in layers if l.get("index") == 0]
    if not base or base[0].get("type") != "PBR":
        raise ManifestError("index 0 layer must be type PBR")
