# Event passings review

Implemented 2026-11-09. This is evidence review; it does not edit CrossMgr races.

## Operator workflow

1. Select the recording date in the main window and click **Event passings…**.
2. Choose a competition and event from their selectors. November 8 PartyCross's five events
   are already cached in both the local review database and zbook9's normal store.
3. For another date, enter the date and CMN base directory, then click
   **Import / refresh CMNs**. Discovery looks one directory level below the base
   for `YYYYMMDD-eventname` directories and immediate `.cmn` files. Imports use the
   CrossMgr MCP saved-race APIs; RaceVideo does not unpickle CMNs itself.
4. Review the lap chart, optionally filtering category. Each column is an
   independently ordered list of passings. Overall leader lap completions define
   its time band; the leader begins the column. Start and other earlier stored
   passings have a separate **Start / pre-lap** column. A category filter keeps
   the overall event boundaries, even when that leader is outside the filter.
5. Click a cell to open the best matching capture in the main window, initially
   positioned with its first moving bike roughly centred. The
   capture chooser below the chart offers other matches and nearby time candidates.
   If OCR found nothing, a yellow CrossMgr cell still offers captures near that
   passing time. No capture within the window is explicitly indicated.
6. Use **Review bibs…** in the main window to accept, reject, correct or add
   a visible number. The passings comparison refreshes video evidence every five
   seconds while open, without querying CrossMgr again or resetting the main view.

### Confirm, correct or ignore directly from the chart

The main video window now repeats the selected passing's suggested bib and a
**Confirm N ✓** button. Review the image and click there; Enter also confirms while
the video has focus. Existing review history, manual-frame anchoring and undo still
apply. **Previous bike / Next bike** (Ctrl+Left / Ctrl+Right) moves between detected
or manually identified passages, with spatial highlighting when available. Counts
are estimated; older OCR-only groups explicitly indicate incomplete bike coverage.
**Find bikes** builds a detector-only index. See MOTION_STORAGE_TRIAL.md for limits.

After clicking a cell and inspecting the main image, the controls below the
capture chooser provide:

- **Confirm bib:** save the number in **Visible bib** as operator-confirmed visual
  evidence. It is prefilled from the selected cell. A capture with no OCR gets a
  manual bib anchored to the displayed source frame. The matched chart cell shows ✓.
- **Save different bib:** enter the number actually visible and save a correction.
  If it differs from the expected rider, that expected CrossMgr passing remains
  unconfirmed; the corrected identity is matched independently by bib and time.
- **Ignore / bystander:** suppress this visual encounter in the selected event.
  It does not delete raw OCR, reject other riders in the video, or erase an
  expected CrossMgr passing. A missing CrossMgr passing stays yellow. For a
  nearby capture with no OCR, this records an ignored-frame annotation; it cannot
  remove an expected passing or exclude a whole multi-rider video.
- **Undo last review:** reverse the last review in this event, including a newly
  created manual bib. Refuses to overwrite a bib decision modified elsewhere.

An optional note can describe the evidence, e.g. readable back bib, crumpled bib,
small legacy frameplate or bystander. Saving requires that the chosen capture is
actually displayed in the main window. It records the displayed ordinal/time
alongside the original OCR source reference, even when OCR's representative frame
differs. A decision is not inferred from the expected CrossMgr bib alone.

New capture selections from thumbnails or the passings capture chooser now seek
to a first-subject centre estimate instead of frame zero or an empty post-roll
midpoint. A bounded low-resolution scan runs in the review worker, with a 128-clip
in-memory cache and cancellation when selection changes. It scans only the first
four seconds and refines around the first moving silhouette's centre crossing.
If inconclusive, it uses the first retained OCR encounter or the motion trigger.
Moving banners, occlusion or a clip already starting mid-passage can still need
manual scrubbing: this is a display convenience, not identity or timing evidence.
Exact OCR-evidence/Sightings jumps and explicit MCP frame requests retain their
requested frames. Performance includes `review_position_ms`, decoded-frame count
and whether the position was cached. The selector does not crop, pan or alter video.

Event-specific `race_visual_reviews` and append-only
`race_visual_review_history` preserve decisions, before/after state and source
references. Confirmations/corrections also use the existing `bib_reviews` and its
audit history, atomically in the same transaction. Competing OCR alternatives on
the reviewed track are suppressed only in this event's chart. Ignore is event
scoped and does not globally reject a readable number belonging to another race.
It applies to the reviewed source evidence; a new OCR run producing new tracks
can introduce new candidates for review. Timestamp overlap alone is not enough
to assume two tracks are the same bike.

