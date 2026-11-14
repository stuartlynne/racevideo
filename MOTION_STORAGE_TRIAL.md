# Sunday motion, storage and review experiments

Implemented November 10 for the November 15 trial. Open **Motion / storage…**
beside the date browser. The default remains **Finish zone only** and trim
proposals remain **Off** until the operator selects and applies other choices.

## Recording / zones

| Behavior | Starts/extends a motion segment when… | Tradeoff |
| --- | --- | --- |
| Finish zone only | The existing draggable finish rectangle sees movement | Familiar baseline; pre/tail frames cover travel outside it |
| Entry / finish / exit — any zone | Any of the three strips sees movement | Earlier entry/later exit coverage; excludes some space between strips |
| Wide road zone | The road rectangle sees movement | Covers space between strips; more sensitive to spectators, shadows and flags |
| Entry / finish trigger, wide road hold | Entry or finish triggers; once active, any strip or road movement renews it | Avoids road-only starts, while keeping a group active between strips |

Entry defaults to the right and Exit to the left for the observed right-to-left
traffic. Move them for the actual camera placement/direction. Use **Draw on Live…**
for each zone or edit normalized coordinates. Drawing is a draft until **Apply
choices**. Escape cancels a drawing. The existing Live finish handles still work.
Applying configuration ends the active segment at a documented configuration-change
boundary and resets comparison baselines; capture continues. An already-running
older recorder must be restarted to load this implementation.

All zones share one reduced grayscale decode. Each compares its own changed-pixel
fraction. Strips inherit the configured motion fraction (normally 0.025); Road
defaults to 0.005 because a small rider occupies less of a wide rectangle. The
Road fraction is editable. Live outlines identify zones and indicate movement.
Avoid sky, flags and spectators. A later GPS beacon will need exclusion/masking
if it lies inside monitored areas; flashing once per second could otherwise keep
a one-second quiet tail active indefinitely. Exclusion-mask editing is future work.

Runtime reports `motion_decode_ms`, `motion_compare_ms`, `motion_analysis_ms` and
per-zone scores/thresholds. Saved clip metadata records the selected motion profile,
zones, fractions and quiet-close policy. Existing one-second quiet close, pre-roll,
event-size limits and analysis-overrun handling still apply.

Local cached-frame microbenchmark (not a sustained camera/load test):

| Mode | Zones | Median decode ms | Median comparison ms |
| --- | ---: | ---: | ---: |
| Single | 1 | 11.75 | 0.031 |
| Three strips | 3 | 11.35 | 0.064 |
| Wide road | 1 | 11.38 | 0.067 |
| Trigger + hold | 4 | 11.47 | 0.120 |

The comparison increase is small relative to decoding. Actual zbook9/camera/scene
load must still be measured. Data: `data/validation/motion-mode-timing.json`.

## Storage proposals

The **Storage proposals** tab selects:

- **Off:** normal original recording.
- **Road-motion trim proposals:** use low-resolution changes against the first
  frame in the chosen road area. **Analyze selected capture** runs in a separate
  process. Neural OCR can also calculate these from already-decoded frames.
  Tesseract runs a separate reduced-decode pass within its analysis process.
- **Reuse bike detections during neural OCR:** retain proposed intervals with
  bicycle detections, independently of whether any bib can be recognized.
- **Reuse bike/person detections — conservative:** also retains detected people,
  which can preserve pedestrians or bystanders in the road area.

Choose behavior and Road area, **Apply choices**, select a saved capture and
**Analyze selected capture**. Bike-based analysis runs neural OCR; choosing
**Read plates** normally also records proposals when enabled. Bike-based proposals
require Neural OCR; selecting them with Tesseract reports that incompatibility.
The neural bike/person detection is already performed to propose OCR regions;
the proposal reuses those detections and adds no second neural detector pass.

