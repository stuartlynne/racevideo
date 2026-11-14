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

Matching uses observations from the **latest completed OCR run for each clip**.
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

## Stars and date cleanup

Select a clip and click **☆ Star clip**; click **★ Starred** to remove its star.
Stars persist in SQLite across restarts and appear on thumbnails. They protect
clips from date cleanup. They do not change the video or OCR evidence.

Choose one date and click **Clean up date…**. The app first computes a concrete
preview, then asks for confirmation with clip/frame counts and protected counts.
Cleanup applies to the **whole selected date**, even when bib or star filters hide
some clips. All Dates cannot be deleted in one action.

Confirmed cleanup:

- Removes only the specific unstarred clips included in the preview, together
  with their frames, thumbnails, metadata and OCR results.
- Rechecks stars and queued/running OCR work inside the deletion transaction.
  Newly starred or busy clips are retained.
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
includes the persistent star. Date cleanup remains an operator GUI action.

## SQL associations

Each segment can match multiple riders, and each rider can match multiple
segments. Schema v8 persists unique pairs in `video_tag_matches`; filtering uses
that indexed lookup. See [SQL_MATCHES.md](SQL_MATCHES.md) for one-bib, multi-bib
and local-date queries, plus the distinction between summary matches and detailed
encounters. Shared videos appear only once in a combined thumbnail/API result.

OCR currently runs **on request** with Read plates or MCP `ocr.start`, not
automatically for each new motion segment. Updated thumbnails distinguish not
scanned, queued/running, no candidates and failed scans. Qualified competing
number hypotheses are retained as candidates; even a repeated OCR result can
be wrong. Use source frames and event/start-list context when reviewing them.

## OCR region and orientation test controls

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
