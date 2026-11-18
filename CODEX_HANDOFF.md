# RaceVideo: start here on zbook9

## Local Sunday OCR and passage tracking cleanup

The Nov 15 batch has completed locally: 828 clips / 51,873 frames, no errors.
The writable database is `/raid4tb/sl/racevideo/tests/2026-11-15/racevideo.sqlite3`;
the protected source remains in `/raid4tb/sl/racevideo/imports/zbook9/2026-11-17/`.
CPU reports are in the test directory's `ocr-local-cpu/`. No AMD GPU runtime was used.

The former recall-v2 detector turned low-confidence wheel/body/background boxes
into thousands of separate passings. New `passage-v3` tracking retains raw keys
but uses sustained, confidence-filtered trajectories for the primary stops.
Weak-only intervals retain one unresolved stop; separate returns and simultaneous
riders remain independent. Raw/weak tracks are inspectable via Show grouped /
weak candidates. OCR on a secondary track cannot create a CM match by itself.

`python -m tools.rebuild_bike_tracks DATABASE REPORT_DIRECTORY --audit AUDIT_DIRECTORY
--event EVENT_ID` previews a rebuild from saved detections; `--apply` updates only
derived reports. It preserves existing analysis/track keys and stores preimages.
The local Sunday set was rebuilt with this tool: Elite unknown rows fell from
2,260 to 53, all 19 confirmed table entries remained, and review/history table
digests were unchanged. Audit/preimages: `tracking-v3-applied/` in the test folder.
This is not a measured rider-detection accuracy result; occlusion and weak-only
groups can still merge or fragment. No capture, OCR evidence, CMN or manual
review records were deleted. Source changes must be deployed on zbook9 before
using the new policy there; the laptop was not changed by this local rebuild.

## November 17 finish-zone candidate preference

Capture 1958 contains a walker and 60. The saved trigger frame places 60 inside
its recorded ROI and the walker outside it. Review now prefers subject tracks
observed inside that recorded zone; outside subjects remain reviewable and are
not treated as clear CM grouping suggestions. Motion-only candidates are labelled
moving subjects, not classified bikes. No pixel masks or semantic classification
are implied. See the 60/bystander section of REVIEW_CAPTURE_CHOICES_2026-11-15.md.

## November 17 shared-capture review positioning

Lap 8's 6 and 5 are both in 1954, at display frames 18 and 28. Equal-sized groups
of clear unknown subjects and expected riders now receive chronological one-to-one
review suggestions; one nearest-time subject must not be reused for both riders.
This is tentative display positioning, not an identity match. Ambiguous/unequal
counts or tied times do not force pairing. See the Lap 8 section of
[REVIEW_CAPTURE_CHOICES_2026-11-15.md](REVIEW_CAPTURE_CHOICES_2026-11-15.md).

## November 17 suggested-candidate display

A unique primary, non-uncertain unidentified candidate already offered by one CM
row is grouped under that yellow/unconfirmed row, instead of duplicated as `?`.
Use the sidebar Show grouped candidates toggle to inspect it. Ambiguous/shared
suggestions and actual extra candidates stay separate. Grouping records no
identity confirmation or race timing change.

## November 17 finish-review correction

See [REVIEW_CAPTURE_CHOICES_2026-11-15.md](REVIEW_CAPTURE_CHOICES_2026-11-15.md).
The final Elite riders 6, 5, 2 are in separate captures 1968, 1969, 1970. Indexed
motion candidates used to outrank the appropriate unindexed next clip. Ranking now
considers all capture types and nearby competing CM times without confirming
identity. Motion preview v2 predicts across brief silhouette loss; v1 audit
reports remain valid. Only two unreviewed clips in whiskey's writable clone were
reindexed. Do not regenerate reviewed track identifiers indiscriminately.
The protected 299 GiB import and test clone are on `/raid4tb/sl/racevideo/`, linked
under local `data/imports/zbook9/2026-11-17` and `data/field-tests/2026-11-15`.
`~/.local/bin/racevideo-sunday-review` opens the local archived review; no OCR batch
was run during import. This local launcher is independent of laptop launchers.

