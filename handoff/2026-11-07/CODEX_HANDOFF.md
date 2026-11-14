# RaceVideo: start here on zbook9

Prepared November 7, 2026 for Sunday's November 8 cyclocross field trial.
This is a self-contained handoff for a new Codex session running on the laptop.
Work in **`/home/sl/racevideo`**. Read this file, then `SUNDAY_TRIAL.md` and
`GPU_OCR.md`. A supporting bundle is under `handoff/2026-11-07/` on zbook9.

## Purpose and boundaries

The user wants to learn whether ordinary race footage can provide useful visual
bib evidence when RFID misses. Sunday is an observational test, not race scoring.
CrossMgr stays independent; do not create provisional reads or change race results.
The user is experienced with Python/processes and strongly values a responsive GUI,
measured performance, bounded memory and preservation of original evidence.

Capture can run continuously while the operator reviews saved segments. Keep local
recordings through LTE/agent disconnects. The Codex session runs locally on zbook9;
LTE carries agent requests, not a mandatory continuous video stream. Use local
files and the authenticated loopback MCP client for investigation/control.

## Freshly verified state — November 7

These are dated observations, not settings to reapply blindly:

- Host zbook9; i7-12850HX, approximately 32 GB RAM. GPU hardware previously verified
  as NVIDIA RTX A1000 Laptop GPU, 4096 MiB. Main app uses standard Python 3.14;
  neural environments use Python 3.12.
- `racevideo-mcp.service` active. Recorder fresh/running; 90 saved clips, no reported
  dropped clips or current error; analysis lag 0 ms at the check.
- Cumulative bad camera-packet count 21. That is a session-total counter, not proof
  of a current failure rate; inspect deltas and segment metadata when testing.
- ELP capture 3840×2160 at 30 fps, MJPEG. Stable device:
  `/dev/v4l/by-id/usb-4K_U3_Camera_4K_U3_Camera_2601230006-video-index0`.
  `/dev/video4` was its capture node and `/dev/video5` metadata; re-enumerate rather
  than assume node numbers. Advertised 4K/60 is not yet sustained-field validation.
- Manual exposure mode 1; absolute 10 = nominal 1 ms / 1/1000 s. Gain 190 is the reported
  maximum. Indoors this is quite dark. Set exposure for the actual outdoor scene.
- Motion settings: 0.5 s pre-roll, 2 s after LAST movement, 0.2 s brief quiet tolerance,
  analysis ceiling 15 fps, delta 18, changed fraction 0.025. Ring 256 MiB, event 512 MiB,
  max chunk 30 s. Storage limits split one motion event into linked chunks.
- **Workshop settings still active:** OCR ROI `[0.34,0.35,0.60,0.56]`, upright-only
  rotations `[0]`. Motion ROI approximately `[0.3714,0.0949,0.5214,0.7949]`.
  Redraw both for the field. Do not retain the top-wheel test region by accident.
- One connected/responsive GUI in Live. Recent sample p95 preview receipt-to-Tk
  submission age about 99 ms and callback delay 0.54 ms. This is a short observation,
  not sensor-to-monitor latency or sustained racing/load validation.
- Timezone America/Vancouver, NTP synchronized; observed local offset -07:00. Use
  actual timestamps/timezone data rather than imposing an assumed seasonal offset.
- 27 deployed app/MCP/prototype source files matched this preparation checkout by
  SHA-256. Most implementation files in the preparation repo are still untracked;
  do not assume Git HEAD contains the whole app or run cleanup/reset on that basis.

### NVIDIA monitoring mismatch: CUDA still passed

`nvidia-smi` currently fails with **Driver/library version mismatch**: loaded
kernel driver 595.91.07, NVML library 595.99. No driver changes/reboot were made.
Nevertheless, a CUDA matrix operation passed and an actual cached Paddle model
read the known 235 crop correctly (score approximately 0.988). Thus GPU inference
was verified working despite the broken NVML status tool. Recheck before the
trial. If a controlled reboot/driver reconciliation is needed, arrange it while
recording can be stopped; do not reboot during capture just for telemetry.

Machine-readable snapshot and source hashes are in `docs/handoff/2026-11-07/`.
Private token/service configuration was not copied into the handoff.

## Paths and entry points

| Item | Path on zbook9 |
|---|---|
| Source | `/home/sl/racevideo` |
| Production store | `/home/sl/.local/share/racevideo/racevideo.sqlite3` |
| GUI launcher | `/home/sl/.local/bin/racevideo` |
| Authenticated service client | `/home/sl/.local/bin/racevideo-tool` |
| MCP endpoint | `http://127.0.0.1:8766/mcp` |
| Private config | `~/.config/racevideo-mcp/` — use the client; do not print tokens |
| Service state | `~/.local/state/racevideo-mcp/` |
| App environment | `.venv` |
| Preferred GPU experiment environment | `.venv-ocr-paddle` |
| Alternative EasyOCR environment | `.venv-ocr-bench` |
| Training-only environment | `.venv-ocr-train` |
| Original cached neural models | `~/.paddlex/official_models/PP-OCRv5_mobile_det/` and `PP-OCRv5_mobile_rec/` |

