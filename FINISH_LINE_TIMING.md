# Virtual finish-line timing prototype

2026-11-09: read-only diagnostic on the November 8 field footage. No capture,
OCR, review or race records were changed by this experiment.

## Demonstrated example

Clip 877, rider with frameplate 24, travelling right to left. Assume a vertical
finish line at x = 1920 in the 3840 × 2160 source image (normalized x = 0.5).

| Evidence | Displayed frame | Host receipt time, November 8, UTC−07 |
| --- | --- | --- |
| Last tyre edge before line | 15 (ordinal 14) | 15:27:12.321566405 |
| First tyre edge observed past line | 16 (ordinal 15) | 15:27:12.353533450 |
| Linear interpolation estimate | Between those frames | Approximately 15:27:12.341 |

The measured leading edge moves from 99.8 pixels before the line to 67.8 pixels
past it. The observation interval is approximately 31.97 ms. Subframe
interpolation estimates the crossing; it does not create another captured frame
or establish millisecond accuracy.

Evidence: `data/validation/finish-line/clip877-centre-crossing.jpg` and `.json`.
The JSON retains source ordinals, receipt and monotonic timestamps, driver PTS,
line geometry, wheel measurements and the estimated time. Local time rendering
uses the copied laptop timezone data, which differs from this host's older data.

## Method and current limits

The diagnostic uses a CPU PicoDet bicycle detector, plausible wheel-circle pairs
inside the bicycle region, and leading-arc edge refinement to estimate the outer
front tyre. The initial circle fit sometimes follows the rim rather than the
tyre; that difference is significant for crossing time. This is a visually
checked single-bike demonstration, not a validated general detector. Its scripts
are in the evidence directory; `racevideo/crossing.py` provides the isolated
crossing/bracketing calculation with unit tests.

The original diagnostic was standalone. See the November 11 integration below;
CrossMgr timing publication remains unimplemented. Dense groups, occlusion, shadows, off-axis wheels, motion blur and
false circle fits require further evaluation. A fully hidden front wheel should
produce an uncertain bracket or no timing result rather than a confident guess.

Host receipt times are not calibrated exposure timestamps. USB buffering, camera
readout and rolling-shutter row timing can shift the relationship. Saved driver
PTS is useful evidence, but its original timestamp-source flags were not saved.
Laptop wall-clock synchronization also needs verification before comparing
against external timing equipment. The reported receipt-time bracket therefore
does not bound the true exposure time in UTC.

## Production direction

1. Let the operator place a finish line over Live and review imagery. Persist
   geometry per camera/session; start with the requested vertical centreline.
2. Track each physical bike passage, determine travel direction, then identify
   its front wheel and leading tyre edge. A later lap is a new passage.
3. Associate OCR evidence from any frame of that passage with the bike track;
   the best OCR frame need not be the crossing frame. Preserve ambiguity when
   adjacent riders cannot be associated reliably.
4. Save the last-before and first-touch-or-past source frames, timing basis,
   detection confidence and uncertainty. Interpolate only as an explicitly
   labelled estimate when justified; retain the original observations.
5. Review annotated crossings across different riders and crowded clips before
   enabling automatic timing publication. Keep this work asynchronous and away
   from capture and GUI drawing.
6. At an event, align the camera with a physical finish plane and reference
   markers across the road. An arbitrary image centreline is sufficient for this
   experiment, but an oblique view can otherwise measure different course
   positions for riders at different distances from the camera.

The calculation currently refuses interpolation across missing detection frames
or a wall-clock discontinuity relative to the monotonic clock. These safeguards
do not themselves establish detection or clock accuracy.

## Planned GPS optical calibration beacon

Discussion, 2026-11-09; hardware and software are not implemented or validated.

The proposed far-side finish reference is a white board approximately **8 cm wide
and 1.5 m tall**, with a GPS receiver/antenna on top. The contemplated beacon is
an approximately $100 ESP32/GPS device; that is a budget idea, not a verified
parts quote. A GPS-aligned LED would flash once per second for approximately
100 ms. Put the LED on the board near the image height of the front tyre's leading
edge, with wiring up to the electronics, to reduce rolling-shutter row differences.
The board is an alignment reference; camera placement must still align the view
with the intended finish plane across the road.

