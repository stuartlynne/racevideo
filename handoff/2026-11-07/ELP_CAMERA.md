# ELP camera initial connection — 2026-11-05

Connected to zbook9 as **4K U3 Camera**, USB VID:PID `32e4:6678`.
Capture node `/dev/video4`; `/dev/video5` is metadata, not a capture source.
Stable device path:

```text
/dev/v4l/by-id/usb-4K_U3_Camera_4K_U3_Camera_2601230006-video-index0
```

USB negotiated 5000 Mb/s. The device advertises MJPEG 3840x2160 at up to 60fps;
initial RaceVideo operation verified delivery at approximately 30fps using
3840x2160 MJPEG with a 256MiB compressed ring. A manually saved segment contains
61 original 4K JPEG frames. No analysis overruns, skipped clips or capture errors
were reported in the initial status samples. These dark-scene measurements are
not a moving-rider quality or real-scene throughput benchmark.

The selected mode/device is saved for the GUI Start recorder control. The GUI is
open on zbook9 in Live with the headless recorder running. Original automatic
exposure mode3, exposure raw156 and gain140 were restored after diagnostic trials.

## Current image problem

Both 4K and 1080p images remain nearly black/featureless. The user reports that the
camera is uncovered and aimed at a lit scene. Manually requested 20ms and 100ms
exposures with gain190 were accepted/read back, but did not yield scene detail.
This does not establish the actual optical exposure or prove a hardware fault.
Physical iris/aperture and any shipping film/cover check is pending. No OCR,
sharpness, focus, motion-blur or race-readiness claim can be made from these frames.

The camera reports manual/automatic exposure, gain, sharpness, autofocus/manual
focus, pan/tilt and 100–200 zoom controls. Physical focus/zoom behavior remains
unverified; advertised controls alone do not prove a motorized/optical operation.
Privacy control readback returns USB EPIPE; it has not been changed or validated.
Unsupported rectangle/bitmask controls are not adjustable in the current panel.

[Initial captured-mode/status evidence](docs/evidence/zbook9/elp/initial-validation.json).
Further image/plate testing is required after resolving the dark image.

## Iris/focus resolved and plate OCR verified

The user opened the manual iris and adjusted the FAR/NEAR focus ring. This
restored a bright scene with clearly readable 235 and 469. The lens therefore
requires these physical adjustments; reported UVC autofocus controls were not
used to achieve this focus.

Saved **clip 16** is starred as a reference. A full-frame scan of eight samples
from the two-second 4K segment found 235 in eight frames and 469 in three, using
no bib whitelist. Two full-frame v1 runs reproduced the result in about 15.5s.

A cropped v1 trial failed (only a wrong, single-frame 965 candidate). Investigation
showed that cropping changed detector scale, magnifying characters beyond its
size heuristics. Engine v2 now anchors detection scale to full-frame dimensions:
ROI reduces work/clutter without changing the detector's pixel calibration.
The same crop then found 235 in eight samples and 469 in three, taking about 8s.
469 split across two observation tracks, reinforcing that encounter counts are
not automatic lap counts. Previous runs remain as evidence/history.

One camera packet lacking a valid JPEG start had previously stopped recording.
The capture path now checks JPEG markers/FFmpeg corruption flags, discards and
counts isolated bad packets, and fails visibly after sustained corruption.
Per-clip metadata reports cumulative packet loss before/through the segment and
loss within it. Status exposes `capture_bad_packets`; updated GUI shows camera
gaps. This is structural validation, not proof every encoded JPEG is error-free.

42 unit tests pass on development host and zbook9. An actual recorder integration
test injecting a damaged packet passes: recording continues, the bad packet is
excluded, source timestamps/pre-post-roll remain correct and the segment records
its packet-loss count. The updated capture remains running at 4K/30 and Live is
open. Automatic exposure is still enabled; fixed short exposure and moving-wheel
OCR must be tested before drawing conclusions about race-speed recognition.

[Focused-wheel results and all OCR trials](docs/evidence/zbook9/elp/focused-wheel-validation.json).

## Four wheel runs at fixed 1/250 second

The user identified two medium and then two slow runs, excluding their final
movement away from the wheel. Event metadata plus contact-sheet review identifies:

| Test | Linked clip IDs | Frames with a qualified 235 hypothesis | Frames with a qualified 469 hypothesis |
|---|---|---:|---:|
| Medium 1 | 46–47 | 6 | 7 |
| Medium 2 | 48–49 | 2 | 4 |
| Slow 1 | 50–51 | 10 | 11 |
| Slow 2 | 52–53 | 9 | 9 |

OCR used eight samples/second from the first chunk of each event, which contains
the wheel passage. Counts are distinct source frames with an OCR hypothesis at
score >=60, not calibrated confidence, distinct riders, laps or moving-only recall.
They include any pre/post-roll frames in the segment. Representative source crops
were visually checked for both printed numbers. Clips 54–55 were excluded as the
user's movement back; earlier adjustment clips were not counted as wheel tests.