The GUI launcher is review/Live with `--no-start`. Closing the GUI leaves recording
running; Stop recorder ends capture. MCP-started capture/OCR have independent
transient user units. Do not start a second recorder against the same camera/store.
Read-only inspection and notes transfer do not require restarting any component.

Useful read-only commands, from the source directory:

```sh
~/.local/bin/racevideo-tool call racevideo.status
~/.local/bin/racevideo-tool call app.instances
~/.local/bin/racevideo-tool call camera.controls
~/.local/bin/racevideo-tool call clips.dates
~/.local/bin/racevideo-tool call clips.list --arguments '{"limit":10,"day":"2026-11-08"}'
~/.local/bin/racevideo-tool call camera.sample --output-dir data/field-live-check
~/.local/bin/racevideo-tool call frames.get --arguments '{"clip_id":81,"ordinal":68}' --output-dir data/reference-81-frame 69
```

GUI frame numbers are one-based; SQL/MCP ordinals are zero-based. The last command
views GUI frame 69 of capture 81. Date filters are host-local; old workshop clips
may not appear in Today on Sunday. MCP `clips.list` without day spans all dates.
For mutations, inspect live operator state, use unique command IDs, and reconcile
an unknown outcome via `commands.get` rather than blindly replaying. Camera
leases/reservations protect operator edits; do not bypass them. See MCP_SERVICE.md.

## What is production versus experimental

Production: PyAV/FFmpeg camera capture, compressed shared ring, motion-triggered
segments, SQLite original JPEG frames/timestamps, asynchronous preview, Tk review,
manual camera controls, dates/stars/bib filtering and existing Tesseract OCR jobs.
Capture I/O is a child process; motion/assembly share the coordinator; SQLite
writing is a thread; preview decode and OCR are separate processes. Tk presentation
stays on the GUI thread; expensive image work is outside it. Source timestamps
survive delayed analysis. They are acquisition timestamps, not calibrated finish
crossings or exact sensor exposure times.

**GUI Read plates and MCP `ocr.start` still use Tesseract.** The stronger Paddle
best-view pipeline is a standalone read-only experiment, not wired to those actions.
It writes JSON, selected source crops and contact sheets only in its output folder;
those results do not populate the GUI's bib filters or SQLite OCR match tables.

Paddle prototype: detect every source frame in the OCR region, deduplicate raw/
contrast proposals, associate by geometry/motion, rank views by sharpness/contrast/
size/clipping and choose up to five. Recognize selected rectified crops in batches.
Variants from one source frame get at most one vote per candidate number. Keep
competing hypotheses; a high score is not calibrated certainty.

**One target means one visible encounter.** A 235 plate that leaves and returns is
a new target, even in the same video. Never group all appearances of one bib into
one OCR target. Each encounter has independent ID, timestamps, selected crops and
votes. Short detection misses can be bridged; closed tracks cannot reopen.
Tracking may fragment encounters or miss plates. Multiple printed labels on one
rider should support one eventual passing, not duplicate passings.

### Running the preferred experimental pipeline

**Always pass `--roi`.** The script's default is the old wheel ROI; it does NOT
read the GUI's saved area automatically. If using the area's saved setting, read
it from SQLite and pass its four normalized coordinates explicitly. Full-frame
`--roi 0 0 1 1` is available for an initial diagnostic, but may shrink small far
plates in the detector's resized input; a suitable field region needs testing.

Replace 123 with the actual saved clip ID, and choose the correct field ROI:

```sh
.venv-ocr-paddle/bin/python -m tools.best_frame_ocr \
  /home/sl/.local/share/racevideo/racevideo.sqlite3 \
  --clips 123 --roi 0 0 1 1 --cpu-cores 2 \
  --output data/sunday-trial/clip-123-fullframe-baseline-01
```

Use a fresh output directory per trial. Omit `--recognizer-model-dir` to retain
the original model. CPU affinity is limited to two LOGICAL CPUs. Run one heavy
analysis job at a time and keep recording/live responsiveness under observation.

Prototype limits: upright-only; no arbitrary/180-degree orientation trials in
this tool yet; expects exact three-digit outputs; clips processed independently;
no tracking carried across linked storage chunks; maximum 2,000 source frames per
clip. A chunk boundary alone is not another physical passing. Tesseract supports
0/180 choices, but its recognition was materially weaker. Unchecking upright-only
in the GUI does not add orientation support to the standalone Paddle tool.

## Physical tests and useful references

