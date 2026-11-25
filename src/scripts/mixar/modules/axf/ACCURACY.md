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

The importer makes this comparison itself on every car paint that carries readings
and shows it in Material Properties ▸ AxF. One convention for every figure here and in
the app:

- both sides as reflectance factor `R = π f` (the stored value divided by `cos θ(emitter)`);
- the device side is the mean of the file's scans at each geometry;
- the model side is the file's model at the reading's directions, flakes as their
  patch average (what a 6 mm aperture averages);
- colour: CIE 1931 2° observer (the observer the files' own colour specifications
  name), D65, CIELAB against the perfect white, CIEDE2000 (kL = kC = kH = 1).

Earlier versions of this note used the 10° observer, per-scan figures and other
sources; their numbers differ from these by up to about 0.3.

| Paint | scans | model vs device ΔE00 mean / max | scan 1 vs 2, worst geometry |
|---|---|---|---|
| silver (metallic) | 2 | 2.59 / 8.77 | 0.53 |
| beige | 2 | 1.66 / 4.24 | 0.93 |
| grey (metallic) | 2 | 1.56 / 3.68 | 0.50 |
| green | 1 | 1.30 / 2.95 | — |
| blue (metallic), scans_blr | 2 | 0.93 / 2.20 | 0.72 |
| blue (metallic), exterior | 1 | 0.94 / 2.37 | — |
| red | 2 | 0.84 / 1.81 | 1.65 |
| chrome garnish | 1 | 0.71 / 2.69 | — |
| black | 3 | 0.48 / 1.49 | 1.51 |
| white | 2 | 0.43 / 1.12 | 1.25 |
| grill black | 1 | 0.39 / 1.46 | — |
| black2 | 1 | 0.34 / 1.02 | — |
| piano black | 1 | 0.22 / 0.36 | — |

On metallic paints the model is 18–39 % darker than the device where the half-angle is
22.5° (`r45as45`, `r15as45`, `r15as-45`) and up to 65 % brighter at the flop. X-Rite's
own decoder agrees with the model there, so the gap is in the file. It is a brightness
error, not a colour one: correcting only the brightness at each geometry would take the
mean from about 1.0 to 0.15 ΔE00, below the scans' repeatability; on blue and red the
paint loses chroma because it is too dark there, not because its hue is wrong. Part of it
comes from the encoder: these files keep one active Cook-Torrance lobe of the three
CarPaint2 allows. Flakes are not the cause (on or off, the figures move by at most about
0.4), and neither is the instrument's angular aperture (modelling it makes the fit worse).

## Fit Lobes to Device (optional)

The import option **Fit Lobes to Device** refits two Cook-Torrance lobes (coefficient
and width; F0, the colour table, diffuse, clear coat and flakes stay as stored) to the
readings in the file, and renders the refit only when it predicts angles it has not
seen better than the file's lobes. Two checks, both on data the fit did not see:

- each geometry in turn is left out; the held-out mean and maximum must both improve on
  the file's lobes by at least 0.1 ΔE00;
- each group of geometries at a similar half-angle (within 3°) is left out whole; the
  held-out mean must be no worse than the file's. This is the check that matters for a
  render, which shows every angle, not only the instrument's twelve.

The lobes must also reflect no more light than they receive. Off (the default), the file
renders as stored. Either way the packed original is unchanged and export writes it byte
for byte.

| Paint | file's lobes mean | geometry left out | angle group left out | used |
|---|---|---|---|---|
| silver | 2.59 | 1.51 | 5.47 | no |
| beige | 1.66 | 1.39 | 5.44 | no |
| grey | 1.56 | 1.20 | 4.04 | no |
| green | 1.30 | 0.95 | 2.85 | no |
| blue, scans_blr / exterior | 0.93 / 0.94 | 0.81 / 0.68 | 2.14 / 3.92 | no |
| red | 0.84 | 0.57 | 1.01 | no |
| white, black, black2, grill black, chrome garnish | 0.34–0.71 | no better | — | no |

On these twelve Pantora 2026 paints the refit matches the instrument's angles better but
predicts the angles between them worse than the file, so every one keeps the file's
lobes: twelve readings cannot say what the paint does between them. A file whose
readings follow a two-lobe CarPaint2 passes both checks. Better files (all three lobes
active) or readings at more angles are what would close the gap.

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

## Artist controls

The AxF Car Paint node has five inputs for deliberate look changes. Their defaults
render the measurement exactly: Tint white, **Flake Strength 1** (the flakes as
measured), Orange Peel 1, Coat Reflection 1, Coat Roughness 0. All validation figures
use these defaults.

## Rendering

Cycles. Checked against the reference on CPU (macOS) and Apple Metal. Windows CPU
renders match macOS CPU to float precision (direct light, per pixel); on textured
materials the few pixels that differ are as many as moving the object by 1e-7 m on one
platform changes (texel lookups at texel edges). NVIDIA CUDA renders match Windows CPU
renders (checked on a GTX 1650 at all 96 instrument geometries: 99 % of pixels within
1.4e-5 without flakes; with flakes, the pixels that differ sit on flake texel edges and
the averaged colour agrees to 0.02 %). OptiX has not been checked yet. OSL shows a neutral grey stand-in. EEVEE renders a car paint imported
by this version close to Cycles: within ΔE00 0.1 under a sun on most paints, and a
median of 0.1–0.5 ΔE00 on a sphere lit by a large area light (area lights are integrated
over their surface). Car paints imported by an earlier version
show a preview until Material Properties ▸ AxF ▸ Add EEVEE Fit fits them from the
material's own data (no re-import, no original file needed). SVBRDF materials show a
preview, not the measured material.
