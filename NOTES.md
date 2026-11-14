# Development notes and observations

## 2026-11-05: medium/slow wheel runs and lossless OCR hypotheses

Capture worked; new segments had no automatic OCR because the current scanner is
on request. Four real wheel runs map to 46–47, 48–49, 50–51, 52–53; 54–55 are the
user moving back and excluded. At nominal 4ms/gain190, qualified raw OCR included
235 and 469 in all four first chunks. A max-score and winner-only summarization
could hide correct 469 behind rotated alternatives. V3 preserves qualified number
hypotheses per track/frame, retaining ambiguity for review; competing/wrong values
still exist. Cached raw reads were reanalysed into provenance-linked new runs,
not silently rewritten or presented as new recognition. Event chunk cap increased
to bounded512MiB, references starred, explicit thumbnail scan states added with
incremental metadata updates. Active operator view preserved; new labels load on
next launch. See [ELP_CAMERA.md](ELP_CAMERA.md) and its structured evidence. 43 unit
checks and actual temporary-store GUI workflows pass on target laptop.


## 2026-11-05: ELP iris/focus, first 4K reads and packet recovery

Opening the manual aperture restored light; physical focus made 235/469 readable.
Starred zbook9 clip16 provides the original 4K reference. Full-frame v1 OCR read
235 in 8/8 samples and 469 in 3/8 (~15.5s). ROI v1 failed; making the detector scale
independent of ROI dimensions restored both reads (~8s), engine version v2.
One bad camera packet had stopped the recorder; capture now counts/skips isolated
structurally damaged packets and fails sustained corruption, recording per-clip
loss metadata. 42 unit tests and injected-corruption recorder integration pass.
See [ELP_CAMERA.md](ELP_CAMERA.md). Moving-wheel/fixed-exposure testing remains.


## 2026-11-04: zbook9 installed and validated

Installed a separate source checkout/venv, OCR libraries and English data, user
MCP service, and review-first application/desktop launchers on zbook9. Recordings
live outside the checkout. Ubuntu 26.04.1/Python 3.14.4 standard build passed 39
unit checks and real Tk/MCP/motion/stress checks. Decoder termination exposed a
multiprocessing Event condition-lock shutdown hang; capture/preview worker
signals now use monotonic shared flags and the laptop failure test passes.
Synthetic full-HD preview measured 63/91ms median/p95 with 4.8s analysis lag;
physical external-camera/4K/race-speed testing is pending delivery. No built-in
camera recording was performed. See [ZBOOK9.md](ZBOOK9.md) for layout/evidence and
camera-arrival/Sunday checks. Credentials are private on the target, not stored
in these notes or copied from the development host.


## 2026-11-04: event-scoped identity and future RFID corroboration

User requirement: several events can share one date; a participant can have a
separate bib for each entry (e.g. Single-speed and Intermediate). Future names
and EPC assignments belong to event-entry identity/history, not a day/bib key.
Keep current OCR tag_id values distinct from EPCs. Correlate independent physical
RFID evidence by resolved entry/time window; distinguish missing evidence from
an unavailable/delayed feed. Preserve lineage to prevent an OCR provisional read
returning through CrossMgr from corroborating itself. Planning only; no live
upstream connections or result writes added. See [INTEGRATION.md](INTEGRATION.md).


## 2026-11-04: many-to-many bib/video lookup

Schema v8 adds `video_tag_matches` (unique tag_id/video_set_id), per-pair encounter
summaries and an indexed reverse lookup. Each group segment can match several
riders and each rider can match several segments. SQLite triggers maintain the
latest completed run's match set, preserve prior matches during running/failed
reruns, and publish replacements atomically. Migration backfills existing OCR
without altering videos. GUI/MCP filtering uses the table; shared clips appear
once. `clips.info` exposes the summaries. See [SQL_MATCHES.md](SQL_MATCHES.md).