Colours:

- **Light green:** same bib appears in visual evidence near a stored CrossMgr
  passing. `?` means unreviewed OCR; `✓` means operator-reviewed visual identity.
- **Light yellow:** stored CrossMgr passing without a visual match, or visual
  evidence for an event entrant with no nearby stored passing. This is a review
  opportunity, not proof of a missed RFID read or a missed lap.
- **Light red:** visual candidate not in this event's cached participant set.
  It could be an OCR error, another event's rider or an incomplete roster.
  The cached entrant set includes result riders and workbook tag assignments,
  including tag owners with no model reads. The current MCP response does not
  expose a complete registration sheet: an untagged entrant absent from the model
  may still require start-list verification. Registration-only identities do not
  acquire invented categories or passings.

Competing OCR strings on one geometry encounter are alternatives, not extra
riders. Alternatives belonging to a matched encounter appear in the selected-cell
details. Otherwise out-of-roster alternatives share one red encounter cell.
Groups can still be imperfectly segmented by the detector. These cells/counts
are not independently verified rider counts or OCR accuracy statistics.

## Time matching and event scope

Default match tolerance is ±3 seconds around the observation interval. Matching
requires both the exact bib string and proximity in time. `24` and `024` remain
distinct. One video may match several riders; each rider may match many videos.
Nearby clips without a bib match remain potential evidence, not matches.

**Camera − CM seconds** is an explicit receipt-clock offset, initially zero:
`camera_time = CrossMgr_time + offset`. It changes comparisons only, not source
timestamps. This is not GPS calibration or front-wheel finish timing. The wheel
prototype in FINISH_LINE_TIMING.md is not integrated into this chart.

CrossMgr's saved start time is interpreted in the configured race timezone when
it has no offset. November 8 on this system uses the copied zbook9 timezone file
because the hosts had different timezone-data revisions. Original elapsed times,
raw source payloads and the interpretation are retained. Ambiguous/nonexistent
local start times are rejected rather than guessed. Time trials are explicitly
unsupported for this first integration.

The importer deduplicates riders/passings across wave and component category
results. Actual stored `rider.times` entries are the passing evidence. Scored lap
numbers are associated only where a non-interpolated wave result matches a stored
passing. Projected/interpolated results do not create passing records or leader
boundaries. Unscored start reads remain visible. Leader changes are allowed;
the earliest observed completion of each scored lap establishes its boundary.
Incomplete or modified sporting histories can still need operator interpretation.

Stored CM passings labelled `Unattributed` are not proof of RFID detection.
The cache retains provenance and RFID tag assignments, but live RFID read-log
corroboration and race-result writes are not part of this implementation.

## Configuration

Optional `~/.config/racevideo/crossmgr.json` (or path in
`RACEVIDEO_CROSSMGR_CONFIG`):

```json
{
  "root": "~/wimsey_crossmgr/sl/2026/LMCX",
  "url": "http://127.0.0.1:8050/mcp",
  "token_file": "~/.config/crossmgr-mcp/token",
  "timezone": "America/Vancouver",
  "timezone_file": ""
}
```

Environment overrides: `RACEVIDEO_CROSSMGR_ROOT`, `CROSSMGR_MCP_URL`,
`CROSSMGR_MCP_TOKEN_FILE`, `RACEVIDEO_RACE_TIMEZONE`, `RACEVIDEO_RACE_TZFILE`.
The directory browser uses the application's filesystem; the MCP server must be
able to read the same absolute paths within its allowed roots. The current local
configuration uses zbook9's MCP endpoint and a private token file; zbook9 uses its
local service. No credentials are stored in the race database or repository.
Editing the window's base-directory entry affects that window; edit the config
file or environment for persistence across launches.

Importing is an explicit request to inspect trusted CMNs within the selected base.
The MCP client sends `trusted_pickle=true` for those inputs. No standalone
unpickling fallback exists. Install the optional `.[mcp]` dependencies for imports;
cached review does not need a live CrossMgr service.