## November 14 visual-only review update

See [CROSSMGR_VIDEO_CORRECTIONS.md](CROSSMGR_VIDEO_CORRECTIONS.md). CrossMgr
positions now align across laps; visual-only evidence is on unnumbered rows.
Unassigned raw CM reads remain cached for audit but are omitted from review. Delete
ignores the selected candidate and advances; Ctrl+Z
restores it. Saved video is retained. Capture 764's Lap 4 run of question marks
is fragmented detector evidence (14 candidates), not 14 established riders.
No video-to-CrossMgr write-back is implemented. Existing MCP add-time operations
can handle native existing riders; workbook-only entrants need an explicit
registration-aware extension. Keep video identity confirmation separate from
approval of a concrete CrossMgr timing correction.

## Git-managed deployment (November 13)

The source is now committed on `develop`; see [GIT_WORKFLOW.md](GIT_WORKFLOW.md).
Whiskey is `/home/sl/work26/sprinttimer/racevideo`; zbook9 is `/home/sl/racevideo`.
The laptop receives a `git archive` of the committed revision, plus Git history
from a bundle so local changes can be committed there and fetched back to whiskey.
Do not use directory-wide rsync/delete, `git clean`, or hard resets for updates.
Keep `.venv*`, `data/`, recording databases, private `~/.config` credentials,
model caches and operator session state outside version control.

The November 13 archive includes the **MCP target** dropdown in the compact
Passings pane (below Current CrossMgr race). Choosing a named target saves
`selected_target` in `~/.config/racevideo/crossmgr.json`. Target/URL/token
environment overrides must be removed before switching through the GUI.
Each machine needs readable token and timezone-file paths; a path copied from
whiskey is not automatically valid on zbook9. Lapsrv is separately installed at
`~/lapsrv` and is not part of this repository. Its read-only `race.roster` server
addition is already installed in zbook9's separate CrossMgr MCP service checkout.

An operator GUI, physical-camera recorder and MCP service were running before
this deployment. They are left running; existing processes retain loaded code.
Close/reopen the GUI when convenient to load the target selector. A recorder or
MCP service restart should wait until capture is idle and the user intends it.
Check current process/recording state rather than relying on old notes below.
The deployment record under `~/.local/state/racevideo/deployments/` identifies
the archive revision, SHA-256 and source-only backup. No footage is in that backup.

## Single-screen passings (November 13)

Main window has a resizable compact bib grid below selected bib/time, video at
right. Current-race mode uses read-only bridge snapshots; archive mode provides
date/event/category selectors. Pop out retains the detailed review window. Both
share one controller, source positions, colors, review history and shortcuts.
See PASSINGS_REVIEW.md for live refresh/cache semantics and configuration.
Bridge discovery currently found no CrossMgr GUI; the live path is mocked in
unit/GUI tests, while archive rendering was checked on real zbook9 Elite data.
Existing operator GUI and recorder were not restarted. Reopen to load changes.

## Analysis scheduling policy

See [ANALYSIS_SCHEDULING.md](ANALYSIS_SCHEDULING.md): selected review first,
otherwise newest ordinary sightings first, with category-specific finishes in
five-place turns ordered by first category finish. Categories have independent
start offsets/lap counts; projected laps do not establish finish priority.
Event bike-index batches use the shared planner and recheck cached source facts
between queued jobs. No new large batch was started. Automatic live enqueue,
CrossMgr refresh and OCR/wheel prefetch remain coordinator work; do not claim
those queues are implemented or interrupt capture to add worker parallelism.

## November 11 timing review update

Race-relative operator clocks and experimental front-wheel overlays are now
integrated; see FINISH_LINE_TIMING.md and PASSINGS_REVIEW.md. The centreline is
fixed at normalized x=.5. Frame time is distinct from estimated crossing time;
missing measurements produce brackets. Additive `wheel_analyses` stores geometry
and source-frame timing evidence. Separate bounded CPU/CUDA workers do not send
CrossMgr reads or change human identity reviews. Optical/clock calibration and
production crossing accuracy remain open. Restart the app to load updated code;
preserve its `.ui.json` session and protected source database.

