# Reviewing race evidence

## Dates and bib filters

The thumbnail bar opens on **Today**, using the computer's local calendar date.
Choose a saved date from the Date dropdown, type `YYYY-MM-DD`, or select **All
dates**. **Today** returns to the current day and follows midnight rollover.
Clips belong to the date of their first saved frame, including pre-roll. Changing
the browser does not change the recorder's capture date or interrupt capture.

Enter bibs such as `333` or `333, 042` and press Enter or **Filter**. Leading zeroes
are significant. Multiple bibs match **any** entered number. Clear the entry to
remove the bib filter; **★ only** restricts the result further to starred clips.

Matching uses observations from the **latest completed OCR run for each clip**,
with saved operator decisions applied. Confirmed/corrected/manual bibs remain
available after a rerun; rejected observations are excluded from matches.
A running/failed rerun does not discard the previous completed evidence. Both
single and repeated candidates can match. Unscanned clips cannot match; absence
of a match does not establish that the rider was absent. Thumbnail labels show
candidate numbers, and the count is matching **clips**, not verified laps.

**Sightings…** lists candidate encounters for the active date/filter, in timestamp
order, with the interval since the preceding sighting of that bib. One clip can
contain multiple encounters; noisy/fragmented OCR tracks can also produce several
observations. Double-click a row to review its original source frame. This can
support a lap-review investigation; it does not automatically confirm race results.

Explicit source navigation (including MCP and `--review-clip`) selects the clip's
date and clears incompatible filters if the clip is outside the current browser.

## Confirming and correcting bibs

Open **Review bibs…** for a saved capture. Select a candidate to display its
original source frame, highlighted region and machine crop. The table groups
alternatives by encounter; several riders can be confirmed in the same capture,
even if the tracker incorrectly grouped them together.

- **Yes — correct** confirms the selected number.
- **No — reject** excludes that observation from the bib filter and sightings.
- Enter one to three digits in **Bib**, then **Correct selected**, to retain a correction.
- Scrub to an appropriate source frame, enter a number and click **Add bib at
  displayed frame** for a rider the OCR missed. This also works without an OCR run.
- **Clear review / remove manual** undoes the current decision or manual entry.

Leading zeroes are retained. Manual evidence is anchored to the actual displayed
frame, including while decoding catches up with scrubbing. Thumbnails distinguish
human-confirmed numbers (✓) from unreviewed candidates (?). Reviews affect retrieval,
not official timing/results. A confirmation states that this bib is present in
the evidence; it does not establish an exact finish-line crossing or lap count.

Original OCR observations, alternatives and reads remain unchanged. Current
decisions live in `bib_reviews`; `bib_review_history` records changes and resets.
A new OCR run cannot erase an earlier operator confirmation. New hypotheses from
a rerun can still need review, particularly where several riders overlap.

For the November 8 field test on whiskey, run **`racevideo-field-review`** (also
in the application menu as **RaceVideo — 2026-11-08 review**). It opens the writable
test store, selects that day's footage and does not start a camera. The original
175 GB snapshot remains protected; see [DATA_SAFETY.md](DATA_SAFETY.md).

On zbook9, the same completed November 8 reports are now imported into the normal
recording database. Open its regular RaceVideo launcher and select **2026-11-08**
in Date. This does not require another OCR pass or the whiskey-only launcher.

## Zoom and pan saved video

| Input in the main video pane | Action |
|---|---|
| Wheel / two-finger trackpad scroll | Zoom around the pointer |
| Left drag while zoomed | Pan |
| `+` / `−`, or toolbar buttons | Zoom around the centre |
| `0`, **Fit**, double-click | Restore Fit |
| Escape while zoomed | Restore Fit, remain in review |
| Escape while fitted, or **Live** / `L` | Return to Live |
| Left / Right | Step frames; in the thumbnail strip, select clips |
| Page Up / Page Down in strip | Move by a page of clips |

Zoom ranges from Fit (100%) to 1600%. It persists while scrubbing/playing the same
clip and resets on selecting another clip. This uses original saved JPEG pixels,
not an enlarged low-resolution preview. Only the visible region is enlarged;
rendering stays off the Tk thread and output is limited to the viewport. OCR area
selection takes precedence over panning. Entry fields retain their normal editing
keys. Native pinch gestures vary with Tk/platform; scroll, buttons and keyboard
are the supported portable equivalents.

The time/frame caption describes the **displayed source frame**, even if playback
or a scrub request is waiting for rendering. A newly selected clip shows Loading
until its own image arrives, preventing a previous clip's pixels appearing under
a new clip label. Source receipt times are not calibrated finish-line times.

## Assigning manual bibs to individual bikes

In **Review bibs…**, scrub to a useful source frame and click **Mark bike…**.
Drag a rectangle around the intended bike in the main image. Enter its bib and
optionally verify **Bike order in capture** (1, 2, 3…), then **Add bib at displayed
frame**. Repeat for another bike, even if it is visible in exactly the same frame.
The next mark suggests the next unused order; the operator verifies that order.

The saved entry retains a separate box, source ordinal/time and order in its
audit provenance. Selecting it highlights that bike on its saved frame. A mark
cannot be saved on a different frame accidentally; return to its frame or clear
and redraw it. Unmarked frame-only manual entries remain supported and are not
treated as automatically associated bike tracks. These order numbers describe
the capture, not race laps or calibrated finish order. Duplicate order numbers
are rejected until the earlier entry is edited or removed.

The passings window has equivalent **Mark bike in main image…** and order controls.
For a marked bike at a different frame from an existing OCR observation, add
separate manual evidence in Review bibs; the app does not attach a box to the
wrong source frame. Raw OCR and original video remain unchanged.

## Quiet gaps in future motion captures

