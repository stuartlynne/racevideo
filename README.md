# RaceVideo

Linux webcam recording and concurrent review. Opens in Live and saves motion
events with **0.5 seconds before detection**, a configured two-second post-roll
and a **one-second quiet-tail limit** by default. Set `--quiet-close 0` to retain
the full post-roll. Maintenance → Motion quiet-tail limit changes the limit for
future GUI recorder starts; existing video is unchanged.
Capture continues while reviewing older clips, and after closing the review window.

The recorder preserves the camera's original MJPEG frames in SQLite. No video
recompression and no FFmpeg command-line subprocess are required. PyAV provides
FFmpeg's native V4L2 capture; Pillow handles preview/thumbnail decoding; Tk handles
the interface. This version requires a camera with **MJPEG** output.

An optional [rider appearance experiment](APPEARANCE_RECOGNITION.md) adds image
comparisons and top-three bib suggestions to archived passings. It runs separately
on CPU and preserves operator confirmations and race times.

## Agent service

The independent [racevideo_mcp service](MCP_SERVICE.md) exposes saved recordings,
OCR evidence, fresh camera samples, verified settings changes, bounded camera
trials and GUI control over authenticated MCP HTTP. The app connects outward on
the same TCP port and shows **MCP linked**. It remains usable without the service.

```sh
.venv/bin/pip install -e '.[ocr,mcp]'
.venv/bin/racevideo-mcp-install-service --db "$PWD/data/racevideo.sqlite3" --enable --start
.venv/bin/racevideo-tool call racevideo.inventory
```

Default MCP URL: `http://127.0.0.1:8766/mcp`. Credentials are private files under
`~/.config/racevideo-mcp/`. See the service guide for client setup, tools, command
reconciliation and operator takeover. Saved-video access works with no GUI open.

## Race laptop

zbook9 is installed with a separate recording store and a review-first desktop
launcher. See [installation, measured checks and camera-arrival checklist](ZBOOK9.md).
A reusable user launcher/service installer is `tools/install_user.py`.

## Event passings review

**Event passings…** opens a competition/event/category lap chart comparing cached
CrossMgr passings with visual bib evidence. Green cells have bib/time matches;
yellow cells need visual review; red cells show outside-roster visual candidates.
Click a cell to review a matching or nearby capture. See
[passings review and MCP configuration](PASSINGS_REVIEW.md).