Prefer a receiver with a configurable UTC-aligned hardware time-pulse output
driving the LED through an appropriate driver. The ESP32 can configure the receiver
and report the UTC second, lock/timing-valid state and pulse configuration. PPS
alone does not identify which UTC second it represents. Do not derive the optical
edge time from Wi-Fi or serial message arrival. Verify the chosen receiver's pulse
semantics, UTC association and behavior when timing is invalid.

The user proposes scrubbing backward or forward in the continuous capture buffer
to find a flash, then transferring that reference to a rider's crossing. A flash
does **not** have to occur within every saved motion segment. Automatically sample
a small fixed beacon region continuously, independently of rider detection. Exclude
it from motion triggering so the beacon does not create captures by itself.

Use actual source-frame timestamps and sequence information rather than nominal
FPS multiplied by a frame count. Retain the last-dark/first-lit bracket around the
known pulse edge. Flashes on both sides of a crossing can check offset stability,
drift and buffering changes. Keep camera-session boundaries explicit: reconnects,
capture-mode changes or timestamp discontinuities require a new calibration.

A 100 ms flash should be easy to see across several frames at 30 or 60 fps when
unoccluded and with continuous capture, but its duration is not the calibration
accuracy. An observed on/off transition initially brackets the edge to about one
frame interval. Repeated pulses may refine calibration, but a stable phase
relationship between frame acquisition and PPS can preserve an unresolved offset.
Occlusion, dropped frames, saturation and rolling shutter need explicit handling.
Do not promise millisecond accuracy without measurement. A coded optical pattern
is a possible later improvement for time identification and finer phase estimation.

### Buffer retention and saved evidence

The ring buffer is bounded. Retain each calibration observation and enough source
imagery to audit its transition **before those frames are overwritten**. A later
review of a saved rider clip cannot assume neighboring continuous footage remains
available. Waiting for a future flash must not block capture or the live GUI.

Persist calibration separately from immutable original frame timestamps:

- Camera/session ID, beacon image region and image-row position.
- Known UTC pulse edge, timing-valid state, pulse width and polarity.
- Last-dark/first-lit frame references, original receipt/monotonic timestamps,
  source PTS/time base and relevant driver timestamp flags when available.
- Detection measurements, retained evidence images and any occlusion or gap flags.
- Derived timestamp correction, uncertainty, validity interval and method/version.
- Which calibration observations were used for each corrected wheel-crossing time.

Record raw and corrected times together. Do not silently rewrite historical source
timestamps or equate a host-receipt bracket with calibrated exposure UTC. If no
valid nearby observation survives, mark timing uncalibrated or explicitly state
the age/uncertainty of the last usable calibration.

## November 11: review integration

The operational time display now uses the cached CrossMgr event `start_ns`.
Camera timestamps subtract the configured **camera minus CM** offset once before
subtracting that start. CrossMgr passings already use the CM clock. Review frame
labels, the large time overlay below the bib, thumbnails, sightings and passing
columns/rows show race elapsed HH:MM:SS (milliseconds where useful). No associated
race, or unresolved overlapping events, uses clearly labelled wall-clock time.
Calendar dates and cache-import metadata remain calendar information.

A yellow vertical line follows the measured leading front tyre on frames where
detection succeeds; the fixed centre reference and wheel circle are hidden. `Track front
wheel` enables asynchronous analysis of the selected physical bike passage;
`Analyze wheels` retries, and `Crossing frame` seeks the first observed frame at
or beyond the line. Detailed controls distinguish current frame time from the `Finish ≈` estimate;
the left overlay uses compact whole-second time.
Missing wheel detections retain a wider crossing bracket without interpolation.
Switching bike/clip discards unrelated overlay results. Zoom and pan transform
measurements from original source coordinates.

`wheel_analyses` is an additive SQLite metadata table. Original source frames,
OCR and operator identity decisions remain intact. One bounded worker per store
runs outside Tk/Reader, using at most two logical CPU affinities, single-thread
OpenCV, and at most 300 source frames per selected encounter. CPU OpenCV fits
wheel pairs and refines the leading tyre arc; available NVIDIA PicoDet bicycle
regions assist failed fits. Local CPU neural refinement is explicit via Analyze
wheels; no AMD GPU/Vulkan path is used. Missing optional models fall back to
OpenCV with a recorded diagnostic. Results are cached by geometry/algorithm.
Wheel tracking and identity confirmation are separate decisions.