At the start of investigation, all these clips were unscanned: OCR is currently
on request, not automatic. The prior automatic-exposure clip21 visibly smeared
plates after acceleration. The camera was switched to manual mode, exposure raw40
(nominal 4ms / 1/250s), gain190. This produces a dimmer but usable indoor picture.
Outdoor exposure/lighting and real rider-speed performance still require tests.

The v2 recognizer had 469 among its raw readings but could drop it when another
preprocessing/orientation interpretation scored higher, then discard nonwinning
track hypotheses. Engine v3 retains qualified alternatives with one vote per
number/source frame and keeps lower-ranked alternatives as review candidates.
This preserves useful evidence without calling it confirmed. Unconstrained false
alternatives such as 697 are still present; a valid start list and proper event
context remain important future improvements.

Existing raw v2 readings were reanalysed using v3 tracking, preserving prior jobs
and recording source_run_id/reuse provenance in new jobs. This is not a new faster
recognition benchmark: original recognition took approximately 20–22 seconds per
first chunk; the subsequent cached-read reanalysis only rebuilt observations.
Current GUI/MCP bib matching now finds all four reference chunks for either bib.
Both chunks of each reference run (46–53) are starred.

128MiB caused the large 4K frames to split events every ~2–3 seconds. The cap is
now 512MiB on the 32GB laptop; long events still split, queues/rings remain bounded,
and original event IDs link their chunks. Capture is still 4K/30 with the fixed
exposure/gain read back after the configuration restart. No new packet loss or
skipped clips was reported during this test.

New thumbnail labels distinguish not scanned / queued / running / no candidates;
OCR is explicitly labelled on request. Same-clip metadata changes update retained
canvas items instead of rebuilding all thumbnails. An active operator zoom/view
was preserved on the production GUI, so these label changes load on its next
launch. 43 unit tests and temporary-store real GUI review/cleanup tests pass on
zbook9. [Structured trial evidence](docs/evidence/zbook9/elp/spins/summary.json).

## Approximate tag rim speeds, assuming 48-inch diameter

Using the original frame PTS/timebase and source-image plate centres in clips
46/48/50/52, an ellipse was fitted to the visible circular path. Partial-arc
angles were unwrapped separately for 235 and 469, then visible traversal rates
were averaged with elapsed-time weighting. This does not count complete wheel
revolutions; equivalent frame counts extrapolate the visible arcs.

For diameter 48in = 1.2192m, circumference is 3.8302m. At nominal 30fps:

`speed_kmh = 3.8302 * 30 * 3.6 / frames_per_revolution = 413.665 / N`

| Run | Approximate mean rim speed | Equivalent frames/revolution at 30fps |
|---|---:|---:|
| Medium 1 (46) | 4.6 km/h (2.9 mph) | 90 |
| Medium 2 (48) | 5.3 km/h (3.3 mph) | 79 |
| Slow 1 (50) | 2.2 km/h (1.4 mph) | 189 |
| Slow 2 (52) | 1.7 km/h (1.1 mph) | 242 |

The slow runs changed speed substantially: short measured intervals ranged about
1.1–3.0km/h and 0.3–3.3km/h respectively. These means do not include an entire
motion clip's stationary tail, but do include deceleration while tags remained
visible. Assume the tag centres lie at the 24-inch radius; using a smaller actual
tag radius scales speeds down proportionally. Ellipse normalization approximates
perspective, not a calibrated projective camera model, so these are rough physical
speed estimates. Source-point radial fit residual median was about 0.2% of the
fitted image radius; that is fit consistency, not a physical-speed error bound.

The tested speeds are approximately walking pace, substantially below race
speeds. At 40km/h, an object travels about 44mm during a 4ms exposure; actual image
blur also depends on camera viewing direction/projection. This wheel test does
not yet establish recognition at that speed.

[Full calculation, timing intervals and assumptions](docs/evidence/zbook9/elp/spins/speed-estimate.json).

## Source of 637 / 697 alternatives

Direct inspection of the saved raw-read quadrilaterals confirms that the 637
example in clip52/frame36 and the highest-scoring 697 examples in clips46/48/50/52
come from the **469 test plate**, not shelf labels or other background text.
They were produced by the recognizer's 180-degree orientation attempt. Inverting
469 makes a strong competing glyph pattern; examples scored 93–96 despite being
wrong. These are alternative interpretations of the same physical plate and must
not be counted as additional riders. The wheel test needs arbitrary orientation;
race-time orientation/start-list context can help, but cannot resolve an ambiguity
merely by both numbers being valid entrants. No orientation policy was changed
as part of this inspection.

## Restricted top-wheel scan, 2026-11-05

Saved OCR ROI `[0.34, 0.35, 0.60, 0.56]` and upright-only test policy `[0]`
were deployed to zbook9. The GUI was reloaded in Live without stopping the
independent recorder. New scans sample 8 fps; originals and previous OCR runs
are retained. Motion region, camera exposure and recording policy are unchanged.