## 2026-11-04: daily review, original-pixel zoom and evidence retention

Implemented Today/date/All dates browsing, ANY-bib filtering from the latest
completed OCR run, candidate-sightings source navigation with per-bib intervals,
persistent stars and previewed date cleanup preserving stars/active OCR/new clips.
Schema v7 adds annotations and a durable clip-ID allocator so deleted IDs cannot
refer to newly captured footage. Older running recorders must restart before
cleanup. Zoom crops original pixels off-thread; captions describe displayed frames.
MCP gains dated/starred/bib lists, date inventory, stars and sightings. Cleanup
validation uses temporary stores; original development recordings are retained.
See [REVIEW.md](REVIEW.md). Earlier dated entries below are historical.


## 2026-11-04: bounded capture/analysis and latest-only preview

Capture now runs in a spawned process, feeding a byte-bounded shared compressed
ring. Motion analysis and segment assembly run in the coordinator; queued SQLite
writing stays on its writer thread. GUI preview has its own decoder process and
latest-only handoff, independent of saved-video reading. Original receipt/source
timestamps remain authoritative. Explicit ring-overrun warnings and segment
boundaries prevent silent continuity claims. No free-threaded Python is required.

The Performance window and MCP snapshots expose bounded latency distributions,
preview age, worker liveness, ring occupancy and analysis/writer backlog. Tests
include seconds of deliberate analysis delay and a forced overwrite, plus the
existing MCP and physical camera paths. See [ARCHITECTURE.md](ARCHITECTURE.md) and
its evidence files for measured results and limits; these are not 4K/laptop or
race-speed OCR benchmarks. Earlier architecture/validation entries below are
historical.


## Persistent MCP service — 2026-11-03

Implemented `racevideo_mcp`, installed/enabled as user-systemd service
`racevideo-mcp.service`. Default endpoint is `http://127.0.0.1:8766/mcp`; the
outward app WebSocket uses `/bridge` on the same TCP port. Service-side configured
stores provide offline frame images, chronological contact sheets, OCR evidence
and playable MP4 derivatives while the GUI is absent. Native frame intervals are
preserved by exports; originals are retained. Private bearer and bridge tokens
are separate and excluded from repository evidence.

The GUI registers its database/instance identity and independent Tk-thread tick.
Network liveness alone does not permit commands to a frozen GUI. Commands expire,
have durable deduplicated IDs, and late results can reconcile lost replies after
reconnect. Unsaved operator camera edits reject reservations; fields reserved by
an agent show live readback, and Release agent control prevents that lease from
writing/restoring over a manual takeover. Camera request deadline fields migrate
the recording schema to v6; legacy capture processes require a restart to expose
control protocol 3. There are no CrossMgr/race model writes.

Bounded exposure/gain tuning saves trial frames and brightness/edge/optional OCR
metrics, applies a whole-preview human-visibility floor, and either keeps the
shortest qualifying exposure or restores the starting values. Reports explicitly
mark these as sampled proxies, not an optimality or race-speed accuracy guarantee.
Focus/contrast/sharpness remain directly controllable rather than automatically
swept. Unknown writes, recorder-session changes and operator takeover prevent
blind restoration. Export/tuning jobs are serialized, and OCR remains a separate
worker. Service-created recorders/OCR run in separate transient user units so an
MCP service restart does not end capture; normal GUI/CLI process behavior remains.

Validation includes 24 unit checks; actual authenticated HTTP MCP/image/video
requests; real Tk reverse GUI control, edit guard, freeze detection and reconnect;
physical C615 live sampling, ordered write/readback, duplicate suppression,
expired-request rejection, measured tuning/restore and operator takeover. The
installed endpoint returned a saved frame with no GUI. A service-created 1080p
recorder was also sampled and retained its live session through an actual MCP
unit restart, then explicitly stopped. Test camera settings were restored.
[Service guide](MCP_SERVICE.md) and
[deployment evidence](docs/evidence/mcp-service-validation.json).