This remains experimental: circle fits, motion-region association, occlusion,
rolling shutter and clock calibration require operator inspection. Reproducing
a crossing in one clip does not validate all riders. Adjacent source-frame
brackets support interpolation; missing-frame or discontinuous-clock brackets
do not. Host receipt time is not a calibrated exposure timestamp. A future
CrossMgr handoff candidate retains bib/event, race elapsed estimate, clock
offset, source frames, line geometry and timing basis, and is explicitly
unreviewed/provisional. No button currently publishes reads to CrossMgr and
Space continues to confirm identity only.

### Integration validation

November 11: 180 unit tests passed on whiskey and zbook9. Headless GUI checks
covered session restoration, confirmation/undo and grouping, plus a dedicated
wheel test on both hosts for elapsed overlays, source geometry during zoom,
missing-sample suppression, crossing seek, stale-clip isolation and Reader
polling without browse-selection resets.

The real zbook9 CUDA-assisted automatic motion-region run on clip 877 recovered
adjacent ordinals 14/15 (displayed 15/16), a 31.967015 ms monotonic interval.
Its current tyre fit estimates host receipt NS 1794176832339073806, shown as
**Race 01:07:34.347** for Elite, start NS 1794172777991621000, offset zero.
The first observed after-line frame shows **Race 01:07:34.361**. The differing
frame and estimated finish values are intentional. The earlier diagnostic's
slightly different fit estimated ~1794176832340050879 NS: that approximately
1 ms variation is detector variation, not evidence of millisecond accuracy.

A real-footage headless review on zbook9 selected the associated bib 24 passage,
loaded the cached result, sought displayed frame 16, and rendered both the fixed
finish line and moving tyre marker. Screenshot copied to
`data/validation/zbook9-race-wheel-review-ui.png`. Existing operator GUI process
and saved session were left running/untouched; reopen to load the new modules.


### Operator correction: moving yellow markers and compact overlay

The review overlay no longer displays the fixed centreline. The yellow vertical
line is at the measured **leading front-tyre edge** on the displayed source
frame. The crossing calculation still uses normalized x=.5 internally. The
circle overlay is hidden to reduce clutter.

The left time overlay contains compact whole-second time only: `7:34` or
`1:07:34`, without Frame/Race/Finish labels or fractional seconds. When an
estimated crossing is available it supplies that value; otherwise the current
frame time (or unresolved crossing range) is displayed. Detailed labelled frame
and estimated crossing times remain in the bottom controls, and database
nanoseconds/brackets are unchanged. Use colons for hour/minute/second separators.

Other tracked passages visible at the displayed ordinal are analyzed sequentially
after the selected bike, using the same bounded worker/cache. Each successfully
measured peer has its own yellow line, bib (or Bike index) beside the line, and
bib/time row on the left. A missing frame measurement hides that bike's marker;
no marker is extrapolated. Reports are keyed by physical-passage geometry, not
just bib, so a later encounter is separate. This supports multiple measurements
in one image but does not establish reliable wheel/identity separation in dense
road sprints; field validation remains necessary.

The dedicated GUI test covers two simultaneous markers with distinct positions
and times, background peer scheduling, zoom alignment, missing samples and
stale-clip isolation. 181 unit tests and GUI checks pass on both hosts. Reopen
the deployed zbook9 app to load these presentation changes.

### Lap 6 missing-marker correction

Some later passings had only a single OCR/manual source-frame anchor. The
Reader's geometry fallback used identity-aware navigation, which could select
that same geometry-less anchor again. Wheel analysis then received no motion
points and no travel direction and completed with zero measurements. The GUI
also restricted an anchored subject to its original frame ±5, even when wheel
measurements covered more of the encounter.

Algorithm version 6 resolves missing/degenerate geometry inside the bounded
worker from raw cached bicycle/motion passages, then a source-frame motion scan
if needed. Geometry is attached to the original review identity and source
ordinal; navigation, reviews and source frames are not rewritten. Candidate
association is constrained to the source-frame encounter and preserves ambiguity
between competing bodies. The algorithm/cache version invalidates older empty
results. The selected identity remains active across its measured frame range.

