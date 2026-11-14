# GPU OCR diagnostics

**November 9 update:** the app now offers an isolated Paddle **Neural OCR**
worker alongside Tesseract; see [REVIEW.md](REVIEW.md). The full field sweep writes
the separate test database. AMD experimentation is suspended after reported
Plasma6/X instability; use the working NVIDIA path. Historical bench notes follow.

The zbook9 has an NVIDIA RTX A1000 Laptop GPU with 4 GiB total VRAM. These
experiments use separate Python 3.12 environments and do not alter the recorder,
GUI, existing Tesseract worker, original recordings or production OCR tables.
Images are processed locally. Upstream model weights download to local caches.

## Reproduce

Export from the application's environment, which has SQLite/image helpers:

```sh
.venv/bin/python -m tools.export_gpu_ocr_fixture "$STORE" data/gpu-ocr-fixture
.venv/bin/python -m tools.export_gpu_ocr_sequence "$STORE" data/gpu-ocr-sequence --clips 71 81 --stride 3
```

Run engines sequentially in their respective GPU environments (avoid competing
for VRAM). Keep the two neural frameworks out of the production environment:

```sh
.venv-ocr-bench/bin/python tools/gpu_ocr_benchmark.py --engine easyocr --fixture data/gpu-ocr-fixture --output data/easyocr-gpu-benchmark.json
.venv-ocr-paddle/bin/python tools/gpu_ocr_benchmark.py --engine paddleocr --fixture data/gpu-ocr-fixture --output data/paddleocr-gpu-benchmark.json
```

Replace fixture/output paths with the sequence paths for sampled-video analysis.
The tools refuse a silent CPU fallback, save raw text as well as exact three-digit
candidates, and test raw and percentile-normalized contrast independently. They
never receive a start-list or the expected fixture bibs as recognition input.
EasyOCR receives a digit character allowlist; PaddleOCR output is filtered to
exactly three digits only after recognition. They are different decoding policies.

Version baseline: EasyOCR 1.7.2, torch 2.7.1+cu126, torchvision 0.22.1+cu126;
PaddleOCR 3.3.2, paddlepaddle-gpu 3.2.2 CUDA 12.6. Use Python 3.12 independently
of the application's Python environment. Small PP-OCRv5 mobile detection/recognition
models are used for Paddle; document orientation/unwarping is disabled.

## Interpretation

The twelve-image fixture has seven selected plate crops, three search regions
and two background regions. It is a diagnostic set, not held-out race accuracy.
Four plate crops were selected from successful earlier Tesseract proposals, so
this is not an unbiased engine ranking. Some regions annotate just one clear
target; the two known fixture bibs are permitted in evaluation, not supplied to
recognition. No passing-level ground truth has been labelled for the sequences.

GPU allocated tensor memory is not total device/process VRAM. Startup includes
model loading and possibly downloading; it is reported separately from per-image
processing. No comparison should treat framework confidence values as calibrated
probabilities or comparable scores. Adjacent frames and reused crops are correlated.

## Font-specific follow-up

The operator identifies the labels as **DIN 1451 Engschrift, Regular**. The supplied `alte-din-1451-mittelschrift.regular.ttf` identifies as **Alte DIN
1451 Mittelschrift Regular**, a different family name from Engschrift. Preserve
that distinction: it is a useful synthetic-data baseline, not a verified exact
match. It has been copied unchanged to zbook9. File hash and rendered samples
are in `docs/evidence/zbook9/elp/gpu-ocr/`.

If general recognizers remain inadequate, use the actual font to render the
physical label layout and all three-digit strings including leading zeroes.
Vary perspective, arbitrary rotations, scale, illumination, sensor noise and
realistic directional blur. Include borders, fasteners and imperfect printing.
Keep original real-video captures for validation; split by recording/event so
adjacent frames do not leak across training and validation. Preserve competing
orientations/bibs rather than forcing 609/906 when both are valid entries.

A future GPU worker should keep models resident, use bounded crop batches and
backpressure, and retain source-frame timestamps and provenance. It must remain
independent of capture and GUI rendering. Benchmark false candidates and complete
passings before switching the default engine. No production switch is made by
these diagnostics.

## Measured results, 2026-11-05