## November 9 post-race update

Short-number correction: [CONTEXTUAL_OCR.md](CONTEXTUAL_OCR.md). Current schema
is v11; one-, two- and three-digit bibs are accepted without padding. Capture
877 now produces 24 in eight frames through the normal app worker on both hosts.
The original completed all-day pass filtered for three digits, so its exposure
yield figures are conditional on that restriction. A fresh 1–3 digit full-day
pass (`5f06c57afcde6d0645ffb86d`) is running on zbook9 with automatic imports into
both databases. Preserve its frozen code/report directories and prior run history.
Event/lap-history ranking is planned, not yet used by the recognizer.

Next field test: [SUNDAY_2026-11-15.md](SUNDAY_2026-11-15.md). The app now exposes
advertised MJPEG capture modes, stopped-only mode selection and delivered-rate
diagnostics, plus per-clip mode/frame-gap metadata. Physical ELP 4K/60 remains
unverified: it was disconnected during development. Cyclocross passings are near
walking speed; 40–60 km/h road finishes remain a separate validation target.

The November 8 field trial is complete. Read
[FIELD_OCR_RUN_2026-11-08.md](FIELD_OCR_RUN_2026-11-08.md) and
[REVIEW.md](REVIEW.md) before the historical trial instructions below.
All 786 race captures / 90,679 original frames have been scanned, with results
in whiskey's separate writable test copy. `racevideo-field-review` opens it.
The same published reports have now also been imported into zbook9's normal
`~/.local/share/racevideo/racevideo.sqlite3`; select November 8 in the normal app.
All 786 imports passed source-identity checks and match whiskey's 733 observations
across 298 candidate-bearing clips. Earlier laptop OCR history was retained.
The original 175 GB snapshot remains protected. Updated code is deployed here;
Neural OCR and per-bib operator confirmation/correction/manual entries are available.
Raw OCR and review history remain separate (schema v11).

AMD experiments are suspended after reported Plasma6/X instability. Use the
working CUDA runtime on zbook9 or CPU-only inference. Batch analysis has finished
and its workers have been released. CrossMgr CMN files/context caching are the
next step; inspect the actual MCP contracts when the user supplies those files.
There have been no CrossMgr/RaceDB/Impinj race-data writes in this update.

## Historical pre-event handoff

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

## November 9: wheel-crossing timing and planned optical calibration

See FINISH_LINE_TIMING.md for the clip 877 centreline demonstration, annotated
evidence and the planned GPS/ESP32 optical beacon. A roughly 8 cm × 1.5 m far-side
white board would carry the GPS on top and an approximately 100 ms, once-per-second
UTC-aligned LED flash. Calibration can use earlier/later continuous-buffer frames;
retain observations before ring-buffer overwrite and transfer time using actual
frame timestamps. Preserve raw times alongside correction and uncertainty. Beacon
detection must not trigger motion capture. Hardware calibration and general
automatic wheel timing are not integrated. The isolated crossing calculation and
current local unit suite passed 94 tests on November 9.

## November 9: event passings review and completed short-bib rescan

The N/NN/NNN full-day batch `5f06c57afcde6d0645ffb86d` is now complete: 786/786
captures imported into both the local field-review database and zbook9's normal
database. Do not interpret earlier partial-progress notes as current status.

See PASSINGS_REVIEW.md for the **Event passings…** window, cached competition/
event/category/rider/passings schema, CrossMgr MCP configuration and colour/timing
semantics. All five November 8 PartyCross CMNs were imported through zbook9's
saved-race MCP endpoint into both stores. Comparisons refresh video evidence
without repeated MCP calls. Race files remain unchanged; no race-result writes
or live RFID-read corroboration are implemented. Optical calibration and the
front-wheel crossing prototype remain separate from the chart's time matching.