Presence intervals have a 0.1-second margin and bridge detection gaps up to 0.4 s.
Multiple separated intervals can be proposed for one source clip. All detected
bikes contribute; no OCR number is required. A detector box's bottom-centre must
be inside the Road area. Keep the bottom of that area at 1.0 where wheels are
clipped by the image edge. No detections yields an inconclusive **keep everything**
proposal. The first-frame background method can be confused by occupied starts,
wind, lighting changes or occlusion. These are proposals, not validated wheel
entry/exit measurements.

The results list original frame ranges, retained frame counts and JPEG bytes.
Select a range and use **Before start / Start / Middle / End / After end** to
inspect boundaries in the main viewer. Proposals are saved in
`retention_proposals`; original frame ordinals/timestamps/JPEGs are unchanged.
There is **no automatic deletion or physical file shrinking** in this trial.
Current disk usage will therefore not fall merely by enabling proposals.
Date cleanup protects clips with queued/running OCR, bike-index or retention analysis.
Decisions must be checked before implementing destructive pruning or compact exports.
Future pruning must also retain GPS calibration observations before buffer overwrite.

Real validation on capture 747:

- Original: 88 frames, 159.37 MB of JPEG data.
- Neural bicycle proposal: 28 frames, 50.86 MB (about 68% potential reduction).
- Road-motion proposal with a manually chosen area excluding flags/curtain:
  25 frames, 46.34 MB (about 71% potential reduction).

These are candidate savings from one single-rider clip, not a whole-event forecast
or proof that every useful entry/exit frame is retained. No source footage was
deleted. Both analysis paths were exercised against real recordings; no new live
physical-camera or sustained event-load trial was performed.

## Faster passings review

After choosing a passings cell/capture, the main video window displays its
suggested bib and **Confirm N ✓**. Review the image and click it without returning
to the passings window. Enter also confirms while the main video has keyboard
focus. The existing event-specific review/history and undo paths are used. It
disables for another capture, an unfinished frame load, a pending write, or an
already confirmed matching observation. Suggested means the selected passing's
candidate, not an independently detected identity for every visible bike.

**Previous bike / Next bike**, or Ctrl+Left / Ctrl+Right, jump between indexed
passages and highlight the selected bike when spatial evidence exists. Two manual
bikes on one frame can remain separate stops with separate boxes. With a multi-bike
capture, verify the intended bike; use Mark bike/order to make the association explicit.

New neural OCR jobs automatically save a bike-passage index, using the existing
bicycle detections rather than bib strings. **Find bikes** builds the index for an
older recording using only the cached object detector; it does not rerun OCR or
change race results. It uses the same heavy-analysis lock as OCR and a maximum
two-logical-CPU affinity. Estimated counts are marked `~`; occlusion and split or
merged detections can make them wrong. A returning bike creates a new passage.
Stationary/jittering detections without meaningful net travel are excluded.

Without a detector index, navigation uses OCR encounter groups and effective human
reviews. Multiple number alternatives from one encounter remain one navigation
group, but the label explicitly says the bike count is incomplete. In particular,
one OCR group does not imply that the capture contains only one bike. Previously
completed indices remain usable while another analysis is queued/running.

Capture 724's detector-only validation found three passages, with representative
displayed frames **20, 29 and 95**. The last is the partial following rider;
neighboring capture footage may be more useful. The previously missed early bikes
are navigable without OCR labels. Source data and operator reviews were retained.

## Suggested Sunday sequence

1. Begin with the existing single-zone baseline, manual exposure and a focused lens.
2. Draw appropriate entry/exit/road zones; keep waving objects outside them.
3. Try the three-strip mode on singles and groups, then wide-road and trigger/hold.
4. Compare capture continuity, idle false triggers, frame counts, original JPEG
   bytes, measured FPS, analysis backlog and UI latency. Keep exposure/framing
   fixed when comparing behaviors. Profile switches are recorded in clip metadata.
5. Analyze examples with motion and neural proposals; inspect both ends and group
   gaps, including unreadable plates and a rider who is partially occluded.
6. Keep originals throughout this trial. A missed bike matters more than a favorable
   proposed byte count. Sunday's slow cyclocross test does not validate road sprints.