Both engines ran GPU inference on the actual RTX A1000, sequentially.
PaddleOCR PP-OCRv5 mobile is the preferred next integration candidate.

| Sampled sequence, raw images | EasyOCR | PaddleOCR |
|---|---|---|
| Clip81, 26 sampled frames | 469 in2 frames;235 in1;715/785 wrong candidates | 469 in4;235 in4; no other three-digit outputs |
| Clip71, 125 sampled frames, faster blurred spin | No three-digit outputs | 469 in5;235 in6;739/735 wrong candidates |
| Mean time per search region | 135–137ms | 20–21ms |

These are frame appearances, **not distinct riders, revolutions or passings**.
Contrast normalization is not universally beneficial: it helped the selected
frame69 search region but reduced correct reads in the faster clip71 sequence.
Keep raw and normalized attempts separate and retain their lineage; do not
automatically prefer the more confident result.

For recognition-only selected crops, Paddle read all six clearer crops correctly
in both raw and normalized versions, including the difficult frame69/78 235. It
did not read the seventh, severely blurred 469 crop. EasyOCR read four of seven
raw crops correctly; it produced 335 for one235 and 0235 on the difficult crop.
Neither engine generated a three-digit number on the two background examples.
This tiny selected diagnostic cannot establish a general false-positive rate.

Paddle peak allocated tensor memory was approximately67–70MiB and EasyOCR535MiB;
these figures exclude CUDA context, reserved pools and other process/device
memory. Timings exclude initialization, video decode/export, frame transfer from
capture, tracking and application integration. A raw-plus-normalized attempt is
two calls. GPU headroom and a real-time pipeline still need sustained measurement.

At the time of this initial trial the app worker was Tesseract. The November 9
update adds an isolated Paddle worker behind the job interface, preserving source
timestamps, original evidence and old OCR runs. Model residency and sustained
bounded-queue throughput still need measurement. Validate at actual race speed
and add cross-frame association before interpreting repeated reads as passings.
Font-specific fine-tuning can follow if that remains necessary; it is not a
prerequisite for the substantial improvement already observed in these recordings.

## Experimental best-view selection

`tools/best_frame_ocr.py` now performs a read-only all-frame experiment:

```sh
.venv-ocr-paddle/bin/python -m tools.best_frame_ocr "$STORE" --clips 71 81 --output data/best-frame-ocr --cpu-cores 2
```

It decodes every original JPEG in the configured top-wheel ROI, runs the small
Paddle text detector on raw and normalized regions, and deduplicates overlapping
detections before association. Geometry, predicted motion, scale and a maximum
three-frame detection gap associate short tracks. Bib text is not used in
tracking, ranking or selecting crops. Each new visible wheel traversal can form
new tracks; tracks are not persistent rider identities.

Quality combines contrast-normalized sharpness, contrast, image area and an
edge-clipping penalty. It retains up to five high-quality views with preferred
spacing of two source frames, keeping a second distinct frame for short tracks.
This ranking is heuristic; it does not guarantee an optimal or fully unoccluded
crop. Singleton detections and stationary tracks are retained as metadata but do
not produce moving-plate recognition candidates in this prototype.

Only selected rectified crops enter recognition, batched in groups of up to eight.
Raw and normalized OCR attempts retain separate provenance but contribute at most
one vote per number per source frame. Exact three-digit readings at model score
0.6 or higher participate. A repeated candidate requires two distinct frames,
a strict vote lead over the next number and support in at least60% of the frames
with qualifying readings. This is a review heuristic, not a calibrated confidence
or race-result rule. Alternatives and unresolved ties are retained. Multiple
variants can support conflicting numbers in a single frame; these remain visible.

Output includes original clip/frame references, acquisition timestamps, source
quadrilaterals, quality measures, selected PNG crops, all OCR attempts, vote
summaries, stage timings and contact sheets. It reads the original SQLite store
with `mode=ro` and writes only to its output directory. The production GUI/MCP
Read plates action is not yet connected to this experimental path. Current tests
use the explicit upright-only fixture policy; arbitrary orientation remains a
separate requirement.

### Native best-view trial results