**Maintenance → Motion quiet-tail limit…** sets an earlier quiet close for future
GUI recorder starts (default 1.0 s; 0 restores the full configured post-roll).
CLI equivalent: `--quiet-close 1`. The effective quiet tail is capped by the
post-roll; the shorter 0.2 s motion indicator gap is unchanged. Renewal of motion
before quiet close keeps the same capture; after close it starts another capture
with normal pre-roll. Small boundary overlaps from pre-roll are possible.
Existing clips are not split or rewritten. A motion ROI cannot certify that the
entire image is bike-free; riders just outside it can still appear in saved tails.

## Stars and date cleanup

Select a clip and click **☆ Star clip**; click **★ Starred** to remove its star.
Stars persist in SQLite across restarts and appear on thumbnails. They protect
clips from date cleanup. They do not change the video or OCR evidence.

Date deletion is deliberately absent from the main toolbar. Choose one date,
then **Maintenance → Delete recordings for selected date…**. The app computes a
preview showing the date, database path, capture/frame counts and protected counts.
Deletion is disabled until you type the exact displayed phrase, for example
`DELETE 2026-11-08 786`, then explicitly activate the permanent-delete button.
Cancel is initially focused; Enter in the text entry does not submit deletion.
Cleanup applies to the **whole selected date**, even when bib or star filters hide
some clips. All Dates cannot be deleted in one action.

Confirmed cleanup:

- Removes only the specific unstarred clips included in the preview, together
  with their frames, thumbnails, metadata and OCR results.
- Rechecks stars and queued/running OCR work inside the deletion transaction.
  Newly starred or busy clips are retained. Clips belonging to an active all-day
  OCR batch remain protected until the batch completes, including imported clips.
- Keeps clips arriving after the preview and clips from every other date.
- Never reuses deleted clip IDs for new footage.

The action is permanent; cancel the confirmation to retain everything. No existing
recordings were deleted during development; cleanup tests use temporary stores.

SQLite makes deleted pages available for reuse, so the database file **may not
shrink immediately**. There is no automatic retention or online VACUUM task.
Physical compaction should be done during maintenance with recording and workers
stopped, using normal SQLite tooling/backups. Older running recorders must be
restarted before cleanup so they honor the durable clip-ID allocator.

## Agent access

MCP adds `clips.dates`, `clips.star` (with command-ID reconciliation) and
`bibs.sightings`. `clips.list` accepts optional `day`, `bibs` and `starred_only`;
omitting the date preserves its existing all-date API behavior. `clips.info`
includes the persistent star, effective `tag_matches`, original
`machine_tag_matches`, and `bib_reviews`. Date cleanup remains an operator GUI action.

## SQL associations

Each segment can match multiple riders, and each rider can match multiple
segments. Schema v11 preserves the raw `video_tag_matches` lookup and uses
`reviewed_video_tag_matches` for effective matches; filtering uses the latter.
See [SQL_MATCHES.md](SQL_MATCHES.md) for one-bib, multi-bib
and local-date queries, plus the distinction between summary matches and detailed
encounters. Shared videos appear only once in a combined thumbnail/API result.

OCR currently runs **on request** with Read plates or MCP `ocr.start`, not
automatically for each new motion segment. Updated thumbnails distinguish not
scanned, queued/running, no candidates and failed scans. Qualified competing
number hypotheses are retained as candidates; even a repeated OCR result can
be wrong. Use source frames and event/start-list context when reviewing them.

## Neural OCR and legacy test controls

Choose **Neural OCR** in the backend dropdown, then **Read plates**. The optional
Paddle runtime must already be installed: `.venv-ocr-paddle` on zbook9 (CUDA), or
`.venv-ocr-cpu` here. The worker uses all original frames, rider/bicycle proposals,
text detection and four recognition orientations. It runs outside Tk, with native
threads/affinity limited to two distinct physical CPU cores. It does not select
the experimental AMD/Vulkan environment.

The neural search area is saved separately from the old Tesseract test area.
Its default broad normalized region is `[0.05, 0.40, 0.98, 0.90]`; adjust it for
the actual scene. This is a scene-specific starting point, not automatic plate
localization across the entire image. Job parameters freeze the selected area.

The corrected one-through-three-digit field sweep uses two isolated CUDA workers
on zbook9, each with one CPU core. **Day OCR N/786** shows results imported so far; **Day OCR complete ·
786 clips** marks completion. Completed captures can
be reviewed while the sweep continues. A queued/running scan leaves previous
completed evidence visible. See [FIELD_OCR_RUN_2026-11-08.md](FIELD_OCR_RUN_2026-11-08.md)
for source, progress and recovery details.

One-, two- and three-digit numbers are accepted without padding or integer
conversion. See [CONTEXTUAL_OCR.md](CONTEXTUAL_OCR.md) for the short-number fix,
the new full-day pass and the planned event/lap-context ranking layer.

**Tesseract** retains the earlier wheel-test implementation described below.

Read plates and MCP `ocr.start` use the saved OCR area. The OCR area is independent
of the motion rectangle; use Select OCR area to restrict analysis to a useful
part of the image. The service freezes region and rotation choices in each job,
including requests made while the GUI is closed. Explicit MCP `crop`/`rotations`
arguments override those defaults.

**Upright only (test)** skips the 180-degree OCR pass. It is off by default;
uncheck it for normal race tests. This does not implement arbitrary-angle label
recognition. Existing recordings and earlier OCR runs remain available when a
new restricted scan replaces the current match summary.

For the November 5 wheel test on zbook9, the saved area is normalized
`[0.34, 0.35, 0.60, 0.56]`, covering the top of the wheel, with upright-only
enabled. Motion detection and recording retain their existing region/settings.