## First OCR worker — 2026-11-03

Optional OCR is now an on-demand worker operating on completed SQLite clips,
separate from camera capture and Tk. The GUI supports selecting a broad blue OCR
search rectangle, requesting a scan, progress/results, and double-clicking a read
to inspect its original source frame. Default sampling is eight frames/second,
20 proposed regions/frame and one active job/database. MSER/connected dark glyph
triplets complement light-label segmentation. Native full-resolution crops are
perspective-corrected; grayscale, inset and border-cleaned variants are tried in
both orientations with digit-only Tesseract. No expected-number list is supplied.

Schema v4 adds OCR runs/progress, raw reads with source coordinates/timestamps and
summarized observations with best-crop JPEG evidence. Original frames remain
unchanged. Simple spatial/time association counts each source frame once and does
not collapse different encounters of the same number into one clip-wide identity.
A two-frame repeat is marked repeated; it is not a verified bib or race timing
result. Competing reads and single-frame detections remain candidates. No race
integration or automatic provisional read insertion is enabled.

First measured automatic run on clip #109 used a broad wheel-area rectangle
`(.15,.4,.53,.99)`, not individual plate corners. It sampled 69 of 271 frames,
examined 631 proposals and retained 71 raw three-digit variant reads. End-to-end
wall time 15.666s; process CPU time 17.146s on the development desktop. It produced:

- 469, two associated source frames, best Tesseract score 95: positive wheel-plate
  read, visually supported by the earlier source review.
- 697 and 735, single-frame candidates.
- 699, four-frame repeated candidate, incorrect for the inspected wheel plates.

235, correctly read in the earlier manually localized experiment, was not recovered
as an automatic repeated observation. Additional sampled runs vary slightly with
pixel-rounded search rectangles; these are explicit baseline errors, not acceptable
production identification. Rotation can turn readable-looking digit sequences into
wrong numeric candidates. Background labels can also be proposed. Start-list
validation, better plate detection, orientation handling and stronger temporal
validation remain next steps. Higher source resolution should improve the digit
pixel budget, but does not establish accuracy or remove exposure blur.

Optional dependencies exercised: OpenCV 4.14.0, tesserocr 2.12.0, NumPy 2.2.4 and
system English tessdata. Some neural text-detector models were explored offline,
but did not improve this blurry fixture in those trials and are not dependencies
of the shipped worker. Downloaded experimental weights remain ignored in data/;
the working implementation requires no model downloads. Limits apply to sampling
and proposal count, rather than making an unmeasured laptop CPU-budget claim.

Validation: 18 unit tests pass, including real synthetic moving-plate detection,
recognition and SQLite evidence persistence, distinct-frame voting, leading zeros,
competing reads, separate encounters and original JPEG preservation. The real-clip
Tk test exercised mouse search-area selection, a subprocess scan, progress/results
and jumping to a 469 source frame. A further run kept the physical 1080p camera
recording while OCR and review ran against the same SQLite database; frame counts
continued increasing, capture remained active and no Tk errors occurred. The test
stopped the recorder afterward. The result window also previews each stored crop.
[Automatic-run summary](docs/evidence/ocr-worker-clip109.json) and
[candidate crops](docs/evidence/ocr-worker-candidates.jpg) retain the baseline
including its wrong readings. Prior motion ROI and camera-panel regression
checks also pass. Race accuracy and 4K load remain unvalidated.

## Follow-up exposure workflow — 2026-11-03

The operator still reported inactive exposure-time controls while RECORDING after
the popup-focus correction. At subsequent inspection the recorder had been stopped;
the last logged mode request was Automatic (3). This is diagnostic evidence after
the problem, not proof that stopping caused the original failure. The original
popup exception did not recur in the new GUI log.