Final checks: 107 local unit tests passed, plus real Tk passings navigation,
competition selection and refresh-preservation checks on both hosts. zbook9's
existing full unit suite passed before the final registration-only entrant case;
all 13 final passings unit cases also passed there. Original 877 clips / 97,535
frames remain in the local review store and its foreign-key check passed. The
protected original database remains read-only. The local GUI was reopened under
`racevideo-event-passings-gui.service`, with the passings window open and the
operator's latest clip/frame restored (727 / ordinal 21 at reload). zbook9 code
and cached data are updated, but its existing desktop GUI was left running;
reopen that GUI to load the new button. No camera/recorder restart was performed.

## Passings review actions and legacy plate examples

Passings now offers Confirm bib, Save different bib, Ignore / bystander and Undo
last review beside an editable Visible bib and note. Missing OCR creates a manual
bib at the actual displayed source frame. Existing candidates use the existing
bib review/audit layer. Event-specific visual dispositions and their history are
committed atomically with bib decisions. Ignore suppresses only the reviewed
encounter in that event, not a whole clip or an expected CM passing. Competing
OCR strings are preserved as raw evidence. Undo refuses to overwrite an external
bib edit. See PASSINGS_REVIEW.md for reviewed-source/version scope and limitations.

Operator-provided references: clip 727 = 15; clip 747 = 5. Both show older small
frameplates, reportedly about 60% of current physical size. Reference images were
inspected; the back bib 15 and seatpost 5 are legible. Latest runs have no retained
observations. Raw clip 747 run 1487 nevertheless contains 5 candidates in seven
frames; clip 727 CPU run 1618 has one raw 15. Evaluate encounter geometry and
qualification as well as recognition, and verify the candidate boxes. No OCR
threshold or model was changed in this follow-up. Reference labels are in
`data/field-tests/2026-11-08/legacy-label-examples.json`; they do not automatically
confirm the app's passings. See FIELD_ANALYSIS_2026-11-08.md.

Validation: 114 local and 100 zbook9 unit tests passed, plus real Tk tests of
confirm, correction, no-OCR manual confirmation, event-specific ignore, undo,
navigation and competition selection on both hosts. Additive tables are
`race_visual_reviews` and `race_visual_review_history`; core schema remains 11.
Local UI reloaded for these controls; zbook9 files/tables are installed and its
already-open GUI still requires reopening. Recorder/camera processes unchanged.

## Default review position: first bike near image centre

New thumbnail/passings capture selections use `review_position.py` in the review
worker to select a frame near the first moving subject's horizontal centre.
Pillow-only, bounded first-four-second/small-frame analysis; no inference model
startup or GUI-thread decoding. A 128-clip in-memory cache avoids repeated scans;
selection changes cancel stale work. Exact source-evidence and MCP frame requests
still retain their requested ordinal. Passings selection now opens at the default
centred frame rather than automatically seeking OCR's representative ordinal or
the stored CM passing time. Explicit evidence jumps remain in Review bibs and
Sightings. It is an approximate display aid, not a finish-time calculation.

Real checks selected ordinal 18 for clips 727 and 747 and ordinal 19 for 877/711;
727/747 centred frames were visually inspected. These examples needed 6–7 reduced
decodes and approximately 0.1–0.3 s on whiskey; other scenes can differ. If motion
is inconclusive, fallback is the first retained OCR encounter or motion trigger.
Moving banners, occlusion, joined groups and clips beginning mid-passage remain
heuristic limitations. See PASSINGS_REVIEW.md for performance metrics and scope.
117 local unit tests passed plus Tk centring/exact-seek/cache, bib-review and
passings-action checks. New positioning unit/Tk checks and passings checks also
passed on zbook9. Code installed on both hosts. The local GUI had already been
closed normally when the update was ready, so it was left closed; the next
launch loads this behavior. Reopen any existing zbook9 desktop process to load it.

## zbook9 accidental-cleanup concern and safer deletion UI