Multiple date-prefixed directories on one day are separate competition choices.
For example, zbook9 also has a `20261108-PartyCross2` directory containing another
Launch CMN. Discovery imports it separately; it does not replace or merge the
original PartyCross Launch event. Select the intended competition explicitly.

CLI import:

```sh
.venv/bin/python -m tools.crossmgr_passings \
  --db data/field-tests/2026-11-08/racevideo.sqlite3 --day 2026-11-08
```

The GUI also accepts `--passings` to open the window at launch. It uses the main
browser's date when opened; Today/All dates default to today's date, which can
then be edited inside the passings window.

## Storage and responsiveness

Additive `race_competitions`, `race_events`, `race_sources`, `race_categories`,
`race_participants`, `race_participant_categories` and `race_passings` tables
are installed with the existing core schema. Core user_version remains 11: this
extension does not alter existing columns or rewrite video/OCR/review records.
Competition is the day/directory, event is the source CMN and category membership
is event/source scoped. Participant bibs and RFID assignments are scoped to that
source snapshot, so a rider using different bibs in different events is supported.

CMN/workbook hashes identify cached source versions. An unchanged import is
idempotent; changed inputs append a new source version and preserve older payloads
and normalized records. Pagination requires consistent input hashes. Live GUI
snapshots and automatic watching of edited CMNs are future work; explicitly
refresh CMNs when the saved race data changes. Completed event imports survive
an error importing another event and remain available for cached review.

All MCP/network and SQL comparison work runs in a dedicated background worker.
Video frames/evidence JPEGs are not loaded to construct the chart. The bounded
worker request queue coalesces pending UI requests; scrolling moves retained
canvas items, and unchanged comparisons do not redraw the chart. Capture, live
preview and OCR processes continue independently.
The Performance window includes `passings_query_ms` and `passings_draw_ms` so
database work and Tk rendering can be measured separately.

Validation: real MCP import of all five November 8 files (653 deduplicated stored
passings); category/leader ordering inspected against the resulting chart. Local
comparison construction measured approximately 2–10 ms per event on this dataset.
Unit tests cover source versioning, exact short bibs, event separation, review
updates, projections, category duplicates, time offsets and alternative grouping.
Real Tk smoke tests exercise matched, missing and extra-cell navigation. This is
not a validation of physical race timing or sporting classifications.

## Bike-first operator workflow (November 11)

Arrow keys select riders/candidates in the table: Up/Down move within a lap,
Left/Right move to the nearest row in the adjacent nonempty lap. Selection scrolls
into view and opens the corresponding source frame. Text fields keep their usual
cursor-key behavior. Rapid selections coalesce in the reader; obsolete index and
frame responses cannot overwrite the newest selection.

The chart now includes detected bike passages with no readable bib, labelled **? /
Unidentified bike**. Multiple OCR alternatives assigned to one physical passage
remain one visual entry and cannot confirm two CrossMgr passings. Expected CM
passings without visual evidence remain separate yellow review targets; selecting
one offers individual nearby bike candidates as well as unindexed nearby clips.
Their presence or absence does not automatically establish a DNF.

Use **Index event bikes** to index the selected race's recordings without repeating
OCR. It queues captures with missing indices or an older detector policy, reuses
one model in a separate analysis process, and respects the OCR analysis lock.
The status shows indexed capture coverage and running/queued work. **Stop indexing**
cancels queued captures; an active clip finishes. Existing completed indices,
footage, OCR and manual reviews remain. The button does not start automatically.
**Find bikes** still rechecks just the selected capture.

The new recall-first policy accepts bicycle detections down to 0.15 confidence,
including short, stationary or weak tracks as uncertain candidates. It orders
passages by the frame nearest the image centre, not by their OCR strings. These
are approximate passage positions, not calibrated front-wheel crossing times.
Existing source-frame/manual bike-order annotations remain available. Occlusion,
track splitting and incomplete model detections still need human review; this
cannot guarantee every rider is found.

**Ignore / bystander** hides only the selected physical passage and its associated
OCR alternatives within this event. It never deletes footage or CrossMgr reads.
The status retains an ignored count; **Show ignored** exposes grey entries with
source frames and **Restore ignored** restores a selected decision independently
of later decisions. Undo remains available. An ignored visual match leaves the
underlying expected CM passing available for investigation.