A further numeric-edit race was identified: after typing a value, moving focus to
Apply could allow an intervening status refresh to replace the draft with the
old camera value before the click completed. Numeric drafts are now tracked like
menu drafts, and protected until submission/readback. Programmatic readback does
not mark a field dirty. A dedicated Enable manual exposure button submits value
1 explicitly, and a prominent status label displays the camera-reported mode and
whether the driver considers exposure time writable. Stopped/offline status is
shown on each row. Start/Stop controls now allow recovery without quitting; restart
retains the camera mode/resolution/timing configuration. This is an additional
usability fix, not an assertion that the reported failure happened while stopped.

Physical regression test at 1920×1080 covered starting from stopped, enabling
Manual, typing 5 and leaving focus on Apply through several refreshes, applying
and verifying actual device readback, closing/reopening with editable value 5,
then stopping and restarting from the panel while preserving 1080p. It completed
without Tk errors and restored the original exposure settings. Existing tests for
the actual Tcl menu, inactive/active flags and 15 unit checks also passed.

## Exposure-menu correction — 2026-11-03

The first camera panel failed when the real Tcl combobox dropdown held focus:
`tkinter.focus_get()` raised `KeyError: popdown`, which stopped scheduling GUI
polls. That left status stale and prevented subsequent control writes. Earlier
hardware tests selected the menu programmatically and missed the popup-focus
path. The panel now compares raw Tcl focus paths; periodic GUI polling is also
scheduled before callbacks so a callback failure cannot permanently stop it.
Menus now have explicit Apply buttons, and draft selections survive status
refreshes until submitted. Successful camera readback clears the draft.

Regression coverage opens the actual Tcl dropdown, leaves its listbox focused
through multiple live refreshes, selects with mouse events and clicks Apply.
The hardware test checks Manual readback, enabled exposure-time controls and
close/reopen retaining the mode, then restores the original mode. The recorder
continues throughout; no camera restart is needed for this GUI correction.

## Camera controls and cat-wheel inspection — 2026-11-03

Camera settings are now exposed through a capability-driven Camera dialog.
V4L2 discovery found 17 controls on the connected C615. Manual focus is 0–255 in
steps of 17, currently inactive while autofocus is on. Exposure is 3–2047 in
standard 100µs units; manual exposure is inactive in the current automatic mode.
Current readback at inspection: autofocus on, exposure 332 (33.2ms / about 1/30s),
dynamic frame rate enabled, contrast 32, sharpness 22, brightness 128, gain 50.
These are **current** observations, not historical settings for clip #109, which
predates camera-setting logs. [Discovery snapshot](docs/evidence/c615-controls-observed.json).

The recorder accepts per-session queued setting requests, validates range/step/
menu/availability, writes to the device and reads back the result. Tk performs no
hardware I/O. Automatic-mode changes refresh dependent inactive flags. Controls
that are absent are listed, and inaccessible controls are disabled with reasons.
There is no silent preset or restart replay. Schema v3 adds a camera request log;
existing recordings remain unchanged. New motion/manual/timer metadata includes
the latest polled settings snapshot, timestamped separately from trigger time.

Validation: 15 unit tests passed, including V4L2 structure/ABI sizes, menu holes,
inactive-control rejection, range validation and readback. A physical C615/Tk test
changed and restored contrast, disabled autofocus, verified manual focus, changed
exposure mode and successfully wrote/read back 5 (nominal 1/2000s), then restored
the prior exposure mode/value. Capture continued, and invalid requests produced
an error without stopping it. All touched settings were restored. This proves
control/driver readback, not independently calibrated optical shutter duration.
An isolated panel test covered missing controls, inactive/active transitions,
request submission, focus-step rounding and disconnect errors. Existing review and
motion timing tests passed after integration.