The zbook9 app was stopped on request to prevent any pending cleanup. Comparison
against the protected original export found zero missing original clips and zero
missing/changed source-frame index/timestamp records: 877 captures / 97,535 frames
were intact. No pending writer or freed pages from bulk deletion. A stale bib
filter `32` was active in the last GUI snapshot. No database replacement was
needed or performed; all nine current operator reviews were preserved. Additional
consistent metadata backup and recovery-check JSON:
`/home/sl/racevideo/data/recovery/20261110-000402/`. See DATA_SAFETY.md for scope.

Main-toolbar cleanup removed. Use Maintenance → Delete recordings for selected
date…; `cleanup_panel.py` shows path/date/counts and requires exact typed
`DELETE YYYY-MM-DD COUNT` before permanent deletion is enabled. Cancel initially
focused; Enter in the entry does not delete. Existing star/active-OCR protections
and transactional rechecking remain. Typed-confirmation/cancel/deletion GUI tests
passed on both hosts; 117 local unit tests passed. Updated code installed on
zbook9 and its app reopened under `racevideo-recovery-review.service`, review-only,
with the bib filter cleared. Protected full original backup retained unchanged.

## Capture 724, bike-specific manual evidence and quiet tails

See CLIP_724_REVIEW.md: operator identifies 4 then 1, followed after a gap by
vertical/smudged 589 (OCR alternatives 599/665/539). Saved clip is only 3.132 s;
its 2 s tail explains the empty interval and partial following bike. Original
clip unchanged. Manual reviews now support normalized `bike_box` and
`passing_order` in provenance/audit without a schema migration. Mark bike controls
exist in Review bibs and passings; selecting saved manual evidence highlights
the marked bike and source frame. Multiple bikes can share a source frame but
have distinct boxes and order; duplicate order values are rejected. Unmarked
frame-only entries remain supported. Enter with an active mark adds manual
evidence rather than silently correcting an unrelated selected OCR candidate.

Future recorder starts default to `--quiet-close 1.0`, capped by configured
post-roll; zero restores the full post-roll. The Maintenance quiet-tail setting
persists for GUI starts. This is separate from the 0.2 s motion indication gap;
no currently saved videos are split. Metadata records effective quiet close.
Camera/recorder processes have not been started for this change.

Validation: 119 local / 105 zbook9 unit tests passed, including explicit quiet
splitting and distinct 4/1 markers in one source frame. Real Tk bike-mark tests
passed on both hosts (two boxes/numbers/order, saved highlight, wrong-frame
guard); existing bib and passings review GUI checks also passed. zbook9 GUI
reopened under `racevideo-bike-review.service`, retaining capture 724 and its
previous ordinal 45. No database migration or retrospective video edits.

## November 10: motion/storage choices and quick bike review

See MOTION_STORAGE_TRIAL.md for Sunday operation and limitations. Motion / storage
provides single finish zone, three zones, wide road, and entry/finish trigger with
road hold. Default remains single. Storage modes off/motion/bicycle/person+bicycle
create source-frame retention proposals only: no originals are deleted, exported,
or compacted, so current disk use is unchanged. Queued/running bike and retention
analysis now protect their source clips from date cleanup too.

Main review shows Confirm suggested bib for the selected passings context,
Previous/Next bike (Ctrl+Left/Right), and estimated passage count. Find bikes
runs only the bicycle detector on an older clip; neural OCR automatically reuses
its detections for the index. Manual bike boxes/orders remain independent evidence;
confirm does not infer which of several riders owns an ambiguous suggested bib.

Real zbook9 clip 724 detector analysis found three moving passages (representative
source display frames 20, 29, 95). Stationary flag jitter was rejected after the
first trial. Single-clip neural OCR 747 run 1621 completed with a bicycle retention
proposal of 28/88 frames, 50,861,846/159,372,438 bytes (~68% potential reduction).
Local motion-only proposal kept 25/88. All source frames and human reviews remain.
No full-day OCR batch was restarted. Detector indices 724/747 were copied locally
as metadata only after checking clip identity. Counts and trim proposals need
human review; no new physical-camera or sustained event-load validation yet.

