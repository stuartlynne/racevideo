# Rider recognition, remote cameras and GPS timing: next-session notes

Discussion following local review of the November 15, 2026 event.
These are design notes and proposed experiments, not implemented capabilities.
Next work: evaluate appearance-assisted rider recognition using Sunday's data.

## Intended use and race profiles

The last two events were feasibility trials for useful video evidence. The
operator considers the results promising enough to explore road racing. Actual
road-speed capture, packed finishes and multi-camera association remain untested.
A faster lens permitting shorter exposure may help; verify on real moving riders.

| Profile | Event duration / circuit | Typical observations |
| --- | --- | --- |
| Cyclocross | 30–60 minutes; riders return every 5–10 minutes | Smaller fields, lower speeds, mostly separated riders; two abreast is uncommon |
| Circuit road race | 2–3 hours; 8–12 km circuits | Packs of 20–60, typically 2–4 abreast; 38–45 km/h mid-race and 50–60 km/h sprints |
| Criterium | 30–60 minutes; 1–3 km circuits | Frequent repeated sightings, but road speeds and crowded passing groups |

An event generally contains 20–200 participants. Appearance matching can operate
within that event, rather than searching an unrestricted population.

The operator's SuperWeek experience is the model: RFID and observers could narrow
an unidentified photo-finish rider to 2–4 candidates, aided by team/jersey colours.
The goal is a practical evidence assistant with a small deployment, rather than
replicating three FinishLynx cameras, front/back video and a dedicated camera crew.

## Rider appearance and passing identity

Store representative images and appearance descriptors for jersey colours and
pattern, shorts, helmet and bicycle. Descriptors can be learned image embeddings
(compact numeric features); readable colour descriptions help human review.
Compare separate regions so grass, road and other riders do not dominate colour.

Keep three concepts separate:

- A participant has an event-specific bib/appearance gallery.
- A physical passage is one traversal, possibly seen by several cameras.
- A track is a detector's temporary observation; several fragments can belong to
  one passage. The same participant returning later creates a new passage.

Build galleries from operator-confirmed or otherwise well-supported sightings.
Retain several sharp views per rider, with source frames and confidence. Do not
teach the gallery from its own unconfirmed guesses. Future cross-event identity
could use participant/EPC data; bib/name mappings must remain event-specific.

For a new passage, combine appearance, OCR alternatives, category, elapsed lap
time, nearby RFID reads and CrossMgr predictions. Show a ranked short list with
evidence. Appearance similarity must not silently create a manual confirmation.

For packs, reason over the whole group: if only three roster riders have similar
red kit and two are reliably located elsewhere, the remaining rider becomes a
stronger candidate for an obscured person. Keep uncertainty about missed riders,
identical kit, bad assignments or incomplete RFID data. Opposite-camera sightings
of the same rider must not become two passings.

Identity and finishing order are independent evidence. A rider may be identified
without a visible front-wheel crossing; a crossing may be clear with no identity.
Keep the best identification frame separate from the crossing frame/time.

### Libraries worth benchmarking