A short additional C615 mode test captured 228 frames over approximately eight
seconds at 1920×1080, with measured recent rate 28.3fps and a 58-frame two-second
clip, no skipped clips and no buffer-size eviction. It exercised native MJPEG
capture/storage in timer mode, not high-speed OCR accuracy. The desktop app was
then reopened with `--width 1920 --height 1080` for the next wheel trial; the code's
default remains 1280×720. Existing 720p clips are retained. At identical framing,
1080p has 1.5 times the linear output samples of 720p; verify actual optical detail
and exposure rather than assuming that output dimensions guarantee readable plates.

### Saved clip #109

Interpreted the user's #109 as the saved thumbnail/clip ID: 271 original 1280×720
JPEG frames, approximately nine seconds, covering a cat wheel carrying plates.
Slow/stopped frames show **235** and **469**. During fast rotation their digits
are visibly smeared. Current automatic exposure suggests a useful next tuning
step, but the historical shutter time for these particular frames is unknown.

Two complementary OCR experiments were retained:

- `tools/inspect_wheel_plates.py` tried white-region contour proposals across all
  271 frames in a hand-bounded wheel area. It examined 1175 regions, produced only
  five three-digit candidate observations (128/144, confidence zero), and did not
  recover the actual plates. Tape glare, hands and nearby objects joined the
  white plate regions into poor proposals. This approach is not a usable detector.
- `tools/inspect_plate_crops.py` used two manually selected quadrilaterals on frame
  46 and reused them across frames 40–54. OCR received digits 0–9, **not** an
  expected-number whitelist. It recovered 235 in 13 distinct frames and 469 in 10,
  with best Tesseract confidence 93 and 96. Incorrect/blank results remain in the
  raw CSV; these scores are not calibrated correctness probabilities. Both best
  examples were visually checked against the image. The source plate regions are
  only about 42×25 and 35×23 pixels, before perspective correction/enlargement.

[OCR example crops](docs/evidence/clip109-ocr-examples.jpg) and
[manual localization summary](docs/evidence/clip109-crop-ocr.json). Full raw results,
sampled source frames and native/extracted crops remain ignored under
`data/plate-review-109/`; the original SQLite recording was read without alteration.
Reproduction uses the parent experiment's optional OCR dependencies:

```sh
../.venv/bin/python tools/inspect_wheel_plates.py --db data/racevideo.sqlite3 --clip 109 --out data/plate-review-109
../.venv/bin/python tools/inspect_plate_crops.py --db data/racevideo.sqlite3 --out data/plate-review-109
```

Conclusion: this 720p fixture has enough detail for useful OCR in selected slow
frames. It does not establish reliable high-speed reads or automatic localization.
Try manual focus and a short fixed shutter with more illumination/gain, then
compare moving crops. At the same field of view a genuine 3840-pixel-wide frame
has three times as many horizontal samples as 1280, but extra resolution alone
will not fix exposure blur. The ordered camera's optical framing and short-shutter
performance still need physical testing.

## Motion capture update — 2026-11-03

Motion is now the default trigger. The original timer remains available with
`--trigger timer`. Initial centered ROI is normalized `(0.425, 0.15, 0.575, 0.85)`:
15% of image width, 70% height. Corners resize; interior dragging moves the box in
both axes. Coordinates are clamped to the camera image and persist per database.
ROI edits apply on release; the detector baseline resets to prevent false motion
from comparing different crops. An event active during an edit is saved with
`end_reason=roi_changed` before the new area is used.

A 0.2s quiet tolerance holds red through small gaps. Yellow returns after that,
but the clip continues collecting its 2s trailing window. Any motion before the
trailing window expires extends the same event; it does not create overlapping
clips. Pre-roll is 0.5s, including the immediately preceding frame at the boundary
when available. Window lengths follow actual monotonic timestamps, not nominal
fps. Explicit stop/error saves a partial event, marked accordingly.

Pillow/libjpeg decodes reduced grayscale images, bounded to 320×180, at up to
15 analyses/s. A Gaussian blur reduces noise; an initial threshold requires 2.5%
of ROI pixels to change by at least 18/255. No new dependency was needed. Global
exposure changes, shadows, autofocus and camera movement can still trigger; actual
race sensitivity and moving-plate performance remain unvalidated.

