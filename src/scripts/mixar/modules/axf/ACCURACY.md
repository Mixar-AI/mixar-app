<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# X-Rite AxF in Mixar: accuracy and your scan files

This note ships with the app so that anyone can check what the AxF importer claims.
The engineering reference is `docs/modules/axf.md` in the Mixar source.

## What "lossless" means here

Mixar renders an AxF material with the model stored in the file, unchanged. Three
things are measured, separately:

| Claim | How it is checked | Result |
|---|---|---|
| The file survives | AxF → `.blend` → File ▸ Export ▸ X-Rite AxF | byte-identical (SHA-256) |
| Cycles renders the file's model | per pixel, against an independent float64 implementation of the model, Cycles CPU and GPU (Metal), at 24 light/view geometries per material, plus a white sky | median relative error ≈ 1e-6; p99 ≤ 4.4e-5 at the instrument's geometries |
| That implementation is X-Rite's model | per pixel, against the preview image X-Rite's own decoder rendered into every file, with no fitted parameter | float precision (median ≈ 1e-7) on every flake-free car paint; 30 of 32 SVBRDF files to float precision, the other two up to two previewer quirks |

How close the file's model is to the physical paint is a property of the file, not of
the renderer. It is reported next.

## The model against the device

Pantora 2026 car paints store the X-Rite MA-T12 readings they were fitted from: 12
geometries per scan, 6 mm aperture, 31 bands, 400–700 nm. The pickup sits at 15° or
45° and the emitter moves; the stored value is `f · cos θ(emitter)`.

| Pickup | Aspecular angles (emitter direction) |
|---|---|
| 45° | −15, 15, 25, 45, 75, 110 |
| 15° | −45, −30, −15, 15, 45, 80 |

Colour: CIE Lab, D65, 10° observer; ΔE00. Flakes enter as their average.

| Paint | model vs device ΔE00 mean / max | scan 1 vs scan 2 |
|---|---|---|
| silver (metallic) | 2.66 / 8.93 | 0.21 |
| grey (metallic) | 1.59 / 3.73 | 0.23 |
| beige | 1.64 / 4.50 | 0.49 |
| green | 1.34 / 2.97 | one scan |
| blue (metallic), two files | 0.96 / 2.30 | 0.33 |
| red | 0.86 / 2.42 | 0.54 |
| chrome garnish | 0.72 / 2.72 | one scan |
| black ×2, grill black, piano black, white | 0.20–0.59 / 0.35–2.33 | 0.35 (white) |

On metallic paints the model is 16–40 % darker than the device where the half-angle is
22.5° and 16–62 % brighter at the flop (aspecular 110°). X-Rite's own decoder agrees
with the model there, so the gap is in the file. Part of it comes from the encoder:
these files keep one active Cook-Torrance lobe of the three CarPaint2 allows.

## Choices the files do not state

- Colour: spectral data is shown as its colour under D65 in linear Rec.709, so a white
  reflector under a white light is exactly white. The equal-energy (`sRGB,E`) alternative
  differs by 0.2–1.1 ΔE00 on average and at most 1.7. 2016 files store `sRGB,E` RGB and
  are used as stored.
- Colour table: X-Rite's 2016 decoder reads texel `i` at `i/N`, its 2026 decoder at
  `(i + 0.5)/N`; each matches only its own files' previews. Against the device the
  conventions differ by less than 0.1 ΔE00.

## What the importer refuses

Anything the renderer cannot reproduce exactly is refused with a message that names it:
BTF materials, anisotropic Cook-Torrance lobes, Fresnel and Cook-Torrance variants other
than the ones checked, clear coats with solid-angle compression or resources other than
an index of refraction and a normal map, flake parameterisations other than `ThetaFI`
and flake tables with virtual thetaI slices, and SVBRDF variants beyond Lambert plus one
Ward or GGX lobe.

## Your scan file

- **In the `.blend`.** With Keep Original File on (the default) the importer packs the
  original `.axf` into the `.blend`, so it can be exported back byte for byte; it then
  travels with every copy of that `.blend`. With it off, the material renders the same
  and cannot be exported to `.axf`. File ▸ Clean Up ▸ Remove Embedded AxF Originals
  deletes the packed originals from a file you already have (save afterwards). Either
  way the material's render data stays in the file: the colour table, flake and map
  images the renderer reads are the scan's measurements in another form.
- **What Mixar features send off your machine.** No feature uploads a `.blend` or the
  packed `.axf`. Generation jobs upload a glTF/FBX of the selected meshes, which carries
  neither the scan nor the AxF render data. Publish to Web uploads a GLB without the AxF
  data or the material's AxF details (model, source file name and hash). Asset Search
  never offers or sends the packed scan as a reference image. Crash reports are text.
  Exports go to folders on your machine.
- **The agent.** Mixie works by running scripts in your open scene. A script can read
  anything in the scene, including packed files, and what it prints goes to the Mixar
  service and the AI model provider. Mixie has no reason or instruction to read a scan,
  but nothing technically prevents it. If a scan must never leave the machine, keep it
  out of files you use with the agent: import with Keep Original File off, or remove the
  originals first.

## Rendering

Cycles. Checked against the reference on CPU (macOS) and Apple Metal. Windows CPU
renders match macOS CPU to float precision (direct light, per pixel); on textured
materials the few pixels that differ are as many as moving the object by 1e-7 m on one
platform changes (texel lookups at texel edges). NVIDIA
CUDA/OptiX builds compile the same kernel code but have not been checked against the
reference yet. OSL shows a neutral grey stand-in. EEVEE renders a car paint imported
by this version close to Cycles (median ΔE76 under 1 on a lit sphere, area lights
approximated by their centre direction); SVBRDF and older car paint imports show a
preview, not the measured material.