Validation: 144 unit tests passed on both hosts, with Tk checks for real arrow
keys, rapid same-clip selection, ordinary text editing, individual unidentified
bikes, ignore/show/restore, confirmation and existing manual bike annotations.
A targeted detector-only run on zbook9 capture 724 retained 20 candidates with the
more permissive threshold, versus the older three moving passages. This includes
false detections and fragments; it demonstrates the recall tradeoff, not 20 real
riders. No whole-event index or OCR rerun was started during implementation.

## Compact review and keyboard actions (November 11)

Opening Event passings hides the main window's Date/browser row, thumbnails and
all controls below them, giving that space to the video. Closing passings restores
them, keeping the current date/filter and review position. Playback, frame scrub,
zoom buttons and the review confirmation controls above Date remain available.

With focus in either the main video window or passings table:

- **Space** confirms the current identification; it does not start playback.
- **+** (including keypad +), then **1–3 bib digits**, then **Enter** adds a separate
  human-confirmed bib at the displayed frame. An entry opens in passings. This
  neither corrects nor replaces the selected rider, and supports multiple added
  bibs on the same frame. Mark the bike/order first when useful.
- **−** (including keypad −) ignores the selected visual candidate using the same
  audited hide/restore workflow as the button.
- **Esc** in the add entry cancels it. Invalid numbers stay in the entry for correction.

Ordinary text/number fields retain their normal typing behavior. The add operation
is anchored to its original event/capture/frame; changing those before Enter
requires cancelling and starting again. Shortcuts respect pending review writes.
Space is intercepted before button bindings, so a focused Ignore button cannot
accidentally execute an ignore when Space means confirm. Closing passings restores
normal Space playback and +/− zoom shortcuts. The Play button remains usable while
passings is open.

Validation: 145 unit tests on both hosts and Tk checks cover actual key presses in
both windows, text-entry protection, focused-button behavior, independent same-frame
additions, cancel/validation, ignore, enlarged video and restored browser/playback.

## Resume, undo/redo and focus (November 11)

The app periodically saves a small `<database>.ui.json` sidecar on this host,
separate from recording evidence. It restores main and passings window geometry,
maximized main state, selected date/bib/star filter, replay clip/frame/zoom/pan,
and whether passings was open, its event/competition/category, clock offsets,
selected cell/capture and table scroll. Closing passings retains its last options
for reopening it on the same date. Closing the app saves the open passings state
before destroying either window. A removed/filtered-out capture falls back safely
without silently clearing the saved date/filter. Recording startup behavior is
unchanged. The first launch of this version establishes the saved session.

While passings is open, arrows navigate riders from either main or passings;
Space / + / minus work in either window too. Plus explicitly transfers typing
focus to the bib entry. Normal text fields retain normal editing. Play and frame
slider buttons remain available in the main window.

**Ctrl+Z** undoes the latest review and **Ctrl+R** redoes it, with buttons in
passings as well. Multiple undo/redo steps survive reopening because their links
are stored in the review audit. Confirm, correct, added bib and ignore decisions
are supported; a new decision clears the redo branch. Exact source review rows,
manual geometry/order and identities are restored transactionally, with stale
change and conflicting bike-order guards. Nothing is written to CrossMgr.

Zoomed video uses grab/drag to pan; scroll or the zoom buttons enlarge the image.
Dragging pauses playback and only the latest requested viewport is presented.
Changing captures clears unfinished OCR/zone/bike drawing gestures, so they cannot
silently intercept an ordinary pan on another capture. At Fit there is no cropped
image to pan.

Validation: 148 unit tests passed on both hosts. Restart/focus GUI tests verified
both windows' positions, date/filter, event/category/cell, source frame, zoom/pan,
arrows/confirm/undo/redo from either window, actual add-entry focus transfer and
pointer drag. Existing passings, manual-bike, motion-options and shortcut checks
also passed locally. Protected recording backups remain unchanged.

## Video cue and review advance (November 11)

While reviewing a selected passing's loaded capture, the main video shows its
suggested bib at top left in large bold type (48 pt), with a black backing for
contrast. Green means matched, yellow means missing/unidentified/visual-only,
and red means outside the event roster, matching the selected chart state.
The cue hides while a different capture loads and when passings closes.

Up/Down follow column order: Down from the bottom moves to the top of the next
nonempty column, and Up from the top moves to the bottom of the previous column.
The first/last entries are boundaries. Left/Right retain their adjacent-column
row behavior. Selection scrolls into view, from either main or passings focus.