- Capture71: 374 source frames, 27.3s wall / 27.4s CPU, 88 recognition images (raw/normalized combined). Repeated candidate tracks: {'235': 5, '469': 2}.
- Capture81: 78 source frames, 5.4s wall / 5.4s CPU, 28 recognition images (raw/normalized combined). Repeated candidate tracks: {'469': 2, '235': 2}.

Capture81 produced two geometric traversals each for469 and235, with repeated
correct readings in each track. The selected crop sheet was visually inspected.
Capture71 retains fragmented/unread and ambiguous tracks, along with wrong
alternatives: the algorithm is not a complete passing counter. The GPU was used
with CPU affinity restricted to two logical CPUs. Decode and detector work
dominated; recognition on selected crops was under a second per clip.

Evidence: `docs/evidence/zbook9/elp/gpu-ocr/best-frame-results.json` and
`best-frame-81.jpg` / `best-frame-71.jpg`. Original initial and final diagnostic
runs remain in separate directories on zbook9; no production OCR rows were
replaced. Validation:51 unit tests passed, including two nearby moving tracks,
detection-gap splitting, preprocessing-detection deduplication, sharpness ranking,
short-track frame selection and non-duplicated/conflicting consensus votes.
These tests do not establish race-speed accuracy.

## Encounter boundary contract

The OCR target is **one uninterrupted visible plate encounter**, not one bib per
video. If235 traverses the region, leaves, then returns on another wheel
revolution, that return is a new target with independent selection, evidence,
votes and timestamps. Repeated bibs must remain multiple encounter records;
only a summary index may group them for bib/video lookup.

Tracks now explicitly close after their detection-gap timeout. Unmatched tracks
whose motion predicts their entire box beyond the configured region close as
`left_region`; a known exit can also be closed explicitly. Closed tracks cannot
be reopened, even within the normal short-gap tolerance. A brief missed detection
alone does not prove physical exit. Association remains heuristic and may still
fragment a pass; detection-only tracking cannot guarantee perfect boundaries.

Output includes a run-scoped unique `encounter_id` and closure reason, in addition
to clip/track/frame references. OCR numbers never participate in reconnecting
tracks. Regression tests cover the same235 returning after an absence, explicit
exit followed by near-immediate re-entry, and predicted full exit versus a brief
miss. All54 tests passed.

For eventual production integration, clip splitting alone must not imply a new
physical encounter: carry active tracking across adjacent linked recording chunks
where possible. This standalone diagnostic currently processes clips independently
and does not attempt that continuity. A fragmented/ambiguous track is not an
automatically confirmed lap or passing.

Native re-entry check on capture81: four separate repeated-candidate encounters
in order469,235,469,235, each with a distinct encounter ID. First235 spans GUI
frames13–17; the returning235 spans65–74. Evidence is
`docs/evidence/zbook9/elp/gpu-ocr/encounter-reentry-check.json`.

## qllabels source inspection supersedes the font assumption

See LABEL_RENDERING.md. The supplied Mittelschrift matches a bundled qllabels
font, but the inspected checkout currently selects TGL_0-1451Eng.ttf for bibs.
The renderer also stretches digits to fill the available area. Reuse its rendered
masters for synthetic training; font samples alone do not reproduce that output.
Actual deployed/historical label-generation provenance remains unverified.

First recognizer fine-tuning experiment completed on the A1000; see TRAINING.md.
It fits the GPU, but synthetic-only tuning did not improve the existing real-video
baseline. Keep the original Paddle model; future tuning should use labelled field
examples and frozen normalization statistics for small batches.

## Current execution policy — November 9, 2026

**AMD experimentation is suspended.** The operator reported Plasma6/X instability
after the Vulkan experiment and needed to recover the display session from the
other seat. The toy compute result below did not establish desktop stability or
OCR viability. Do not rerun it or change graphics drivers/device permissions as
part of field analysis. Use the working NVIDIA CUDA runtime on zbook9; the GUI
backend selector does not select the Vulkan environment.

The neural pipeline is now available through **Neural OCR → Read plates** in the
app. It runs in an isolated process with two physical CPU cores and uses the
original Paddle model. The full November 8 offline sweep runs separate isolated
workers on zbook9 and imports atomic clip reports into the local writable test
store. See [FIELD_OCR_RUN_2026-11-08.md](FIELD_OCR_RUN_2026-11-08.md).