The main video also offers one-click confirmation of a selected passing's suggested
bib, previous/next bike navigation and estimated passage counts. **Find bikes**
indexes older footage; new neural OCR reuses its bike detector automatically.
**Motion / storage…** selects zone behavior and non-destructive trim proposals.
See [Sunday's motion/storage experiments](MOTION_STORAGE_TRIAL.md).

## Run

Python 3.11+ with Tk and a working Linux video device are required. On Debian/Ubuntu,
install `python3-tk` and `python3-venv` if missing. Then:

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
./run.sh
```

The current workspace already has its environment installed. Default camera:
`/dev/video0`, 1280×720, requested 30 fps. Actual fps is shown in the status bar.
The test Logitech C615 initially delivered 14–15 fps, and later approximately
29–30 fps. These are observed rates under different test conditions.
The Camera button discovers and adjusts the controls exposed by the device.
It also lists advertised MJPEG capture modes. Stop recording, select a mode,
click **Use mode**, then start recording; compare requested, driver and measured
rates in the panel. Mode selection persists. New clips retain mode/rate/gap
diagnostics, and review displays average saved fps. See the
[November 15 A/B test checklist](SUNDAY_2026-11-15.md) for 4K/30 versus 4K/60.

Choose a camera or mode at launch:

```sh
./run.sh --device /dev/v4l/by-id/usb-046d_HD_Webcam_C615_E8CBAB50-video-index0
./run.sh --width 1920 --height 1080 --fps 30
./run.sh --db data/practice.sqlite3
./run.sh --trigger timer --interval 10 --seconds 2  # Original periodic test mode
```

Options apply when starting a recorder. Attaching to an existing recorder uses
that recorder's settings; stop it before changing modes.

## Daily review and evidence retention

The thumbnail bar defaults to **Today**. Select another saved date or **All dates**,
filter by one or more OCR bib candidates, and use **Sightings…** to review timestamped
encounters and intervals. Date deletion lives under **Maintenance → Delete
recordings for selected date…**, with a preview and mandatory typed date/count
confirmation. Stars and active OCR clips remain protected.

Saved video supports pointer-centred wheel/trackpad zoom, drag-to-pan, +/−, and
Fit/0/Escape. Rendering uses original saved pixels off the GUI thread. See
[the review guide](REVIEW.md) for controls, filter semantics and cleanup limits.
An indexed many-to-many bib/video match table supports group segments and SQL
lookups; see [SQL examples](SQL_MATCHES.md).
Future event-scoped participant/EPC identity and OCR/RFID badges are planned in
[INTEGRATION.md](INTEGRATION.md).

## Plate OCR prototype

Current OCR/review/filtering accepts **1–3 digits**, retaining leading zeroes.
The earlier whole-day pass accepted only three digits; a corrected pass is now
running. Capture 877's two-digit 24 is verified through the app worker. See
[short-number support and recurring-rider context](CONTEXTUAL_OCR.md).

See the [November 8 field investigation](FIELD_ANALYSIS_2026-11-08.md) for the
copied race dataset, reproducible neural OCR tests, sampling/tracking failures,
and orientation ambiguity. **Neural OCR** is now available from the GUI, using
the installed optional Paddle environment (CUDA on zbook9, CPU here). It scans
all original frames, recognizes four orientations and keeps competing candidates.
The legacy **Tesseract** backend remains available for comparison. See
[review controls and backend details](REVIEW.md).

For the copied November 8 race footage, run `racevideo-field-review` on whiskey.
It opens the writable test database without starting capture. The independent
NVIDIA all-day sweep imports completed captures while review continues; see
[run and recovery notes](FIELD_OCR_RUN_2026-11-08.md).

Install the optional worker dependencies (already installed in this workspace):

```sh
.venv/bin/pip install -e '.[ocr]'
# Requires English Tesseract data at /usr/share/tesseract-ocr/5/tessdata.
# Debian/Ubuntu package: tesseract-ocr-eng
```

1. Click a saved clip to pause/review it.
2. Click **Select OCR area**, then drag a blue search rectangle around the part
   containing plates, such as the entire wheel. This is independent of the motion
   rectangle. Individual plate corners and numbers are not supplied to the worker.
3. Click **Read plates**. Capture/review continue while a separate process works.
4. Open **Review bibs…**. Select a candidate to inspect its source frame, then
   confirm, reject or correct it. You can also add missed bibs at the displayed
   frame. Operator decisions persist separately from the original OCR.

The following settings describe the legacy Tesseract backend. Its search area is
saved separately from the neural region. Full image is the default; a tighter area
reduces clutter and work. Initial settings sample up to eight frames/second,
limit proposals to 20 regions/frame, and use one worker with native thread limits.
Only one OCR job per database runs at a time; wait before scanning another clip.
CLI access uses the same implementation:

```sh
./run.sh ocr --clip 109 --ocr-area .15,.4,.53,.99
./run.sh gui --no-start --review-clip 109
```

Motion and GUI processes do not import the OCR libraries. The worker combines
MSER/thresholded digit groups and light-label proposals, perspective rectification,
several preprocessing variants and digit-only Tesseract. Both orientations are
tried for the wheel fixture. Source pixels, original frame times, raw 1–3 digit
reads, confidence scores, region corners and best crop evidence are retained.
Spatial/temporal association gives at most one vote per source frame; separate
encounters remain separate observations. Two consistent source frames can mark a
result **repeated**, but that is still an OCR candidate, not a verified bib.
Scores are not calibrated probabilities. There are no CrossMgr/race writes.

The first automatic clip #109 pass found 469 without individual plate annotations,
but also produced wrong numbers. The earlier hand-localized experiment recovered
both 235 and 469; the current automatic path does not yet reliably find/read 235.
The slow 720p fixture therefore provides a positive baseline and concrete errors
for improvement. Upside-down digits, blur, label boundaries and background text
remain significant problems. More pixels should help crop recognition; field
accuracy still needs measurement. See [NOTES.md](NOTES.md) for exact results.

## Camera controls

Click **Camera…** to open the non-modal settings window while Live is running.
The recorder discovers each control's range, step, menus, current value and
availability through Linux V4L2. Missing common controls are listed as unavailable;
read-only and inactive controls are disabled. Sliders apply on release; numeric
fields have Apply buttons. Boolean controls apply immediately; menus have an explicit Apply button.
Unapplied menu choices are preserved while live status refreshes. Requests
run in the recorder's writer thread, away from Tk and camera capture. The panel
shows the camera's actual readback, including failures, rather than assuming a
requested value was accepted. Values refresh every two seconds and after writes.

The test Logitech C615 exposes 17 controls, including autofocus/manual focus,
exposure mode/time, dynamic frame rate, brightness, contrast, saturation, sharpness,
gain, white balance, power-line frequency and zoom/pan/tilt. These are driver
capabilities, not a claim that every setting is optical or independently effective.

For a short-shutter trial:

1. Return to Live, open Camera and click **Enable manual exposure**.
   Alternatively choose **Auto Exposure → Manual Mode** and click its **Apply** button.
   Wait for the camera readback to confirm Manual; the exposure-time controls enable.
2. Set **Exposure Time, Absolute** to **5**, nominally 0.5ms / 1/2000s. The C615
   advertises a minimum of 3, nominally 1/3333s. Exposure labels show both raw units
   and converted time. Indoor images may become very dark: add light or increase
   gain rather than lengthening exposure for moving-plate tests.
3. To lock focus, switch **Focus, Automatic Continuous** off, then adjust **Focus,
   Absolute**. This C615 reports steps of 17. Keep the plate at the intended distance.
4. Contrast and sharpness can help readability, but do not restore detail lost to
   motion blur. Review saved original frames as well as the scaled preview.

The standard exposure units are 100µs per step, documented in the
[Linux camera control reference](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/ext-ctrls-camera.html).
The camera accepted and read back a value of 5 in testing; actual optical exposure
has not been independently measured. Test settings were restored afterward.

Camera values are queried at startup; the app does **not** silently replay old
settings or force a preset. The device may retain values while connected. Queued
requests belong to a specific recorder session and old requests are not replayed
on restart. SQLite retains write requests, readback and errors for diagnosis. New
clip metadata includes the latest polled camera values at the trigger; this is a
snapshot, not per-frame measured exposure. Changing settings affects future images;
saved JPEGs remain unchanged. Autofocus/exposure changes may themselves trigger
motion recording. Controls are Linux-specific and do not require `v4l2-ctl`.

## Motion rectangle

The live image starts with a centered vertical rectangle, 15% of the image width
and 70% of its height. Left-drag near any corner to resize; left-drag inside the
rectangle to move it horizontally and vertically. It stays inside the actual
camera image, including when the window has black margins. The area is applied
on mouse release and persisted in this recording database across restarts.
Changing it resets the detector reference so the resize itself does not trigger.

- **Yellow:** no current movement in the rectangle.
- **Red:** movement detected; remains red through quiet gaps shorter than 0.2s.
- A clip starts with 0.5s of compressed pre-roll where available, and continues
  through 2s after the last positive detection. Motion during that trailing window
  extends the same clip. Yellow during the tail means it is still collecting
  context; the status bar says “saving tail”. Completed clips appear in the strip.

Analysis uses reduced grayscale JPEG decoding, blur to suppress pixel noise, and
frame differences inside the selected rectangle, at up to 15 analyses/second.
Defaults require at least 2.5% of its pixels to change by 18/255 brightness levels.
This is an initial sensitivity setting; shadows, camera shake and exposure changes
can trigger it. Stationary objects stop counting as movement. Tune from the CLI:

```sh
./run.sh --motion-fraction 0.015 --motion-delta 15   # More sensitive
./run.sh --pre-roll 0.5 --post-roll 2 --motion-gap 0.2
```

Long continuous events split into linked chunks at 30s or 128 MiB, without losing
intervening frames. The final chunk retains the trailing context. A deliberate
stop, ROI change or capture error flushes the current partial event and records
why it ended. Thumbnails are chosen from the detected motion interval.

## Review

- Click a thumbnail to review a saved clip. Capture continues; new thumbnails
  arrive on the right without changing the clip being reviewed.
- With the **large viewer focused**, Left/Right step one frame, PgUp/PgDn jump
  ten frames, Home/End go to the first/last frame. The slider also scrubs.
- Space or Play toggles playback, using recorded monotonic frame intervals.
- With the **thumbnail strip focused**, Left/Right select clips, PgUp/PgDn move
  one visible page, Home/End select oldest/newest. Enter focuses the large viewer.
- Drag the strip horizontally to browse. Mouse wheel and scrollbar also work.
  New clips follow to the right if already at the right edge; browsing older
  thumbnails preserves the scroll position.
- Escape, L, or Live returns to the current camera image.
- Save recent 2s captures the current rolling buffer immediately. The duration
  follows `--seconds` if overridden.

**Stop recorder** ends capture and flushes queued clips; saved review stays open.
The button becomes **Start recorder** to resume with the same capture settings.
The Camera panel also offers Start recorder when stopped, and prominently shows
the camera-reported actual exposure mode. Typed numeric drafts survive refreshes
and focus changes until Apply; automatic readback does not replace your entry.
Closing the window leaves capture running. Reopen `./run.sh` to reconnect. Use
these commands without a window:

```sh
./run.sh status
./run.sh capture
./run.sh stop
./run.sh gui --no-start                  # Review only; don't open a camera
./run.sh record                        # Foreground recorder; Ctrl-C to stop
./run.sh record --run-seconds 35        # Bounded hardware test
```

Use the same `--db` for commands addressing a nondefault store. GUI-started
recorders log to `data/racevideo.recorder.log`.

## Storage and process model

`data/racevideo.sqlite3` contains complete clips, thumbnails, original JPEG frames,
per-frame received UTC and monotonic nanoseconds, and original source PTS/timebase.
Frames are ordered explicitly, independent of nominal fps. Displayed times are
local; stored wall times are UTC Unix epoch nanoseconds. Received times are host
receipt times, **not calibrated exposure or finish-line times**.

Camera ingestion, motion/segment coordination, preview decoding, OCR, the GUI and
MCP run in separate processes. A byte-bounded compressed shared ring absorbs
analysis latency; overwritten history is explicitly reported. SQLite writing is
queued on a coordinator thread. Live preview has a latest-only mmap channel and
a one-image shared-memory prepared slot, independent of saved-video reading and analysis.

Open **Performance…** for rolling latency measurements. MCP `app.instances`
includes GUI measurements and `racevideo.status` includes ring/backlog/analysis
health. See [architecture and instrumentation](ARCHITECTURE.md) for process
boundaries, memory limits, failure handling and measured stress-test evidence.
A per-store OS lock prevents duplicate recorders. A second store must not use the
same physical camera. SQLite WAL and atomic clip transactions allow review during
recording without exposing partially saved clips.

There is no retention/deletion policy yet. Recording stops before another clip
is written if free disk space is below 512 MiB. Monitor storage and stop when done;
Full-resolution motion events can still use gigabytes per hour. Keep the SQLite file with its `-wal` and `-shm` files together while
running. Stop the recorder and close readers before copying the store, or use
SQLite's backup API for a live snapshot.

## Development

```sh
.venv/bin/python -m unittest discover -s tests -v
xvfb-run -a .venv/bin/python tests/ocr_gui_smoke.py data/racevideo.sqlite3 data/ocr/gui-test.png --live
xvfb-run -a .venv/bin/python tests/live_smoke.py          # Physical camera, timer
xvfb-run -a .venv/bin/python tests/live_smoke.py --motion # Physical camera, motion
xvfb-run -a .venv/bin/python tests/review_gui_smoke.py   # Temporary-store date/bib/star/delete/zoom flow
xvfb-run -a .venv/bin/python tests/roi_smoke.py
xvfb-run -a .venv/bin/python tests/camera_panel_smoke.py
xvfb-run -a .venv/bin/python tests/camera_live_smoke.py  # Physical camera; restores touched settings
xvfb-run -a .venv/bin/python tests/pipeline_stress.py      # Deliberately slow analysis
xvfb-run -a .venv/bin/python tests/pipeline_stress.py --overrun
.venv/bin/python tests/record_motion_smoke.py             # Deterministic motion input
# Review a previously populated camera test store under a virtual display:
xvfb-run -a .venv/bin/python tests/gui_smoke.py data/webcam-test.sqlite3
```

The live smoke test needs the physical camera to be free; it verifies concurrent
capture/review, manual saves, drag/page navigation, duplicate-recorder protection,
GUI/recorder independence, clean stop, database integrity and JPEG decoding.

Motion tests check ROI masking, static/noise rejection, pre/post timing, gap
merging, bounded event splitting, settings/schema migration, corner dragging,
red/yellow feedback and display scaling. Field sensitivity still needs real
bicycle trials.

See [PLAN.md](PLAN.md) for the broader motion/OCR roadmap and two camera
suggestions, and [NOTES.md](NOTES.md) for observations and tested boundaries.
