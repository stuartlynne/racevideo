# Camera bib observation and CrossMgr integration plan

Recorded: 2026-11-01. Target: field trials during the Spring series starting in
March 2027, assuming the coming Spring series is intended. Exact event dates
remain to be confirmed. The identified race laptop is a ZBook with an
i7-12850HX and 32 GB DDR5; previous component benchmarks used the i7-14700K desktop.

Updated 2026-11-02: prioritize an unattended motion-triggered recorder and concurrent
operator review interface. Add OCR as an independent consumer of captured events.

## Implementation status: 2026-11-04

Capture and motion analysis now run in separate processes, with a bounded shared
ring and latest-only preview decoder process. GUI latency/backlog instrumentation
and synthetic backlog/overrun tests are implemented; see [architecture](ARCHITECTURE.md).

Daily review now includes Today/date browsing, bib candidate filters, source
sightings/intervals, original-pixel zoom/pan, persistent stars and protected,
confirmed date cleanup. See [review guide](REVIEW.md).

The initial implementation now lives in this repository. See [README](README.md)
for running instructions and [development notes](NOTES.md) for the tested webcam,
scope, and next steps. Motion ROI editing and capture are now implemented with
0.5s pre-roll, 0.2s quiet-gap tolerance and 2s post-roll. Capability-driven camera
controls and readback are also implemented; cat-wheel clip #109 produced useful
OCR from manually located crops (see development notes). An initial automatic
on-demand OCR worker and review controls are now implemented; automatic results
are candidates with known errors. A persistent MCP service, outward GUI bridge,
offline recording inspection and measured camera-control trials are now implemented
(see [service guide](MCP_SERVICE.md)). Race integration remains future work. The roadmap below is broader than the implemented prototype.
Original video/OCR evidence remains in the parent `sprinttimer` workspace; its
relative links therefore require that workspace. Camera suggestions and prices
are the previously recorded research, not a fresh availability check.

## Purpose

Produce an additional source of rider-passage evidence when RFID is missing or
inconsistent. Identify three-digit bibs on roughly 2 × 4 inch seatpost plates,
attach capture timestamps, and provide evidence to a reviewing agent through a
durable event stream. The agent can compare observations with CrossMgr's expected
passings and propose or apply explicitly provisional estimates under the event's
configured policy.

Typical failures to help resolve include lost tags, incorrectly programmed tags,
the wrong tag being used, and tags obscured by other bicycles. RFID remains the
primary source. A missed camera identification is acceptable; a confidently
incorrect identification is the more consequential failure.

Modern cameras, CPUs and native video libraries make this worth revisiting after
earlier attempts around a decade ago. Current tests demonstrate readable plate
images and practical crop-level OCR costs. They do not yet establish reliable
identification of whole bunches or accurate finish times.

## Event identity and RFID corroboration

RaceDB/CrossMgr integration must resolve observations through event entries:
one participant may race Single-speed and Intermediate on the same date using
different bibs and possibly the same EPC. Date alone does not scope bib identity.
Cache source-qualified event/entry/person references and assignment history;
keep raw OCR bib/video matches distinct from RFID EPCs. Future per-rider badges
should distinguish independently correlated OCR+RFID, OCR only, RFID only,
awaiting/incomplete RFID coverage, and ambiguous/conflicting evidence. An OCR
provisional read echoed through CrossMgr cannot corroborate its own source.
See [INTEGRATION.md](INTEGRATION.md) for the model and staged implementation.

## Requirements and boundaries

- One camera initially, with a preview, configurable finish-area region, camera
  settings, and visible capture/processing health.
- Approximately two CPU cores on a 12th-generation i7 class race laptop, alongside
  CrossMgr. Python orchestration with native processing libraries is the initial
  implementation choice. Profile before introducing custom compiled code.
- Useful observation delivery within 10–30 seconds of the passage. Preserve the
  original capture time regardless of processing delay.
- Approximately 100–150 participants on the start list; size the workload for
  dense bunches and riders per second, not just total entrants.
- Local capture and observation logging must continue without Internet or an
  available reviewing agent. Running a large local language model is outside
  the proposed two-core vision budget.
- Optional JPEG evidence for debug/review, with bounded retention and disk use.
- Linux USB/UVC capture first. Confirm the actual race laptop OS before building
  deployment tooling; keep capture and camera-control backends replaceable.