| First clip | Trial | Candidate bibs in restricted scan | Wall time |
|---|---|---|---|
| 46 | Medium 1 | 469 | 3.4 s |
| 48 | Medium 2 | 409 (incorrect) | 8.1 s |
| 50 | Slow 1 | 235, 469 | 4.3 s |
| 52 | Slow 2 | 235, 469, 463 (incorrect) | 4.7 s |

637/697 no longer appear in these four restricted scans. This does not make OCR
reliable: a smaller region reduces the number of useful frames, and wrong/missed
readings remain. The checkbox is an explicit fixture test; normal race defaults
remain 0/180 OCR passes, with broader label-orientation handling on the TODO list.
Evidence: `docs/evidence/zbook9/elp/spins/top-zone-test.json`. Local unit validation:
45 tests passed; the table above is a native OCR rerun on physical-camera clips,
not a synthetic accuracy claim or race-speed validation.

## Faster wheel trial, 2026-11-05

Clips 70–73 were captured and starred. Clip 71/72 share a continuous motion
event split at the compressed-byte limit; originals remain intact. Clip 71
metadata records manual exposure absolute 40 (nominal 4 ms), gain 190, zero
analysis overruns and zero bad packets within that segment.

Measured repeated top-wheel plate groups (two neighbouring plates form one
group per revolution) against acquisition monotonic timestamps. Selected clean
intervals give clip 71 mean 0.894 rps / 12.3 km/h and clip 72 mean 1.000 rps /
13.8 km/h. Individual intervals span roughly 11–16 km/h. Assumes plate centres
at a 24-inch radius. This is an approximate test-fixture speed, not calibrated
race timing; hands, stopping and the plate-detachment tail are excluded from
the selected speed intervals. Consecutive frames 90–149 in clip 71 visually
confirm successive paired-plate traversals.

Native upright-only OCR within the same saved top ROI, requested sample rate
15 fps, produced no qualifying observations in 70/71/72. Actual sampling counts
were 38/126/82 (around 10 fps with the current timestamp-based sampler), not
all 30 captured frames/sec. Clip 73 produced repeated 235 plus incorrect 194/199
candidates. The latter is a final slow/stationary tail and is not evidence of
fast-pass OCR success. Visible digit smear exists across consecutive source
frames; sampling alone does not explain this result. At 14 km/h a plate moves
about 16 mm during a 4 ms exposure. A shorter exposure/brighter-light comparison
would help separate acquisition limits from detector/OCR limitations. Camera
settings were not changed during this analysis.

Evidence: `docs/evidence/zbook9/elp/spins/fast-wheel-test.json`, retaining native
OCR run IDs, summary timings, candidate evidence and measured frame intervals.

### Shorter-exposure trial

At the operator's request, changed manual exposure absolute from 40 to 10
(nominal 4 ms / 1/250 s to 1 ms / 1/1000 s). Driver readback confirmed 10.
Gain remains at its reported maximum 190. A fresh live sample is very dark
(mean 33.56, median 33 on this camera's output); static 235 remains faintly
visible, but no moving-plate OCR validation has been performed at this setting.
Left 1 ms active for the next test. More scene light/opening the manual iris
if available is needed to recover illumination; no automatic exposure enabled.

### Shop-light spin at 1 ms

Reviewed and starred clips 79–82, native OCR runs 24–27, retaining prior evidence.
Clip 81 contains moving plate 469 correctly recognized at source frames 59, 62
and 65 (scores 95,79,96). Plate 235 produced score 46 at frame 14, below the
60 threshold, with incorrect competing 735 at score66. Clips79/80 have no
qualifying observations; clip82 includes stationary/handling footage with some
469 readings and wrong 698/659 candidates. This is not reliable passing-level
recognition. Source crops look less smeared, but the spin appears slower than
the previous 4ms trial, so neither exposure benefit nor OCR improvement is
isolated experimentally. Illumination remains low. Current ROI and camera
settings were not changed for this analysis. All four clips ended quiet and
record zero analysis overruns/bad packets; continuous detection of dark-scene
wheel motion has not been independently established.

Evidence: `docs/evidence/zbook9/elp/spins/one-ms-shoplight-test.json`.

### Operator-selected capture 81, frame 69 of 78

GUI frame69 is source ordinal68 (GUI numbering is one-based). Directly inspected
that frame and its adjacent ordinal69; the plate reads 235 to a human. Native
proposals/recognition returned no text on either, also none on final GUI frame78.
A manually selected original-pixel crop `[1740,1010,2000,1170]` clearly retains
the digits, but direct Tesseract single-line/word/raw-line attempts on raw,
percentile-normalized and Otsu variants returned no text. These diagnostic
manual-crop attempts do not change stored OCR observations. This establishes
useful source detail that the present pipeline is failing to read; do not
attribute every missing OCR observation solely to exposure or motion blur.