Active motion clips split at 30s or 128 MiB and share an event ID and sequential
chunk number, keeping memory bounded during continuous movement. The rolling
buffer remains separately bounded. Motion thumbnails use the detected interval,
rather than the potentially empty middle of a trailing window. Original full-rate
camera JPEGs are preserved. Schema v2 adds settings and event metadata tables;
existing clips and frames are retained. Metadata records ROI, thresholds, timing,
logical event/chunk identity and the reason the chunk ended.

Validation: 11 unit tests passed, including static/outside-ROI rejection, detected
movement, ROI reset, 0.5s pre-roll, 0.2s gaps, 2s tail, renewed motion during the
tail, no-loss chunk splitting and migration with existing clips. The recorder
integration with deterministic JPEG camera input produced one 31-frame clip with
0.500s pre-roll and 2.001s post-roll. Tk mouse tests passed for all four corners,
2-axis movement, bounds, red/yellow feedback, persistence, resizing and hiding
the rectangle in replay. Existing physical-camera timer/review tests also passed. The motion-mode physical
webcam test passed with 10 clips, including applying a GUI-edited ROI to the
running recorder, manual saves during review, independent GUI close and clean
stop. The normal desktop app was relaunched in motion mode; status confirmed the
centered default ROI, approximately 30 fps, no skipped clips and a quiet detector.
Repeated deterministic timing checks stayed within one 10 fps test-frame interval
of the requested boundaries.
These tests do not establish real race detection accuracy or calibrated timing.

## Initial implementation — 2026-11-03 (historical baseline)

The empty `racevideo` repository is now the implementation home. `PLAN.md` carries
forward the camera/OCR design and CrossMgrVideo comparison from the parent
experiment. Original MOVs, exported plate CSVs, review crops and scanner stay in
`../`; small original run/CPU summaries are copied into `docs/evidence/` so those
observations are retained with the code. Those benchmarks concern earlier OCR
experiments, not this recorder's measured CPU usage.

The ordered camera has not arrived. The exact purchased model has not been
confirmed here. The two previously researched suggestions remain in the plan:
ELP-U3CAM4K60-IB(5-50B), a 4K IMX678 camera with manual 5–50 mm lens, and enclosed
Arducam B0495C, a lower-resolution AR0234 global-shutter alternative. Prices and
product claims are dated research; neither has been hardware-tested here.

### Logitech test fixture

- Logitech HD Webcam C615, `/dev/video0`; `/dev/video1` is the other enumerated node.
- Stable path observed:
  `/dev/v4l/by-id/usb-046d_HD_Webcam_C615_E8CBAB50-video-index0`.
- V4L2 enumerates MJPEG and YUYV, including 1280×720 and 1920×1080. Enumeration
  does not establish a working fps at every resolution.
- Direct PyAV capture verified complete MJPEG/JPEG packets at 1280×720. The
  requested rate was 30 fps; measured rate was around 14–15 fps. No exposure
  setting was changed or read back, so the cause of the lower rate is unconfirmed.
- First 12-second recording test: 176 frames received; two timer clips with
  29 and 31 frames. Both span approximately 1.996 seconds. No skipped clips or
  buffer size evictions; rolling buffer approximately 5.3 MB in that scene.
- Dependencies exercised: Python 3.13, PyAV 19.0.2, Pillow 11.3.0 and Tk, Linux/X11.
  Development desktop differs from the target i7-12850HX race laptop.

### Deliberate first-version decisions

- Timer triggering exercises the compressed pre-trigger buffer: save the most
  recent two seconds, first automatic save about ten seconds after startup.
  `--interval` and `--seconds` are configurable. Overlapping manual/timer windows
  are separate clips for now.