Space confirmation and minus ignore use the same Down advance, **after a
successful database commit**. Invalid input or a failed save does not advance.
Clicking elsewhere while the save is pending cancels its automatic advance.
Buttons, Enter confirmation, manual add, undo and redo do not auto-advance.
At the final entry, confirmation stays there; ignoring a final visual-only entry
hides it and holds the source video instead of jumping to another bike. Down then
holds, and Up selects the last remaining entry. An expected CM passing remains
available even when its associated visual candidate is ignored.

Validation: 148 unit tests and GUI checks on both hosts. The new
passings_advance_gui_smoke.py exercises every row/column boundary, confirm and
ignore advance, invalid input, end-of-table holds and the large green/yellow/red
video cue. Shortcut and restart/undo/pan checks were updated for the new advance
behavior. No field footage or human reviews were changed by these tests.

## Correct rider within a shared capture (November 11)

Capture 764 (143 frames; zbook9 review around 14:47:29) exposed two problems:
only Nelson's 499 had OCR evidence, and Napier's expected 4 reopened the clip at
its first subject. Previous/Next had only one OCR evidence group available.

A targeted detector-only run now indexes this capture on both working copies.
Selecting Napier offers the sustained, unassigned second bike first and seeks
source display frame **75**, where plate 4 is visible. The sustained first rider
is centered at frame **20**. This positioning is a candidate for human review,
not an automatic confirmation or finish-time measurement. No operator decisions
were changed. The full protected recording backup remains unchanged.

Missing passings prioritize unassigned sustained tracks ahead of weak fragments
and tracks already associated with another CrossMgr passing. Navigation uses
primary stops from sustained tracks in each occupied interval, retaining
independently sustained overlapping tracks. All weak/short candidates remain in
the review data and table; they are not deleted or marked ignored by this ranking.
The count distinguishes primary navigation stops from total candidates.

Previous/Next now align to the selected bike/source frame and disable at true
boundaries. Scrubbing uses the current frame to choose the next directional stop.
Without a bike index, a time-only candidate seeks the nearest expected passing
time instead of reopening the first bike. That fallback is approximate; use
Find bikes or Index event bikes on older recordings to obtain physical targets.

Validation: 149 unit tests and GUI checks on both hosts. A 143-frame two-bike
regression covers a readable first rider and missed second rider, fragment
retention, Previous/Next alignment, boundary states and unindexed time fallback.
The actual local capture 764 was exercised in Tk: Nelson frame 18 → Next frame
75 → Previous frame 20; selecting Mac Napier also opened frame 75. Human review
audit count stayed unchanged. Artifacts: data/validation/clip764-fixed-review-ui.png,
clip764-mac-frame75.jpg and clip764-zbook9-bike-index.json. Local and zbook9 time-zone
data currently render the same source time an hour apart; matching used exact
source nanoseconds, capture identity and frame ordinals.

## Generic CM-no-visual positioning (November 11)

The missing-visual path now examines images when no useful bike index exists;
it no longer relies only on the beginning or nearest expected timestamp.
A bounded CPU/Pillow motion preview finds moving-subject tracks and positions the
video near a centered candidate. It deprioritizes evidence already matched to
another passing. No OCR result or neural/GPU runtime is required.

Preview positions are cached as source=motion bike-analysis metadata and supply
Previous/Next stops and unidentified candidates for review. They remain unconfirmed;
a moving subject is not proof of the expected rider. Neural detector results take
precedence when available, even if a preview job received a newer database ID.
Index event bikes still upgrades motion previews to neural indices.

Short clips are sampled across their length. For clips over 12 seconds, the scan
covers roughly five seconds either side of the expected time and is labelled
partial. There are at most 96 reduced JPEG decodes, with reusable foreground masks.
The first/middle/last-image median reduces problems with a rider already present
at clip start. Cancellation follows selection generations and never publishes
partial work as a completed analysis. Active source clips are protected by the
existing analysis cleanup guard. No-subject results are cached too; the UI reports
that no clear moving subject was found instead of presenting a timestamp as a
successful rider identification. A failed preview leaves ordinary review usable.

The scan runs in Reader, outside Tk drawing and the independent live-preview
process. Existing performance metrics include positioning time/decoded frames.
Re-selecting a restored CM-no-visual row runs the new positioning once, while
ordinary repeated clicks after positioning preserve the operator's frame.