## Recorder and concurrent review workflow

The first usable product should be a Linux counterpart to the described
SprintTimer Video Finish workflow, with recording and review operating concurrently.
SprintTimer's [product page](https://appmaker.se/home/sprinttimer/) describes
motion-activated video finish and saving a small number of frames per passing.
Our proposed recorder should preserve full-rate motion-event clips, including
pre-trigger and post-trigger context, rather than reproduce that sparse-frame
behavior. The supplied exports remain useful replay fixtures but cannot recover
frames that the phone did not save.

The operator workflow:

1. Start the recorder and GUI. The GUI opens in Live view, showing capture health,
   camera time, recording state and storage status.
2. Show a yellow motion-detection rectangle over the preview. Move it by dragging
   its interior and resize it with corner/edge handles. Save coordinates relative
   to the original image, independent of preview scaling or letterboxing.
3. Keep a compressed rolling buffer while monitoring motion inside that rectangle.
   On a trigger, begin an event with buffered frames from before the trigger;
   continue recording through movement and a short quiet period afterward.
4. Publish completed events as timestamped files and thumbnail entries along the
   bottom. Labels include capture start time, duration and event/processing status.
5. Clicking a thumbnail switches the main view to replay without stopping capture.
   Provide pause, frame stepping, scrubbing, playback speed, image magnification
   and explicit Return to Live. New thumbnails arrive without interrupting replay.
6. Allow manual event capture or Save Recent Buffer when automatic motion detection
   misses something, and allow flags/notes for later review.

Initial tuning values might be two seconds of pre-trigger video and two seconds
after the last motion, but these are starting assumptions to test. Use trigger
debouncing, separate start/stop thresholds, and event merging so a brief gap
between riders does not create many tiny clips. For persistent motion, split
long recordings at a configured duration/size while retaining event continuity.
Record ROI changes, stream interruptions and actual timestamp discontinuities.

Test camera placement around three feet above ground at the finish line, as
proposed. Confirm plate visibility, focus across the course, and occlusion by
nearer bicycles before fixing the geometry. The motion ROI and the larger region
used for rider/plate tracking need not be identical. A narrow trigger region
must not discard useful adjacent frames or riders elsewhere in the full image.

### Process responsibilities

Use separate processes within one project, with a simple launcher for the operator:

| Process | Responsibilities |
| --- | --- |
| Recorder service | Sole owner of the camera; settings, timestamps, compressed buffer, motion triggers, clip writing and event index |
| Review GUI | Live preview or replay, draggable ROI, settings controls, thumbnail strip and annotations |
| Optional OCR worker | Read events/selected frames, detect/track plates, publish bib observations and review images |

The GUI sends control requests to the recorder and reads its status; it does not
open a second competing camera connection. Closing or crashing the GUI must not
stop an already-running recording service. OCR failure must not stop recording.
Preview delivery should use a latest-frame queue so a slow GUI cannot accumulate
a backlog or block capture. Separate playback resources from the live decoder.