- Store original JPEGs as SQLite BLOBs. No MP4 encoder, codec availability issue,
  or long-GOP seeking is necessary to prove capture/review. Export can be added
  later, outside the capture process.
- Separate recorder process; review can close/reopen without losing capture.
  Disk writer and review decoder run away from Tk's event loop. This is not a
  claim of a measured two-core budget; profile full camera modes on the laptop.
- Host receipt UTC, host monotonic time and camera/driver source PTS are retained
  separately. Neither driver PTS nor receipt time has been calibrated to exposure
  time. Playback uses monotonic intervals and never assumes configured fps.
- Limits bound compressed buffer and queued pending clips. Native frame decoding
  is limited to preview/thumbnail/review frames. The strip retains small decoded
  thumbnails, not full-resolution frames for every clip.
- Status exposes actual fps, buffer duration, saved/skipped counts and errors.
  A stalled/stopped recorder shows a last-frame warning in Live.

### Still to implement

1. Completed in the motion update above: ROI editing and motion-triggered
   pre/post-roll capture. Tune sensitivity and test detection in race conditions.
2. Device/mode enumeration and optional per-camera presets remain. Live exposure,
   gain/focus and other discovered V4L2 controls with readback are implemented. Favor sharp digits at short
   exposure over pleasant automatic low-light images.
3. Automatic reconnect with explicit new stream sessions and discontinuity markers;
   test physical unplug, blocked capture, disk failure and crash/restart paths.
   Current capture errors stop the recorder; relaunch it to retry.
4. Retention/archiving and storage-rate display; image zoom, annotations, JPEG/video
   export and durable bookmarks. Large archives need paged thumbnail loading;
   this prototype loads all small thumbnails and has no automatic deletion.
5. Separate plate detector/OCR consumer with a start list, nearby-frame agreement,
   recorded evidence, and a durable observation stream for CrossMgr reconciliation.
   No OCR, race edits, RFID listener or race timing calibration
   is implemented in this initial UI/capture version.
6. Real moving-plate trials with the ordered camera, including short exposure,
   focus/framing, bunch occlusion, rolling-shutter artifacts, sustained I/O and
   CPU/thermal load alongside CrossMgr on the actual race laptop.

### Validation

Automated unit checks cover elapsed-time buffer selection, byte cap, original
JPEG/PTS persistence, transactional rollback and SQLite integrity after reopen.
The Tk review smoke test uses saved camera clips on an isolated Xvfb display and
exercises Live, thumbnail navigation, individual frame stepping, playback and
return to Live. A separate physical-camera test checks recording while reviewing,
new thumbnails, manual capture, horizontal dragging, page navigation, duplicate
recorder rejection, closing the GUI without stopping capture, graceful stop and
every saved JPEG. These are functional checks, not a sustained race-load test.

Validation result: all three unit tests passed; the saved-clip Tk smoke test
passed; the physical Logitech integration test saved 10 clips and passed every
check listed above. Initial screenshot was visually reviewed at 1200×850 on
Xvfb. The normal desktop launcher was then started using the default ten-second
interval and two-second window. Test databases/screenshots remain ignored under
`data/`; no original footage was moved or modified.

## GPU OCR comparison and supplied font, 2026-11-05

See GPU_OCR.md and docs/evidence/zbook9/elp/gpu-ocr/ for native RTX A1000
benchmarks. PP-OCRv5 mobile via PaddleOCR3.3.2 read the operator-selected
frame69 235 crop and outperformed EasyOCR1.7.2 on sampled sequences, including
correct fixture numbers in faster clip71 where Tesseract had none. Wrong
candidates remain; frame counts are not passings. Production engine unchanged.

The supplied alte-din-1451-mittelschrift.regular.ttf was inspected and copied
unchanged to zbook9. Its internal family is Alte DIN1451 Mittelschrift Regular,
not the previously reported Engschrift. Preserve both facts when preparing
synthetic data; do not treat this as a verified exact label-font match.