On zbook9, Elite Lap 6 bib 100, clip 808: recovered 15 measured frames from a
manual anchor at ordinal 11. The crossing is bracketed by ordinals 14 and 16
(displayed 15 and 17), 67.95 ms apart. Ordinal 11 itself still has no reliable
wheel measurement; the next ordinal 12 does. The status explicitly reports a
missing measurement at the current frame and Crossing frame seeks the supported
bracket. No invented marker/interpolation fills these gaps. Regression checks
cover geometry-less anchors, encounter separation, ambiguous bodies, unchanged
source/review identity, and scrubbing beyond the original anchor. 183 unit tests
pass on both hosts, plus GUI checks and real clip-808 review.

The review button now becomes **Wheel frame** when measurements exist but no
crossing is bracketed. It seeks the nearest actually measured frame; when a
crossing is bracketed it remains **Crossing frame** and seeks first observed
at/past. No synthetic wheel position is substituted for an unresolved frame.

Targeted reanalysis of the eight geometry-less entries observed in the recent
review history (clips 808, 804, 803, 801, 800, 799, 798, 797) completed on zbook9:
all eight now have wheel measurements, but only three have a crossing bracket.
This is not a complete reanalysis of Lap 6 or the day. Results are retained in
`data/validation/lap6-wheel-recovery.json`; raw footage and identity reviews are
unchanged. Additional riders are processed on selection after reopening the app.

### Explicit passing-to-timing database links

`wheel_analyses` already retains each measured wheel position, source frame,
receipt/monotonic/PTS clock and crossing report. `passing_timing_links` now adds
an explicit many-to-many association to event, passing cell, cached CrossMgr
passing ID (nullable for visual-only riders), clip, physical/evidence subject,
and candidate bib. Race start, camera-minus-CM offset and identity-confirmation
state at linking are saved as snapshots. Identity confirmation is not timing
approval; `operator_timing_reviewed` remains false and no CMN/read is changed.

Links are created when a job is requested, including reuse of a cached result.
The `passing_timing_results` SQL view derives full-precision integer nanosecond
race time from the saved crossing report, offset and start; a queued job becomes
queryable on completion even if the GUI has closed. Missing/interrupted-frame
brackets retain bounds with NULL estimate, never an invented timestamp. Source
frame wheel positions remain in the referenced analysis JSON. Whole seconds in
the left overlay do not round the stored evidence.

`passings.compare_event` exposes `cell.video_timings` for linked current-context
candidates, without overwriting original CrossMgr or visual passing timestamps.
A changed clock offset/start leaves previous link snapshots available as history;
stale-start results are flagged and excluded from current model results, as are
links using a different offset. Evidence keys must agree: clip/bib similarity
alone cannot attach another bike. Multiple possible passing associations are
left unlinked by the automatic cached-result helper.

`tools/link_cached_timings.py --db PATH` previews associations using current
source evidence. `--apply` adds only link metadata for unambiguous entries; it
retains older analysis reports, footage and reviews. It was used on zbook9 to
associate available existing measurements. Restart the app to load automatic
linking on subsequent review. Tests cover queued-to-complete persistence,
cache reuse, nanosecond offset calculation, NULL estimates for gaps, wrong bib
rejection, ambiguous evidence and stale clock contexts. 189 unit tests pass on
both hosts; GUI testing also verifies a real database link after a result arrives.

Example query:

```sql
SELECT cell_key, bib, clip_id, race_elapsed_ns, before_race_ns,
       after_race_ns, before_ordinal, first_after_ordinal, bracket_ns
FROM passing_timing_results
WHERE event_id = 1 AND bib = '100';
```

### Worker progress and queue messages

Observed zbook9 jobs were progressing normally: recent uncached jobs completed
in approximately 15–33 seconds. Analysis is serialized per database, so a newly
selected rider may wait for the previous clip; revisiting an identical measured
track reuses its cached analysis.

Workers now publish a stage (`Finding motion track`, `Loading bicycle detector`,
`Measuring wheels`) and processed/total frame count with a roughly one-second
heartbeat, including through rejected measurements. The GUI identifies the
active clip and frame progress for both its own job and the preceding job it
is waiting on. It does not imply that a queued/running job already has a timing
result. Final reports retain completion duration/frame counts and original
measurement evidence; the inference/cache algorithm is unchanged.

191 unit tests plus GUI checks pass on both hosts. A worker lifecycle test
observes live progress from a second connection and verifies the passing link
survives completion. Reopening RaceVideo loads the clearer status labels;
already-started jobs continue using their original worker code.