Tkinter/ttk is a reasonable initial GUI choice, using a Canvas for the image and
mouse-editable overlay. Keep decoding, recording and OCR outside its event loop;
marshal GUI updates onto the GUI thread. A modest preview refresh rate can coexist
with full-rate recording. Evaluate Qt only if measured playback/scrubbing/display
requirements exceed the Tk implementation. Do not make the media engine depend
on the GUI toolkit. See [Tkinter's threading model](https://docs.python.org/3/library/tkinter.html#threading-model).

### Media and storage

Retain the camera's compressed MJPEG packets where practical, buffering and muxing
without re-encoding. Decode only the frames needed for motion detection, preview,
playback and OCR. MJPEG images are independently decodable, which simplifies
pre-trigger selection compared with inter-frame video. Actual recording/container
support and timestamp preservation must be tested with the chosen media backend.

Compare GStreamer and FFmpeg/PyAV for the capture/buffer/writer implementation.
[FFmpeg streamcopy](https://ffmpeg.org/ffmpeg.html#Streamcopy) avoids decode/encode
work for compatible recording paths. [GStreamer splitmuxsink](https://gstreamer.freedesktop.org/documentation/multifile/splitmuxsink.html)
supports segmented recording and asynchronous finalization, with keyframe/GOP
constraints; it is a building block, not a complete motion/pre-trigger recorder.

Write clips to temporary paths and publish them to the event index only after
successful finalization. In the first version, replay completed events while
recording the next event; label an active event as recording. Review of an event
that is still recording can later use finalized rolling chunks rather than
assuming an unfinished MP4 is seekable. Keep clip-relative PTS and an absolute
capture-time mapping in sidecar metadata; filenames alone cannot supply timing.
Show capture times during replay without permanently burning text into originals.

Measure actual MJPEG bytes per second and buffer memory on the selected camera.
Long busy periods can create substantial files. Retention, low-disk alarms and
disk-full behavior are essential; a later archive transcode must preserve the
original timing/evidence relationship and fit the resource budget. Avoid writing
every full video frame as a separate JPEG file. Generate review thumbnails and
selected debug crops asynchronously.

### OCR insertion points

Begin by processing finalized event clips. Later, process selected frames during
an event when needed to meet the 10–30 second observation target, and provide an
operator-requested re-analysis of a clip or crop. All modes should share one
recognition pipeline and preserve source event/frame identities. Offline replay
must not publish duplicate live observations or race edits.

Recorder/review acceptance should first demonstrate simultaneous acquisition and
playback, reliable pre/post-trigger coverage, usable frame stepping/timestamps,
ROI persistence, bounded CPU/memory/disk use, GUI reconnect, camera recovery and
correct behavior through long bunches and brief gaps. OCR accuracy is a separate
acceptance gate; the recorder can be useful before that gate is met.

## Existing footage and observations

The supplied iPhone 14 SprintTimer exports are H.264 portrait 1080 × 1920 files.
Their nominal rate is 60 fps, but the saved frames occur in bursts with large
presentation-timestamp gaps. Extract actual frames and preserve timestamps;
do not synthesize repeated frames or derive time as frame number divided by 60.

| Source MOV | Decoded frames | Confirmed OCR examples in verified appearance order |
| --- | ---: | --- |
| VF261101131607.mov | 123 | 213, 233, 203, 227 |
| VF261101132158.mov | 160 | 469, 461, 432 |
| VF261101141429.mov | 127 | No complete number confirmed in this pass |

Across all 410 decoded frames, the final exploratory scan produced 95 OCR
observations and 62 distinct video/number candidates; 15 candidates appeared in
multiple frames. These counts include false positives and wrong digits, not
identified riders. Seven matching examples were visually checked. Precision
and recall have not been measured against a complete annotation.

Important findings:

- Some plate regions were only about 25–45 pixels wide. More original pixels on
  the plate, better viewing geometry, and short exposure are likely to help.
  Upscaling an existing crop does not recover missing detail.
- Gravel, clothing logos, background objects, and helmets generated numbers.
  One helmet produced 774 at confidence 82; a 227 plate produced 220 at 83.
  Tesseract confidence is not a calibrated probability of a correct bib.
- Plate 461 generated conflicting readings including 467. Nearby frames can
  resolve ambiguity, but repeated errors can also agree with one another.
- Plate 239 is visually readable in the first clip but was missed as a correct
  number in the final OCR configuration. Lack of an OCR result is not evidence
  that a rider was absent.
- The current grouping is by number across an entire clip, not by tracked rider.
  For the delivered CSVs, a clothing-logo detection of 227 and a misread 239 as
  233 were excluded before computing the accepted timing/order.
- The supplied files do not demonstrate the iPhone's full capture capability:
  Apple specifies 4K/60 support. SprintTimer capture/export settings need checking
  before attributing the resolution limit to the phone.

Local evidence:

- [Current scanner](../scan_plates.py) and [run instructions](../README.md).
- [Verified example crops](../analysis/verified-examples.jpg),
  [verified examples](../analysis/verified_examples.csv), and
  [raw OCR observations](../analysis/readings.csv).
- Delivered [first clip CSV](../VF261101131607.csv),
  [second clip CSV](../VF261101132158.csv), and
  [third clip CSV](../VF261101141429.csv).
- [Run summary](docs/evidence/run-info.json) and per-video metadata in `analysis/`.

CSV order means first verified observation in the image, not measured finish
order. A plate may be hidden until after its rider has passed another rider.

## Two camera suggestions

Prices below were observed during the 2026-11-01 discussion and are purchase
leads, not guaranteed delivered prices. Neither option has been physically tested.

| | Preferred 4K trial camera | Global shutter comparison camera |
| --- | --- | --- |
| Model | ELP-U3CAM4K60-IB(5-50B) | Arducam B0495C, enclosed version |
| Sensor | 1/1.8 inch Sony IMX678, rolling shutter | 1/2.6 inch AR0234, global shutter |
| Documented USB 3 output | 3840 × 2160 MJPEG at 60 fps; YUY2 at 23 fps | 1920 × 1200 YUY2 at 50 fps; 960 × 600 at 80 fps |
| Lens | Interchangeable CS mount, manual 5–50 mm varifocal lens | Stock M12 manual-focus wide lens; narrower lens likely needed |
| Packaging | Aluminium box, standard 1/4 inch tripod mounting; supplier shows a screw-secured USB cable | Enclosed option with back cover and tripod adapter |
| Price observed | C$224.35 before tax on Amazon.ca, import-fee deposit included in displayed price | US$154.99 on Arducam, before shipping, tax and any replacement lens |
| Main reason to test | More pixels on small plates and flexible optical framing | Eliminate rolling-shutter skew and compare passage tracking |
| Main reservation | Minimum manual exposure time not documented in the reviewed specifications | Lower resolution and wide stock lens reduce pixels on plates |

The ELP is the first choice for this experiment because framing and small-digit
detail were immediate limitations in the supplied footage. Global shutter does
not eliminate motion blur from a long exposure; both cameras need suitable
exposure and focus. Confirm the exact lens and enclosure variant when ordering.
The Arducam documentation has differing stock-lens specifications between its
product page and older datasheet, so do not design framing around that lens
without confirming the shipped part.

Sources:

- [ELP Canadian listing](https://www.amazon.ca/dp/B0GKGYNDWC).
- [ELP manufacturer specifications](https://www.elpcctv.com/elp-4k-60fps-usb30-camera-large-sensor-imx678-webcam-with-cs-550mm-lens-manual-10x-optical-zoom-p-712.html).
- [ELP supplier housing and cable details](https://www.hdusbcameras.com/elp-new-4k-60fps-webcam-usb-30-imx678-low-light-streaming-camera-with-10x-zoom-5-50mm-lens-for-pc-cctv-video-conference-ai.html).
- [Arducam enclosed B0495C](https://www.arducam.com/arducam-2-3mp-ar0234-color-global-shutter-usb-3-0-camera-module-with-enclosure.html).
- [Arducam B0495 datasheet](https://www.arducam.com/downloads/datasheet/B0495_AR0234_Global_Shutter_USB3.0_Camera_Module_Datasheet.pdf).
- [iPhone 14 specifications](https://support.apple.com/en-us/111850).

No weatherproof or impact rating was established for these enclosures. Use a
rain/mud shelter, cable strain relief, and secure lens adjustments. A large lens
housing alone does not establish light gathering: check aperture, lens coverage,
and real images at the intended short exposure. The phone's main lens is f/1.5.

Camera acceptance should verify Linux enumeration, actual sustained frame modes,
manual exposure/gain range, setting readback, disconnect recovery, and image
quality. Test around 1/2000–1/4000 second in daylight where supported and adequately
exposed; use observations to choose an operating range rather than assuming it.

## Capture and processing design

Proposed flow:

```text
USB camera → timestamped compressed frame buffer → reduced-resolution passage detection
           → plate detection and tracking → selected original-resolution crops
           → OCR alternatives and passage consensus → durable observation stream
           → CrossMgr context and RFID reconciliation → provisional decision
```

Capture directly from the camera and provide a preview. Desktop screen capture
is unnecessary for the intended USB installation. Separate capture from OCR so
slow recognition cannot stall acquisition.

Use a configured finish-area region and inexpensive motion/passage detection.
Start with simple plate geometry, then introduce a compact trained detector if
needed to reject non-plate objects. Maintain a track identity distinct from the
recognized number. Select a few clear views per track by sharpness, plate size,
clipping, angle and occlusion. Retain competing OCR readings and an explicit
unknown outcome. Preserve leading zeroes by storing bibs as strings.

Do not merge different laps simply because they share a bib. Do not count several
preprocessing variants of one image as independent observations. Tune frame
sampling against actual passage durations and use the compressed buffer for
retrospective selection when a passage is detected late.

Start with Python, OpenCV/FFmpeg and an in-process OCR engine. Evaluate a compact
ONNX plate/digit model if the baseline detector or Tesseract limits accuracy.
Native-library thread counts, worker count and process CPU limits must be
explicit; library defaults can otherwise consume the whole laptop.

## Timing and event contract

An observation should include:

- Schema version, stable event ID, replay cursor, race/session ID, camera ID,
  and passage/track ID.
- First/last capture times, original monotonic/device timestamp and its source,
  mapped UTC time, and result-emission time.
- Bib alternatives and uncalibrated OCR scores, independent supporting frames,
  quality/rejection reasons, and start-list match as a separate field.
- Optional crossing-time estimate with uncertainty and method. Leave it absent
  when the images do not support it.
- Source frame references, optional crop/context JPEG paths, camera settings,
  model/configuration versions, and any capture or processing gaps.

A plate observation is not the front-wheel crossing instant. Establish camera
geometry, line position, clock alignment with RFID/CrossMgr, transport delay,
and the camera's timestamp semantics. Keep capture time separate from receipt
and emission time. Driver timestamps are not automatically exposure timestamps.
See the [V4L2 buffer documentation](https://docs.kernel.org/userspace-api/media/v4l/buffer.html).

Use a durable local log, for example SQLite with cursor-based polling and JSONL
export. Deliver at least once with stable IDs and consumer deduplication. Later
interpretations should reference/supersede earlier events without erasing the
original image evidence. Agent outages must not lose observations.

## CrossMgr and RFID reconciliation

Keep the camera service separate from CrossMgr's GUI thread. The other Codex owns
`crossmgr_mcp` and the in-process bridge; agree on an observation schema and adapter
without duplicating or modifying its work here.

The checked local [CrossMgr service documentation](../../whiskey/crossmgr_mcp/SERVICE.md)
describes `reads.wait`, `rider.get`, and `rider.edit.preview/apply` with `add_estimate`.
These are integration leads from the checkout, not a claim of physical-event
validation or a completed autonomous camera adapter. Verify contracts again
when integration starts.

Matching cases to support:

1. A rider is predicted near this time, RFID is absent, and a camera track supports
   that bib: create a candidate missed-passing case.
2. A start-list bib repeatedly appears with plausible category/lap context but
   has no RFID evidence: build a persistent missing-tag case across laps.
3. RFID and camera agree: retain corroboration without adding another passing.
4. A delayed RFID read arrives after a provisional estimate: link the evidence
   and reconcile the estimate rather than double-counting a lap.
5. Camera and RFID disagree: flag possible misread, bad tag mapping, or wrong tag;
   do not automatically rewrite a tag mapping from ambiguous images.

Predictions and start-list membership are contextual evidence, not proof of an
image interpretation. Preserve the unconstrained OCR alternatives so the expected
bib does not become a self-confirming answer. Category proximity and repeated
laps strengthen a case but cannot establish identity alone.

Store camera observations, reconciliation decisions and provisional race edits
as distinct records. Do not fabricate EPCs or present optical evidence as a raw
RFID read. Bind decisions to an exact race and rider revision; use idempotent
commands and reconcile uncertain outcomes instead of blindly replaying a write.
Translate timestamps to CrossMgr's rider-elapsed coordinates, including starts,
restarts and TT offsets where applicable. Reset/rebind context on race changes.

The initial field trial should operate in shadow mode. Enable provisional edits
only after testing the chosen authorization policy, provenance, duplicate/late
read handling, and targeted correction of an incorrect estimate. Account for
CrossMgr's configured live publishing when testing edits.

## Camera settings and review evidence

Use OCR success as one signal alongside plate contrast, clipping, blur, size and
agreement across a track. Measure success against detected rider passages as well
as detected plates; otherwise a detector that misses plates can look successful.
An empty course must not trigger a setting change.

Bound exposure to a range that preserves moving digits, then adjust supported
gain/exposure controls conservatively over several passages. Apply one change
at a time, allow settling, record settings with the frames, and revert changes
that degrade the quality measurements. Keep an operator lock and manual override.
Focus, zoom and iris on a manual lens are physical adjustments, not assumed
software controls. Camera capability discovery must precede any control loop.
See the [V4L2 camera controls](https://docs.kernel.org/userspace-api/media/v4l/ext-ctrls-camera.html).

Debug modes should select no images, accepted observations, uncertain passages,
or all passages. Save original-resolution crops and selected contextual JPEGs
with sidecar metadata. Use asynchronous bounded writes, retention limits and
disk-full reporting. Short compressed clips are useful for crowded/ambiguous
passages where a single crop hides the tracking problem.

## CPU and latency evidence

The [component benchmark](docs/evidence/cpu-feasibility-benchmark.json) ran on the
local i7-14700K desktop, pinned to logical CPUs 0 and 2, representing two separate
physical performance cores on this host. It is not a 12th-generation laptop test.

| Measurement | Result |
| --- | ---: |
| Existing saved candidate regions | 86 |
| OCR calls, four variants per region | 344 |
| Two-worker elapsed OCR time | 1.599 s |
| Total worker CPU time | 2.759 CPU-seconds |
| CPU cost per region, including four OCR variants | 32.08 ms |
| Synthetic 4K JPEG full decode | About 16–20 ms/frame |
| Synthetic 4K JPEG quarter-dimension decode | About 8.63 ms/frame |

OCR inputs were previously detected small crops, not an unbiased sample of all
candidate regions or native 4K crops. Decode used an upscaled existing image
encoded as JPEG, not an actual camera stream. Measurements exclude live capture,
plate detection/tracking, GUI load and agent processing. JPEG cost depends on
image content and quality.

Full decoding at 60 fps could consume about 0.96–1.20 CPU cores before OCR.
Even reduced decoding of every frame has a cost. Benchmark selective decoding,
motion gating and candidate scheduling rather than assuming downscaling is free.
For illustration only, 150 riders × three crop evaluations × 32.08 ms is about
14.4 CPU-seconds of OCR. This is not an end-to-end latency prediction.

Track queue age, CPU time, memory, disk use, dropped frames and recovery after
bunches. Keep acquisition continuous with bounded work queues. Under overload,
retain evidence and explicitly report skipped/late work instead of silently
losing passages. Extra allowed latency absorbs bursts only when average demand
remains below processing capacity. Reserve headroom for CrossMgr and test laptop
power modes, thermal throttling and performance versus efficiency cores.

## Development and field trial stages

Dates are planning windows, not commitments or confirmed race dates.

| Window | Work | Completion evidence |
| --- | --- | --- |
| November–December 2026 | Preserve baseline; annotate every rider passage and visible plate in the supplied clips; agree stream schema with CrossMgr work | Separate detection misses, unreadable plates, wrong IDs and timing uncertainty; reproducible replay fixtures |
| December 2026–January 2027 | Acquire/test one enclosed camera; build recorder service and Tk review GUI with editable motion ROI, pre/post-trigger clips and thumbnail playback | Real sustained capture modes, usable short exposure, timestamp calibration, concurrent recording/review, GUI reconnect, disconnect and disk-full tests |
| January–February 2027 | Implement passage tracking, crop selection, OCR consensus and durable stream; test start-list matching | Measured precision/recall, duplicates, unknown rate, latency and resource usage against annotations |
| February 2027 | Run paced replay and real bicycle passes on the actual laptop, alongside CrossMgr; integrate in a disposable race | Two-core budget test, bunch backlog recovery, race context/clock mapping, late RFID and incorrect-estimate correction |
| March 2027 Spring series | Run in shadow mode; review with RFID and manual observations; consider a limited provisional workflow after acceptance | Saved cases, false positives/misses, timing errors and operational issues from actual race conditions |

Measure capture-to-result latency at median, 95th percentile, maximum, and by bunch
size; target useful results within 10–30 seconds and explicitly report exceptions.
Measure identification precision and recall separately for visibly readable
plates and all rider passages. Do not promise a numerical accuracy threshold until
the annotation/replay results support one and an event policy is agreed.

Field tests should include side-by-side bikes, obscured plates, dirty/tilted
labels, strong sun, shade/cloud changes, spectators/logos, repeated laps, known
missing tags, conflicting tag mappings, delayed reads, restart and agent outage.

## First implementation milestone

Inspect existing CrossMgrVideo before deciding how much of the review UI to
rebuild; the source comparison below identifies overlap and scaling limitations.

Build the recorder service and concurrent review GUI first, with a replay input
that allows the current MOVs to exercise the UI and event logic before camera
hardware is available. Their sparse timestamps cannot validate continuous-camera
pre-trigger coverage or throughput; use continuous test recordings for that gate.
Add passage tracking, selected-crop OCR, JSONL/SQLite observations, debug JPEGs and
timing/resource metrics as an independent worker, followed by camera autotuning
and CrossMgr reconciliation. Keep this experiment's original MOVs, baseline
outputs and manual review evidence intact so improvements can be measured.

## CrossMgrVideo source comparison 2026-11-02

Reviewed the local `CrossMgr` symlink to `/home/sl/work25/crossmgr/CrossMgr`.
The checkout identifies CrossMgrVideo as `3.0.63-private`; its root HEAD is
`84c39fb0`. The latest local history entry under CrossMgrVideo is `a87d32a7`
(2025-03-07, removal of a deprecated cgi dependency). This is a local-checkout
assessment, not verification of current GitHub HEAD. No CrossMgr code was changed
and no camera or GUI was started for this review.

### Existing functionality worth retaining

- Continuous USB capture using OpenCV, configurable resolution/fps/FourCC and
  actual-fps reporting. MJPG is the GUI default, and the resolution list includes
  4K; it is not restricted in code to old low-resolution cameras.
- Timestamped JPEG circular buffering. `CamServer.py` currently allocates
  `configured_fps × 8` frames. QuickStart documentation describes ten seconds,
  so code and documentation differ; actual temporal coverage depends on delivery.
- Save a configurable interval around a trigger, or only the nearest one/two
  frames. Defaults are 0.5 seconds before and 2 seconds after a trigger.
- Standalone snapshot, timed Auto Capture and press/release Capture, with keyboard
  and joystick controls. Auto Capture here means a configured time window after
  a manual/external trigger; it is not automatic motion detection.
- wxPython live preview, replay, frame stepping, image zoom, finish-strip review,
  saved review positions, annotations and optional MP4 export.
- SQLite storage of per-frame timestamps/JPEG BLOBs and separate trigger metadata,
  plus browser review through the built-in web server. Normal background capture
  is separate from review work, although starting manual Capture stops the photo
  panel's current playback.

Useful entry points: [CamServer](../CrossMgr/CrossMgrVideo/CamServer.py),
[circular buffer](../CrossMgr/CrossMgrVideo/FrameCircBuf.py),
[review UI and request handling](../CrossMgr/CrossMgrVideo/MainWin.py),
[photo playback/export](../CrossMgr/CrossMgrVideo/PhotoDialog.py),
[storage](../CrossMgr/CrossMgrVideo/Database.py), and
[QuickStart](../CrossMgr/CrossMgrVideo/helptxt/QuickStart.md).

### CrossMgr trigger path

CrossMgr's `MainWin.handleChipReaderEvent` maps incoming tags to bibs and calls
`SendPhotoRequests` when the race is running and the camera feature is enabled.
`processNumTimes` also requests photos for eligible entered passings, including
manual input. Requests contain the expected bib, race time, absolute timestamp,
race/category metadata and a configurable timing advance.

The active sender is [SendPhotoRequests.py](../CrossMgr/SendPhotoRequests.py) using
[MultiCast.py](../CrossMgr/MultiCast.py): UDP multicast group `225.3.14.15`, port
`10083`. CrossMgrVideo's `SocketListener` queues the request and `processRequests`
asks the camera server for buffered and subsequent frames around the trigger.
The legacy `CrossMgrVideo/Client.py` contains a TCP sample; it is not the current
multicast path and should not be copied as the integration contract.

Consequently, automated capture can miss an isolated rider when no bib/RFID trigger
arrives. A nearby rider's trigger might incidentally preserve that rider, and
manual capture can preserve them too. Motion must be an independent trigger for
our missing-RFID use case. Retain RFID requests as additional capture/annotation
inputs, attaching multiple trigger reasons to overlapping footage.

### Changes needed for the proposed installation

1. Add image-motion detection and an editable ROI; none was found in the capture
   path. GUI mouse-motion handlers are unrelated to scene movement.
2. Separate recorder lifetime from GUI lifetime. Existing camera, event and DB
   workers are threads inside the wx application; closing the GUI shuts them down.
3. Establish a verified compressed capture path. The normal `cap.read()` path
   returns decoded frames, then `CVUtil.toJpeg` encodes them with `simplejpeg`.
   The helper can pass encoded JPEG buffers through, but the capture setup does
   not explicitly request raw encoded output or disable colour conversion.
   Selecting MJPG as the camera format does not itself prove decode-free buffering.
4. Bound memory by bytes. `CVUtil.jpegToFrame` caches up to 3,600 decoded frames.
   At 3840 × 2160 × 3 bytes, that could approach 90 GB of image data if filled
   with distinct 4K frames, before other caches/objects. This is a potential limit,
   not a measured allocation; it is unsuitable unchanged for a 32 GB laptop.
5. Add exposure/gain discovery, controls and readback. The camera setup currently
   configures FourCC, width, height and fps. Its Focus command opens a larger
   preview for manual focusing; it does not drive a motorized lens.
6. Improve timing provenance. Frames receive `datetime.now()` after `cap.read()`;
   capture latency is initialized to zero. Network correction uses recent
   sender/receiver wall-clock differences, which also include network delay.
   Preserve device/host clocks and calibrate rather than treating these values
   as measured exposure or crossing timestamps.
7. Choose the recording contract explicitly. Current storage is timestamped JPEGs
   in SQLite, not a timestamped video file per motion event. MP4 is an export
   operation that re-encodes at an inferred constant frame rate. Keep authoritative
   original frame timestamps when adding ordinary clip files.

Recommendation: reuse the trigger semantics, interval merging, review concepts
and race metadata. Evaluate the existing wx review UI before rebuilding it in Tk.
A motion-trigger prototype could extend the present request queue, but a reliable
4K recorder needs the capture, memory and process-lifetime changes above. Compare
that refactor with a new recorder service and a compatible trigger adapter; do
not assume either a complete rewrite or a small camera-resolution change is required.

## Follow-up from wheel testing, 2026-11-05

- Implement and validate horizontal, vertical and upside-down label handling.
  Preserve ambiguous bib hypotheses (including 609/906 when both are entered);
  see INTEGRATION.md for event-scoped evidence and review requirements.
- Compare the restricted top-wheel, upright-only fixture test against the normal
  dual-orientation scan. Restore normal orientation handling before race trials.

## GPU OCR next step

Integrate a resident, isolated PaddleOCR PP-OCRv5 mobile GPU worker via the
existing OCR job contract. Native GPU comparison on zbook9 is recorded in
GPU_OCR.md. Keep raw/normalized hypotheses, per-frame timestamps and provenance;
bound memory/queues and retain previous results. Validate sustained recording/GUI
latency, orientation handling and real race-speed false reads before changing
passing semantics. Keep DIN synthetic training optional until this baseline has
been evaluated; supplied font is Mittelschrift rather than confirmed Engschrift.

The first best-view GPU prototype is implemented in tools/best_frame_ocr.py and
racevideo/plate_selection.py. Native trial evidence and limitations are in
GPU_OCR.md. Connect this path to the app/MCP job interface only after retaining
experimental provenance, bounded execution and explicit engine selection.

Encounter identity: repeated visits by the same bib are independent OCR targets,
each with its own selected frames, timestamps and hypotheses. Never collapse
these into one per-clip bib result. Close on exit/expiry, bridge only short misses
within a traversal, and preserve continuity across linked chunk boundaries when
connecting the experimental worker to production.

## Sunday November8 field trial

See [SUNDAY_TRIAL.md](SUNDAY_TRIAL.md). This is an observational cyclocross
trial with LTE-assisted Codex testing; it will not supply race scoring. Preserve
local recordings through connection loss. Compare dim-light shutter compromises,
near/far focus and real passing-level OCR. Keep faster March–June road finishes
as a distinct validation target.

Synthetic label provenance: LABEL_RENDERING.md records the inspected qllabels
font choice and digit stretching. Resolve the earlier Mittelschrift/Engschrift
assumption against the actual generating deployment or saved label masters
before claiming an exact production-font training set.

Body bibs: include the larger102x152 (~4×6in) layout alongside62x100 Frame
left/right layouts in training/validation. Same stretched digit renderer,
different proportions and side-text layout. Keep frameplates primary; body bibs
are opportunistic because placement/visibility is unreliable. Preserve both
label tracks but correlate co-visible frame/body evidence before counting rider
passings; a second label must not create a second passing. Actual rendering
masters and provenance are documented in LABEL_RENDERING.md.

First recognizer fine-tuning experiment completed on the A1000; see TRAINING.md.
It fits the GPU, but synthetic-only tuning did not improve the existing real-video
baseline. Keep the original Paddle model; future tuning should use labelled field
examples and frozen normalization statistics for small batches.