The 48-inch cat wheel carried 235 and 469. These were indoor workshop tests, not
race-speed validation. Medium/slow original test passes start at clips 46, 48, 50, 52;
linked 47, 49, 51, 53 were largely tails. Ignore 54/55 for those trials: operator moving.
Fast test 70–73: approx 0.9–1 rps / 12–14 km/h, briefly near 16 km/h; manual exposure 4 ms.
Clip 71 has 374 frames and visible smear. Global shutter would not remove that smear
without shortening exposure. Clip 73's later readable 235 was not a fast-pass success.

Later 1 ms/shop-light test 79–82: clip 81 has 78 frames and readable 235 at GUI frame 69.
The preferred unchanged Paddle model and selected-view prototype find four
encounters in order 469 → 235 → 469 → 235. Native best-view trial took about 5–6 s for
78 frames, 27 s for 374 frames on this laptop; decode/detection dominated. These are
candidate encounters, not lap counts. Baseline selected crops are in
`docs/evidence/zbook9/elp/gpu-ocr/best-frame-81.jpg`.

PaddleOCR 3.3.2 / paddlepaddle-gpu 3.2.2, PP-OCRv5 mobile detection/recognition,
Python 3.12 was the useful GPU baseline. EasyOCR was slower and less useful here.
Original neural weights are already cached locally. Before travelling, check that
models/imports still work rather than downloading/rebuilding during racing.

## Training, labels and future race integration

Training was actually tried: 3,232 synthetic images / 384 held-out; 235 and 469 were
excluded from training. Two epochs took 4.6 min, roughly 1.3 GB allocated GPU tensors.
Original recognizer 383/384, ordinary tuned 361/384. Restoring 302 BatchNorm statistic
tensors recovered 383/384 but still did not improve real-video encounters. **Keep
the original model.** Trained copies/checkpoints remain under data/training;
TRAINING.md records the experiment. Future training should use manually labelled
field examples, freeze normalization statistics for small batches and split by
whole recording/event. Existing wheel frames are development diagnostics, not a
pristine final accuracy set.

qllabels source was inspected on whiskey at
`/home/sl/work25/qlmux/qllabels/qllabels/qllabels.py`. Its bib path selects
`TGL_0-1451Eng.ttf` and stretches both dimensions to fill available space. A supplied
Mittelschrift file is also bundled but was not the selected font in that checkout.
Both fonts are copied here. Pure renderer masters for Frame-left/right and larger
Body bibs are under data/ql-label-masters. Body approximately 4×6 in uses 102×152 mm
media; Frame uses 62×100 mm. Prefer frameplates; body-bib placement/occlusion varies.
See LABEL_RENDERING.md for exact source/font hashes and deployment uncertainty.

Labels can be vertical, horizontal or upside down. 609/906-style alternatives may
both be valid entrants, so a start list alone cannot settle orientation. Preserve
alternatives and source views. CrossMgr predictions can guide review, not create
independent corroboration. Identity/name/bib mapping is event-scoped, not date/bib
alone. RFID EPC/TID are separate identifiers; OCR `tag_id` currently means bib text,
not RFID EPC. One video can contain many riders; each rider can appear in many
videos. See SQL_MATCHES.md and INTEGRATION.md. No CrossMgr/RaceDB ingestion or
provisional race-result writes are implemented by these experiments.

## Sunday setup and remaining work

The venue has 3–4 m of road width. Table position gives roughly 1.2 m to the nearest
frameplate, farthest roughly 4–5 m; near/middle/far focus and readable pixel size
must be tested outdoors. Lens zoom, focus and iris are physical/manual; remote
software cannot move them. A person on site adjusts them while the local session
inspects crops. Slower cyclocross helps, but fall light may force exposure tradeoffs.
Compare moving-plate 1/1000 and 1/500 s rather than let auto exposure silently lengthen
shutter. Brighter operator preview/gamma was discussed but is **not implemented**.
Do not assume displayed brightness implies better source exposure.

Use SUNDAY_TRIAL.md as the practical procedure. Record settings changes with source
samples and compare singles/groups, near/far positions and label angles. Watch
motion capture continuity as well as OCR; missed capture cannot be fixed by a
recognizer. Preserve originals, timestamps, useful failed examples and stars.
Frameplate release/re-entry is separate from OCR error or a new recording chunk.

Road finishes in March–June are faster and have different light: Sunday's result
will not validate that use case. Camera alternatives/lux claims are documented in
CAMERA_COMPARISON_2026-11-06.md. Do not substitute a camera solely for 0.05 versus 0.1 lux;
both Sony models use IMX678 and rating conditions were unspecified. An OG05B10 global
shutter is a different comparison, but costs some image detail depending on mode.

The last local unit run passed 56 tests. Fresh November 7 checks validated service,
recorder state, source hashes and actual cached-model GPU recognition. This handoff
does not claim a new sustained field/CPU/GPU stress test or deployed GPU integration.