- [OpenCV histogram comparison](https://docs.opencv.org/4.x/d8/dc8/tutorial_histogram_comparison.html): inexpensive regional colour baseline.
- [Torchreid / OSNet](https://github.com/KaiyangZhou/deep-person-reid): learned appearance descriptors and gallery comparison.
- [OpenVINO person-reidentification-retail-0288](https://github.com/openvinotoolkit/open_model_zoo/blob/master/models/intel/person-reidentification-retail-0288/README.md): small 256-value embedding model, a CPU candidate. Documented pose coverage is upright pedestrians; leaning cyclists are a domain shift, not a validated use case.
- [BoT-SORT](https://github.com/NirAharon/BoT-SORT): reference for combining motion and appearance through interruptions. Evaluate the approach and dependencies before incorporating it.

### Tomorrow's experiment

1. Use confirmed early laps to build an event gallery. Hold later laps out for
   testing; split by passage/lap, not adjacent frames from the same sighting.
2. Compare regional colour features, a small embedding model and their combination.
3. Measure correct first choice, correct identity among the top three, confident
   wrong suggestions, and rejection/unknown rates. Include matching team kit,
   occlusion and changing light. Compare against OCR/timing alone.
4. Measure CPU time per sampled image and passage. Several selected images per
   passage may suffice; do not assume every frame needs an appearance embedding.
5. Preserve the current real-capture ordering regression before integrating any
   model into the app. First prove useful suggestions; then add persisted galleries
   and operator-facing evidence. No appearance model has been benchmarked here yet.

## Current data and code starting point

Local writable review DB:
`/raid4tb/sl/racevideo/tests/2026-11-15/racevideo.sqlite3`.
Protected original:
`/raid4tb/sl/racevideo/imports/zbook9/2026-11-17/racevideo.sqlite3`.
Start local UI with `~/.local/bin/racevideo-sunday-review` on display `:0`.

The CPU OCR batch completed all 828 Sunday clips / 51,873 frames without errors.
Saved per-frame reports: `ocr-local-cpu/` under the test directory. There were
initially 1,187 candidate observations; physical-trajectory consensus recovered
77 more, for 1,264 in 457 clips. Counts are not recognition accuracy.

Code baseline is `cc53640`: passage-v4 plus physical-trajectory OCR consensus.
Clip 1872's Elite Lap 2 must display 5, 6, 2, 1, 60, at display frames
21, 25, 43, 56, 80. Rider 1 remains an unconfirmed suggestion; repeated OCR supports
the other four. `tests/fixtures/elite-lap2-1872.json` contains real saved detections
with rebased times and no JPEGs/names. Its regression checks rider order and
separate review frames, not merely fewer candidate rows. Clip 1954 must retain
two riders at display frames 18 and 28. See CODEX_HANDOFF.md and
REVIEW_CAPTURE_CHOICES_2026-11-15.md for pitfalls, audits and current boundaries.

No AMD inference experiment: earlier GPU work destabilized the desktop. This
batch used CPUs. Laptop NVIDIA inference has a separate established environment.
Latest tracking changes were applied locally and pushed to GitHub; laptop
deployment and its current checkout must be verified separately.

## Remote camera nodes and Wi-Fi

An elevated camera and/or cameras on opposing sides may improve visibility in
road packs. Exact placement, depth of field and occlusion need field trials.

A Pi 4/5 may handle native USB MJPEG capture, timestamping, storage and forwarding
without decoding every frame. This has not been benchmarked on a Pi. The camera
already compresses JPEGs; RaceVideo currently saves the original MJPEG packets.

Measured Sunday samples at 30 fps, excluding transport overhead:

| Clip | Mean JPEG size | Equivalent continuous bitrate |
| --- | --- | --- |
| 1850 | 2.101 MB | 504 Mbit/s |
| 1872 | 1.987 MB | 477 Mbit/s |
| 1968–1970 | about 1.64 MB | about 392–394 Mbit/s |

Two full streams could therefore need roughly 800–1,000 Mbit/s. Do not assume
built-in Wi-Fi can sustain that in race conditions. Prefer a local original-data
buffer/SSD, a small preview over Wi-Fi, and queued transfer of motion segments or
requested evidence. Long packs can create a transfer backlog; bound storage,
report backlog/drops, and preserve capture independently of connectivity.

[Pi 5 specifications](https://www.raspberrypi.com/products/raspberry-pi-5/)
include USB 3, Gigabit Ethernet and dual-band 802.11ac. Pi 5 uses software video
encoders ([documentation](https://www.raspberrypi.com/documentation/accessories/camera-software.html));
Pi 4's hardware H.264 encoding is specified at 1080p30
([specifications](https://www.raspberrypi.com/products/raspberry-pi-4-model-b/specifications/)).
Neither fact proves USB MJPEG-to-4K streaming performance. If continuous 4K
transcoding is required, investigate a small x86 system with a supported hardware
encoder, e.g. Intel Quick Sync; [N100 lists support](https://www.intel.com/content/www/us/en/products/sku/231803/intel-processor-n100-6m-cache-up-to-3-40-ghz/specifications.html).
Validate actual codec/driver support, frame drops, image quality and power before
purchasing a fleet. Start with one available Pi and the existing camera.

At 60 km/h, distance between observations is about 56 cm at 30 fps or 28 cm at
60 fps. Shorter exposures reduce blur but do not increase temporal sampling.
Timestamp frames at the camera node; network receipt time contains Wi-Fi delay.

## Low-cost optical GPS timing beacon

Proposed hardware: GPS/GNSS module with PPS output, LED driver and bright visible
LED in a small weather-resistant assembly. An ESP32 can supply supervision,
configuration or UTC logging, but may be unnecessary if the receiver starts and
provides the required pulse automatically. Drive the LED from hardware PPS,
rather than an ESP software timer. Configure a rising edge aligned to UTC and a
100 ms pulse each second, with valid-time/GPS-lock handling. Pulse width/defaults
are module-specific; [u-blox documents configurable pulse timing](https://content.u-blox.com/sites/default/files/documents/MAX-M10M-00B_IntegrationManual_UBX-22038241.pdf).

For road events, RFID reader boxes are commonly on each side of the road. They
already have 12 V DC backed by LiFePO4 batteries, powering roughly 32 W of reader
and Wi-Fi equipment. A small regulated supply can power the GPS/LED assembly
from those boxes. The operator's approximate 1 W incremental budget is a design
estimate, not a measured load. This avoids another battery/charging workflow.
USB-C or a USB power bank remains an alternative; check low-load auto shutoff.

Mount a visible LED externally, with suitable daylight shading. Both cameras
could see one optical source, or each side could have its own GPS-locked beacon.
Optical visibility and power/weather protection need field testing.

Detect off-to-on edges in a small ROI, pair them with UTC second numbers, and
store the pulse observations and calibration uncertainty in the database. PPS
flashes alone do not identify the absolute second: provide a UTC log or another
unambiguous reference. A 100 ms pulse spans roughly 3 frames at 30 fps or 6 at
60 fps. Repeated edges can estimate camera clock offset and drift and reveal
discontinuities. These observations calibrate actual imagery despite USB/network
buffering, but do not physically synchronize shutter phases. One edge is bracketed
by about a frame interval (33/17 ms at 30/60 fps); do not claim GPS-level timing
accuracy for video. Rolling shutter makes LED-versus-wheel image-row position
relevant; place the beacon near the crossing image height or characterize readout.

Timing hardware and multi-camera deployment are future experiments. Rider
recognition on the existing Sunday data is the next session's immediate work.