## Historical AMD investigation — November 9, 2026

Measured complete-clip baseline, capture 508 (90 frames):

- Whiskey CPU, two distinct physical P-cores: 24.2 seconds.
- zbook9 RTX A1000 plus two logical CPU threads: 11.9 seconds.

These include model initialization, source reads, JPEG decoding and diagnostic
output. This is about a 2x end-to-end improvement for that clip across the two
hosts, not a GPU-only kernel benchmark. See `FIELD_ANALYSIS_2026-11-08.md` for the
larger sample and known recognition/association limitations.

Current whiskey observations:

- Radeon RX 6800 XT, 16 GB; second PCI device is Navi23/RX 6600-class, 8 GB.
- Mesa RADV/Vulkan enumerates the RX 6800 XT as a real discrete GPU. Its render
  device is readable/writable by this session. The second Radeon is not currently
  enumerated by Vulkan in this session; llvmpipe is a CPU software device.
- ROCm's kernel module is loaded, but rocminfo fails to open `/dev/kfd` because
  this user lacks render-group access. No membership/permission change was made.
- The normal ONNX Runtime reports CPU/Azure providers only. The working Paddle GPU
  environment on zbook9 uses CUDA; it cannot simply be selected for these Radeons.

Two inference paths were identified for investigation (now suspended):

1. **ncnn with Vulkan.** This uses the already working Mesa/Vulkan driver and is
   the first route worth testing on the RX 6800 XT without changing the graphics
   driver or installing a ROCm stack. The ncnn project supports Vulkan inference
   on AMD. Export/convert the actual detector and recognizer models, check supported
   operators and CPU fallback, and validate preprocessing and outputs against the
   existing fixtures. GPU enumeration alone does not prove model compatibility,
   correct results, or performance.
2. **ONNX Runtime with MIGraphX on ROCm.** This is an established AMD inference
   backend. It requires ONNX exports, a compatible ROCm/MIGraphX runtime, device
   access, and validation of these older consumer GPUs against the selected
   runtime. Prefer an isolated environment/container for a trial. The old ONNX
   Runtime ROCm provider is deprecated in favor of MIGraphX.

Start with one GPU and the exact same test clips. Record actual device/provider,
operator fallback, source-frame candidates, disagreements, CPU time, wall time,
and GPU memory. Keep CPU decoding/SQLite outside the neural inference backend.
Only after correctness and single-GPU timing pass should separate clip workers
be distributed across both cards. No AMD OCR acceleration has been measured yet.

Primary references:

- https://github.com/Tencent/ncnn/wiki/vulkan-notes
- https://github.com/Tencent/ncnn/blob/master/docs/how-to-use-and-FAQ/FAQ-ncnn-vulkan.md
- https://onnxruntime.ai/docs/execution-providers/MIGraphX-ExecutionProvider.html
- https://onnxruntime.ai/docs/execution-providers/ROCm-ExecutionProvider.html
- https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html

See `DATA_SAFETY.md` for the protected backup and writable test-store paths.

### Actual Vulkan compute check

An isolated `.venv-ocr-vulkan` environment using ncnn 1.0.20261020 successfully ran
a known FP32 3x3 convolution plus ReLU on device 0, the RX 6800 XT. The Vulkan
convolution/ReLU layers were selected and results matched the numpy reference
(maximum absolute error approximately 8.94e-8). The CPU path was checked too.
Device selection explicitly rejects CPU/software Vulkan devices.

This establishes a working compute/runtime path with the existing Mesa driver;
it does not establish OCR-model conversion, accuracy, throughput, or latency.
No ROCm permissions, drivers or system packages were changed. The toy model does
not open any recording database. Results are in
`docs/evidence/field-2026-11-08/amd-vulkan-smoke.json`.

```sh
.venv-ocr-vulkan/bin/python -m tools.amd_vulkan_smoke \
  --output data/ocr/amd-vulkan-smoke.json
```

Recreate this environment with the separate
`tools/requirements-vulkan-smoke.txt` requirements, not in the GUI/OCR environment.
The actual rider/text detector/recognizer exports and their operators still need
validation before an AMD OCR performance comparison is meaningful.
