# Label-renderer provenance

Inspected locally on whiskey, 2026-11-05:
`/home/sl/work25/qlmux/qllabels/qllabels/qllabels.py`.
Checkout HEAD: `146feb5c64736a96e23f2228fbfdca11490706e5`.
The source tree and printer configuration were not modified. No printer commands
or sockets were invoked. This records checkout behavior, not deployed-container
or historical printed-label provenance.

## Font correction

The supplied `alte-din-1451-mittelschrift.regular.ttf` is byte-identical to the
copy bundled in qllabels. Its internal family is Alte DIN 1451 Mittelschrift,
Regular; SHA256:
`3cdbdd35c7637ff4a15d22bdcb8b952f48afadd2e41edb5ab29d80eaad8d48fd`.

However, this checkout sets `DIN_ENG_FONT` to `fonts/TGL_0-1451Eng.ttf` (line 191).
`_load_font(size,'bib')` prefers that file when present (line 353), and
`_render_bib_block` calls that loader (line 749). The file exists and its internal
family is TGL 0-1451 Engschrift, Regular; SHA256:
`69463a90044fd69df7a775d517befb1d17228ac6fec5c2712fa19044af0875d5`.
A byte-identical reference copy is now `assets/fonts/TGL_0-1451Eng.ttf`.

The previous acceptance of the supplied Mittelschrift as verified production
font was based on the operator's description, not source inspection. Keep that
history distinct from this source finding. A different deployed version, fallback
PDF rasterization or historical label batch may still have used another font.
The exact generating deployment/version has not been checked. Use both fonts as
augmentation candidates if that provenance remains unresolved.

## Rendering matters beyond font choice

`_render_bib_block` starts with a large bib font, crops its text bounds, uses
Lanczos containment, then resizes width and height to fill the target digit area.
That can stretch the glyph proportions independently; rendering a normal TTF
sample alone is not equivalent to the printed label image.

The custom Frame path applies for 62/62x100 labels after successful PDF field
extraction. Default LABEL_DPI is 300; the target is 1109×696 pixels. Supported 600 dpi
mode uses 2218×1392. The frame renderer produces left/right side-text variants,
with a narrow vertical participant/footer strip (`results.wimsey.co`), a nominal
0.125-inch bib offset and zero outside margin. Side-text sizes/placement change
the area available to the digits. The standard CLI can fall back to rasterizing
the original PDF when extraction/custom-layout selection fails.

## Synthetic-data implication

Use the pure renderer functions (`LabelFields`, `_render_bib_block`,
`render_frame_label`) or verified saved pre-printer PNGs as the clean masters.
Keep the renderer source/version, font hash, dimensions, DPI and layout variant
with each generated example. Avoid calling the print CLI or monkeypatching live
printer configuration to generate data. Apply camera geometry/blur/noise/light
augmentation only after producing the clean label master.

Before calling the data an exact match to the wheel/race labels, compare those
masters with known printed examples or verify the deployment that produced them.
Independent real footage remains the evaluation set.

## Both frameplates and body bibs

The current CLI consumes a RaceDB PDF from standard input, using its positional
PDF name for routing/label type. `--save-png --no-print` saves preview PNGs and
suppresses forwarding; `--save-raster` optionally saves printer instructions.
There is no PDF-output switch in this CLI. PDF creation is upstream; the saved
PNG is the useful clean pre-printer training image.

Small Frame labels use 62x100 media and 1109×696 printable raster at 300 dpi. Large
Body bibs use 102x152 media (approximately 4×6 in) and 1660×1164 raster at 300 dpi. Both
use `_render_bib_block` and the same preferred Engschrift font/stretching. They
are not identical scaled layouts: side-strip widths, text placement and available
digit-area proportions differ. Frame labels have left/right variants; Body uses
its own layout. Include all of these in synthetic data.

`tools/render_training_labels.py` calls the actual checkout's pure rendering
functions and records source/font hashes, label type, dimensions and layout.
It does not invoke the printer CLI, raster conversion or network delivery.
Eighteen 300 dpi masters were generated for 000, 235, 469, 609, 906, 999 across Frame-left,
Frame-right and Body. They are in `data/ql-label-masters/`; the manifest and a
visually inspected contact sheet are retained under
`docs/evidence/zbook9/elp/gpu-ocr/ql-label-masters.*`.

## Recognition scope

Frameplates remain the primary target for the field trial. Body bibs are a
secondary opportunity: placement varies, they may be obscured or outside the
camera view, and fabric/mounting can introduce folds or curved surfaces. Their
larger size does not guarantee that they are visible or readable.

Retain target type as frameplate/body-bib/unknown where supported. Do not create
separate rider passings simply because both labels are visible together. Keep
both target tracks and their evidence, and correlate compatible co-visible
observations into a candidate rider passing in a separate step. Equal bib numbers
alone do not establish identity/correlation. If either label leaves and returns
on a later pass, that is a new encounter, even if its number repeats.