Validation: 156 unit tests on both hosts and GUI checks for clips with no OCR or
prior bike analysis, empty predicted-time frames, two separate riders, cached
Previous/Next, cancellation, static video, long-clip target windows and late neural
completion. On real Elite clips 706, 707 and 710 the selected frames show riders
(frame 63, 62 and 16 respectively); first scans here took 0.7–1.1 seconds. A direct
motion-only scan of 764 found frames 20 and 75 without its neural index. Actual
identities still require review. Field validation added preview metadata only;
original frames, human decisions and protected backups remain unchanged.

## Later manual confirmations versus older ignores (November 11)

Elite lap 9, bib 4, capture 866 revealed an ignore-precedence bug. A human
confirmation was saved at display frame 18/89, but geometry associated it with a
previously ignored motion candidate. The comparison suppressed the newer manual
identification, leaving a missing row and a generic fallback video position.

Comparison now retains the bib review's modification time and applies source-key
rules in decision order. An older inferred candidate ignore cannot hide a later
explicit manual confirmation. A later explicit Ignore still hides that observation,
and re-confirming restores it. Machine/OCR alternatives remain suppressed as before.
The confirmed observation's saved source ordinal takes precedence over an estimated
motion centre, so this row opens at frame 18, not its candidate's frame 20 or the
start. No historical decisions are rewritten to produce this result.

Validation: 159 unit tests passed on both hosts, including ignore -> independent
manual confirmation, later explicit ignore -> re-confirm, and manual evidence
entered through Review bibs. The actual zbook9 database was opened in a headless Tk
check with session writes disabled: Elite final-lap 4 displayed matched/confirmed,
opened capture 866 at 18/89, showed a green bib overlay and disabled redundant
Confirm. No field reviews, frames or operator session settings were changed by
that check. Existing review and no-visual positioning checks also passed.

## Automatic review consistency safeguards (November 11)

The cause was an inferred geometry association being treated as authority over
an explicit later operator decision. This was not a failed save: ignored motion
candidate -> later independent manual identification -> geometric re-association
-> unconditional suppression in the comparison. The generic decision policy is
now centralized in review_resolution.py and runs on every comparison/refresh.

Additional safeguards automatically:

- Retain current human observations if candidate grouping would otherwise drop them.
- Keep independently confirmed bibs separate when one guessed track contains both.
- Preserve the human's source frame and marked bike box rather than replacing them
  with estimated detection geometry.
- Give confirmed human observations priority over closer competing OCR guesses.
- Apply resolved human evidence consistently to automatic positioning, so a stale
  candidate ignore cannot exclude a currently visible later confirmation there.
- Report reconciliations in `review_reconciliations` and the passings status.

Newer explicit Ignore decisions remain effective; undo/redo and the original audit
are preserved. This is automatic read-time reconciliation, without rewriting old
operator decisions or manufacturing new confirmations.

A repeatable read-only audit is available:

```
python -m tools.audit_review_consistency --db /path/to/racevideo.sqlite3 --day 2026-11-08 --output review-audit.json
```

Validation: 168 unit tests passed on both hosts. Auditing all six cached zbook9
events found 19 visible manual observations, one automatically reconciled
association, and zero accepted manual observations missing from passings views.
The actual Elite lap9/4 GUI check again showed green confirmation at frame18/89.
No human decisions, original frames or protected backups were modified by the audit.

## Group possible duplicates near a confirmed passing (November 11)

Nearby same-bib possibilities can now be folded under a confirmed passing, with a
**[+N grouped]** badge and **Show grouped** checkbox. Showing them restores their
individual selectable rows and explains why they were grouped. Switching back
returns selection to the confirmed parent. The option persists in review sessions;
an old saved selection that has become grouped resumes at its parent.

The default window is 30 seconds, within the same overall leader-lap column.
An unconfirmed OCR row can fold only if its observed
subject is the same as the confirmed sighting. Different physical tracks, bibs,
columns, separately confirmed sightings and rows with their
own video candidates remain available independently. The comparison's optional
`duplicate_seconds=0` disables grouping; Show grouped exposes all grouped rows.

This is a reversible presentation rule for visual evidence. Undoing the parent
confirmation automatically brings possible visual duplicates back into the main
list. Grouping never marks the extra observation confirmed or proves it is invalid.