Validation: 134 unit tests passed on each host; Tk smoke checks on both cover quick confirmation,
same-frame distinct bike navigation, editable zones and source-boundary review.
Code is installed on zbook9; its already running review GUI is left undisturbed.
Reopen the app to load the new controls. Default settings were not changed.

## November 11: bike-first passings and recall-first detector

See PASSINGS_REVIEW.md, Bike-first operator workflow. Added cursor-key selection
with scroll-to-selection, unidentified bike entries from completed detector
indices, one physical-passage assignment across competing OCR numbers, and
individual nearby bike candidates for missing expected CM passings. Ignore now
scopes associated source keys to the physical passage; grey Show ignored entries
have per-decision Restore. CrossMgr records and all original footage remain.
No automatic DNF. Unindexed capture coverage is explicit.

Index event bikes queues missing/older-policy detector indices for just the
selected event, using one detector process/model and the shared heavy-analysis
lock. Stop indexing cancels pending clips, finishing any active clip. New neural
OCR also builds the recall-v2 index; OCR region confidence remains 0.3 while
physical bike candidates accept 0.15 and short/stationary tracks. More fragments
and bystanders are expected. No whole-event rerun was started automatically.
Targeted zbook9 detector-only analysis 6 on clip 724 completed with 20 candidates;
these are not 20 real riders. Keep old indices and human annotations for comparison.

GUI review-index replies now carry selection generations, coalesce obsolete
requests and reject stale same-clip index/frame responses. This fixes a race
exposed by rapid key navigation and selecting another bike in the same capture.
144 unit tests and relevant Tk smoke checks passed on both hosts. Code is installed
on both; reopen RaceVideo to load it. Protected original backups remain intact.

## November 11: compact passings layout and keyboard review

Event passings now hides main browser_area (Date and everything below) until the
panel closes; video gains the freed height. Space confirms, + / keypad + opens a
bib entry followed by digits and Enter, minus / keypad minus ignores. Keyboard
handlers run before widget/class bindings on the main and passings widgets, but
leave text entry alone. Closing passings restores normal playback/zoom shortcuts.
Adding uses an anchored event/clip/source frame and independent audited added:
subjects, so adding several bibs at one frame cannot overwrite the selected rider.
Escape cancels the entry; changed-frame and invalid-number guards retain the draft.
Existing ignore/restore and manual bike/order annotations remain available.
145 unit tests passed on both hosts; new passings_shortcuts_gui_smoke.py verifies
actual key events, button focus, multiple additions, text protection, hiding and
restoring the browser and larger video. Existing passings/manual-bike GUI checks
also passed locally. Installed on zbook9; its active GUI was left running to preserve
operator position, so reopen the app for the new controls. No field footage or
operator evidence was changed during this implementation.

## November 11: resume review, multi-step undo/redo and focus/panning

See PASSINGS_REVIEW.md, Resume/undo/focus. New ui_session.py atomically stores a
host-local <database>.ui.json sidecar. Periodic writes run in Reader; close saves a
final snapshot. Startup restores date/filter, main/passings geometry, replay frame
and view, event/category/selected passing/scroll, without forcing Live afterwards.
Passings close retains its last configuration; obsolete Tk timers are cancelled.

Added race_visual_history_links (additive metadata only), history_state and audited
transactional redo. Undo/redo restores exact event/bib snapshots and row IDs,
appends audit entries and checks concurrent changes/duplicate order. New edits
invalidate redo. Ctrl+Z/R and rider arrow navigation use the shared shortcut tag
in either main/passings, preserving text-entry behavior. Plus now forces focus to
the entry after its explicit user invocation. Panning pauses playback, rejects
obsolete frame renders and capture changes clear stale OCR/zone drawing modes.