Actual Elite final lap: Wakefield's confirmed CM passing 1217 is followed 28.598909
seconds later by unassigned CM passing 1218, with no video candidate. Current
presentation omits that unassigned read while retaining it in `race_passings`.

Validation: 173 unit tests passed on both hosts. Tk tests cover confirmation-driven
grouping, visible badge, Show grouped, explanation/selection, restored sessions,
undo restoring rows, column navigation and unchanged source reads/frames. The
six-event zbook9 consistency audit still reports no accepted manual observations
missing from the passings views.


## Race clock and front-wheel review (November 11)

Race elapsed time is calculated from the cached CrossMgr event start. The
camera-minus-CM offset is applied to camera footage once; CrossMgr timestamps
are already in the race clock. No race context falls back to labelled clock
time. The review image shows `Frame Race ...` below the large suggested bib;
wheel analysis can add `Finish ≈ Race ...` or a crossing bracket. These are
separate values. The passing-table time remains its CrossMgr passing/estimate
or visual observation time, not silently replaced by a wheel estimate.

`Track front wheel` draws a fixed dashed centre finish line and, when resolved,
a cyan front-tyre marker. Analysis runs separately and results are cached.
`Crossing frame` jumps to the first frame observed touching/past the line;
`Analyze wheels` retries with available bicycle-region assistance. A missing
measurement hides the marker rather than extrapolating it. Confirmation keys
still review identity; they do not certify timing or submit CrossMgr reads.
See FINISH_LINE_TIMING.md for calibration and detection limits.


Presentation correction: the visible yellow vertical line now follows the
front tyre; the fixed centreline and wheel circle are hidden. The left overlay
uses `M:SS` / `H:MM:SS`, no labels or milliseconds. Co-visible measured bikes
have individual yellow markers and bib/time rows. Detection remains experimental
for close groups; detailed timing/bracket evidence retains full precision.

## Opening frames and fixed headings

Lap headings now live in a separate fixed canvas. Vertical scrolling moves only
the rider rows; horizontal scrolling moves headings and their columns together.
Keyboard selection/reveal and saved scroll position continue to use the body.

When opening a passing with front-wheel tracking enabled, a source frame without
a wheel measurement is replaced for display by the nearest actually measured
frame of the same selected bike. This runs once when its analysis is available;
a source frame with a measurement stays in place. Scrubbing, changing zoom/pan,
or starting playback cancels pending automatic alignment. Reopening a saved
session preserves the saved review view. Neither source annotation nor passing
timing is modified just to change the displayed frame.

Verified against Elite Lap 6 bib 100, clip 808: source review displayed frame 12
has no wheel measurement; opening now selects displayed frame 13 automatically
and renders the measured yellow tyre line. Crossing frame still seeks frame 17,
the first observed past the line in its unresolved two-frame crossing bracket.
Regression checks cover fixed headings, horizontal alignment, automatic opening,
manual-scrub cancellation, keyboard review and session restoration.

## Single-screen compact passings

The main window now has a resizable left panel beneath the selected bib and race
time. It mirrors CrossMgr's concise grid: bibs only, lap number, leader lap time
and cumulative race time. Headers remain fixed on vertical scroll and align
with horizontal scroll. Cell colors and selected outlines match the detailed
review model. Names/status appear below the table on hover/selection. Start reads
remain available in Pop out; the compact grid starts at Lap 1 once laps exist.

Click a bib to open its matched/potential capture. Confirm/Ignore/Correct/Undo
buttons and existing Space, +/- bib entry, arrows and Ctrl-Z/Ctrl-R work without
a second monitor. An added bib uses an entry inside the main window. The video
moves to the right of the panel; its source coordinates and wheel timing are
unchanged. The splitter and compact scroll position persist with the session.

- **Current CrossMgr race** reads the current GUI race via `bridge.identity` and
  `bridge.snapshot`, then analyzes its private copy through `race.inspect` /
  `race.review`. This does not send edits or reads to CrossMgr. While running,
  it refreshes about every 15 seconds. Clicking a current-race bib for video
  review keeps following that race unless archive mode is explicitly selected.
- Uncheck **Current CrossMgr race** to select a date, event and category. Load
  reads the local cache; Import date imports saved CMNs through MCP. Event choices
  span the selected date's competitions. Category filtering uses the existing
  event-scoped model; bib identity is not shared across events.