148 unit tests passed locally and on zbook9. review_session_gui_smoke.py verifies
restart geometry/date/filter/event/category/selection/frame/zoom, both-window
navigation/confirm/undo/redo, real entry focus and pointer pan. Other review and
motion-options GUI checks passed. Installed code requires reopening the existing
GUI once; old already-running code cannot save a full session until this version
is loaded. No field reviews/footage were changed by tests; original backups remain.

## November 11: large bib cue and column-major review advance

Main video now overlays the selected passing bib in 48 pt bold green/yellow/red
with a black backing, only for its loaded capture. Cached cue updates avoid
rebuilding text every video frame; it remains above video and review outlines.
Space/minus shortcuts request auto-advance, performed only after a successful
review commit. A user selection during the pending save cancels it. Buttons and
other actions retain their old behavior. Up/Down wrap through nonempty columns,
stopping at the first/last entries. Final visual ignore holds the existing video
without selecting another rider; Up resumes at the last remaining row.
148 unit tests plus GUI checks passed. New passings_advance_gui_smoke.py verifies
all column boundaries, success/failure advance behavior, end holds and cue colors.
Existing shortcut and session tests were adapted to post-confirm advance.
Installed locally and on zbook9; reopen the active GUI to load this version.

## November 11: capture 764 wrong-rider seek and bike navigation

User selected PartyCross Elite Mac Napier 4 after Drew Nelson 499, but capture 764
(143 frames) stayed on its first rider. No bike analysis existed; OCR had only
499/49/667/67 on one encounter, so previous/next had one evidence group.
Targeted zbook9 bike analysis 7 completed; report copied metadata-only into local
analysis 3 after exact source identity/dimension/count/timestamp checks. No human
reviews or frames changed. No whole-event scan started.

bike_index.navigation now provides primary stops separately from all candidates:
sustained tracks per occupied interval, retaining independently sustained overlaps.
Raw weak fragments remain in passings for review. Prefer primary track geometry
when attaching OCR, so 499 belongs to its physical first bike. Missing expected
passings rank sustained unassigned bikes ahead of weak fragments/already-matched
riders. This capture has two primary stops, display frames 20 and 75. Frame 75
visually shows 4 and opens when selecting Napier; it is still unconfirmed.

GUI aligns active bike to the selected evidence and source interval, uses current
scrub position, and disables Previous/Next at real boundaries. Time-only unindexed
candidates now seek target_ns instead of automatic first-subject placement. Index
reader messages include that target alongside the existing selection generation.
149 unit tests and relevant GUI checks passed. Actual local capture 764 was
exercised in Tk without changing review evidence: select 499/frame18, Next75,
Previous20, select4/frame75. See data/validation/clip764_gui_check.py and artifacts.
Local display timezone is still one hour behind zbook9; source nanoseconds match.
Installed on both hosts; reopen the current GUI to load the new behavior.

## November 11: generic no-visual image search, not per-capture fixes

Added motion_position.py: automatic bounded CPU/Pillow moving-subject positioning
for CM candidates without an explicit indexed frame. Panel passes target time,
expected bib and evidence keys already matched elsewhere; Reader locates a centered
candidate instead of timestamp-only seeking. Caches source=motion metadata in
bike_analyses and supplies Previous/Next and unidentified passings. Nothing is
human-confirmed automatically; no GPU/model/OCR is needed for the preview.

Preview uses median first/middle/last background, sparse tracking, refinement and
cached masks; <=96 reduced decodes, full short clips or +/-5s on >12s clips labelled
partial. Cancellation is generation-aware; static/no-subject findings are cached
and reported explicitly. Optional positioning failures do not kill Reader.
completed_analysis prefers a usable neural result over a newer preview ID, avoiding
an async completion race. Index event bikes still queues motion-only clips for
neural analysis. Active preview source clips receive normal cleanup protection.

156 unit tests and relevant GUI checks passed on both hosts. New
no_visual_subject_gui_smoke.py covers completely unindexed/no-OCR clips where the
predicted frame is empty, both separate riders, and working cached Previous/Next.
Actual local Elite validation created only motion metadata for 706 (frame63), 707
(frame62), 710 (frame16); screenshots show visible riders. First scans 0.7–1.1s here.
Motion-only scanning 764 separately reproduced frames20/75. No field human reviews
or source footage changed, no whole-day scan. See data/validation/generic-no-visual-
positions.json and .jpg. Installed on zbook9; reopen the current GUI to load it.