- **Pop out** shows the existing detailed window for a second screen. Closing
  that window returns to compact-only use. The toolbar **Passings** checkbox
  hides/shows the panel; ordinary thumbnail browsing is restored when both
  passing views are closed.

An unavailable/ambiguous/unstarted CrossMgr GUI is shown explicitly, with the
current-race grid cleared rather than relabelling an archive as live. A current
race must have a saved path and recorded start. For multiple GUI instances,
`CROSSMGR_INSTANCE` or `CROSSMGR_LIVE_RACE_PATH` selects one explicitly (also
`instance` / `live_race_path` in the CrossMgr client configuration).

Finished GUI races are cached after the first snapshot. Press Live again (or
turn Current race off/on) to explicitly refresh post-race GUI corrections.
Running races reuse unchanged model analysis for up to 60 seconds, then recheck
workbook metadata. Snapshot inputs are normalized to the original race path for
cache identity, preserving original snapshot inputs as provenance; different
private snapshot filenames do not create duplicate events/source versions.
CrossMgr owns its private snapshot artifacts; RaceVideo does not delete them.

SQL, MCP and snapshot analysis run in background threads, not Tk callbacks.
Compact grid items are rebuilt only when visual fields change; click targets
still refresh to current capture dictionaries when a redraw is unnecessary.
Hidden detailed grids are not repainted. Performance records
`compact_passings_draw_ms` alongside existing capture/preview metrics.

Validation: 200 unit tests and both compact/detailed GUI tests. Compact tests
exercise snapshot follow, offline state, capture click, source metadata refresh,
confirm/undo/add, date/event/category selectors, pop-out/hide/reopen, pane width
and session restore. Real Elite data rendered on zbook9 in a single 1600×1000
window: 229 displayed passing cells, bib 100, clip 808, measured frame 13.
`data/validation/zbook9-compact-elite-review.png` is the copied screenshot.
No live CrossMgr GUI was open during this development check; live snapshot
handling was tested with simulated MCP replies rather than race traffic.

### Named MCP targets

The compact panel's MCP target selector persists its choice in
~/.config/racevideo/crossmgr.json (override with RACEVIDEO_CROSSMGR_CONFIG).
The configuration supports a selected_target name and a targets object mapping
names to configurations. Existing flat configurations remain supported.
Each target supports url, token_file, root, timezone, timezone_file, instance,
and live_race_path. Top-level settings supply shared defaults.

ContextForge uses the virtual server's streamable HTTP URL and its own bearer
token file. If tool names differ, set tool_names to a mapping from bridge.identity,
bridge.snapshot, race.inspect, and race.review to their exposed gateway names.
No gateway discovery is performed. CROSSMGR_TARGET is an environment override;
remove target/URL/token environment overrides before using the GUI selector.

Changing target waits for outstanding requests to finish, clears the displayed
model, and follows the new current race. Subsequent archive imports also use the
new target. Cached events are retained. Cloned credentials and paths must be
verified on the destination before use.

### Unranked observations and quick dismissal (November 14)

Visual-only entries are displayed on separate unnumbered rows. Raw CM reads
without an assigned lap remain cached as source evidence but are omitted from
review and do not consume video matches. Numbered CrossMgr positions remain
aligned across lap columns, in CrossMgr time order. Compact and detailed views
use the same layout and navigation. Delete (or keypad Delete) ignores the selected candidate
and advances, from either main or passing window; Ctrl+Z restores it. Entry
controls retain ordinary text editing. Video is not deleted. See
[CROSSMGR_VIDEO_CORRECTIONS.md](CROSSMGR_VIDEO_CORRECTIONS.md) for the Elite
capture-764 fragmentation finding and the MCP write-back contract assessment.

### Display-only review enhancement (November 14)

The review toolbar's **Display…** controls adjust brightness, contrast and
sharpness for the on-screen saved-clip preview. Adjustments run on the bounded
display image outside Tk's thread and persist in the host-local UI session.
The button visibly reports an adjusted state and the dialog provides Reset.
Saved JPEG frames, thumbnails, OCR input/evidence, wheel analysis and exports
remain unchanged. Enhancement can expose encoded shadow detail but cannot recover
clipped highlights/blacks, missed focus or motion blur.