## November 11: Elite final-lap 4 saved confirmation was suppressed

Actual zbook9: event1/source12, CM passing1207 (lap9 bib4), capture866/89frames.
Bib review33 is manual 4 at ordinal17 (display18), event review60 confirms it.
Older event reviews56/57 ignore bike:11:motion:1/2. collect inferred association
of review33 with motion:1; compare_event's unconditional physical-ignore filter
then hid the later manual evidence, producing missing/false and a start fallback.

visual_evidence now includes reviewed_ns from bib_reviews.updated_ns. Source-key
suppression uses the most recent event decision; later human evidence overrides
older inferred physical ignores. Newer explicit ignores still apply and can be
re-confirmed. Saved human source ordinal remains the capture target. No database
repair or decision rewrite was needed: fresh compare_event now returns confirmed,
matched, capture866 ordinal17. Old ignores/audit remain intact.

159 unit tests passed on both hosts. Actual zbook9 headless GUI check with UI-state
writes disabled verified final-lap row confirmed, frame18/89, green overlay and
Confirm disabled. Script: data/validation/elite-confirmed-frame-check.py. It reads
field evidence without changing reviews or operator session files. Regression
checks cover both ignore/confirm orderings, Review bibs manual evidence and saved
source frame precedence. Installed on both hosts; reopen the active GUI to load
this fix. User does not need to confirm the rider again.

## November 11: generic automatic reconciliation and prevention audit

User asked for root-cause prevention and automatic handling, not per-record repair.
Extracted the decision precedence into review_resolution.py, called on each
compare_event. Added stable reconciliation diagnostics and UI status count.
bike_evidence.collect now recovers accepted manual rows that heuristic association
filtering might drop, preserves saved manual boxes, and detaches ambiguous inferred
associations when they collapse independently confirmed different bibs. Confirmed
human matches are assigned before OCR alternatives; confirmed orphan evidence is
never silently folded into another rider's OCR alternatives. Positioning receives
protected visible manual keys so old candidate ignores cannot exclude them there.
Newer explicit ignores and undo/redo continue to work; no operator history rewrite.

Added read-only tools/audit_review_consistency.py to inspect all cached events and
check every resolved accepted manual observation is represented in the chart.
Actual zbook9 audit: 6 events, 19 visible manual observations, 1 auto reconciliation,
0 unrepresented manual observations. Output: data/validation/review-consistency-
zbook9.json. Actual lap9/4 GUI check again showed confirmed green frame18/89.
168 unit tests passed on each host plus relevant review/session/no-visual GUI checks.
Installed both hosts. Reopen the existing GUI for the new diagnostics/guards.

## November 11: compact nearby same-bib possibilities after confirmation

User pointed to final Elite rows4/Napier,1/Wakefield confirmed,1/Wakefield CM-no-
visual,Lawson. Actual second Wakefield is raw CM passing1218, 28.598909s after
confirmed passing1217, no assigned lap/no video. Current presentation omits
unassigned CM reads while retaining them in the source cache. Same-subject
unconfirmed OCR can group under a confirmed passing; distinct physical tracks are retained.

Model retains grouped_cells and parent.grouped_candidates; UI badge and Show grouped
expose the originals. Checkbox persists; hiding a selected child/old restored child
returns to parent. Confirm undo automatically removes grouping. No source CM read,
video or operator review is edited/deleted; no duplicate is automatically adjudged
invalid. Fresh actual zbook9 comparison now begins Napier/Wakefield/Lawson, with
Wakefield +1 grouped. 173 unit tests on both hosts and grouping/review GUI checks
passed; six-event manual consistency audit still has zero unrepresented accepted
observations. Installed both hosts, reopen current GUI to load it.
