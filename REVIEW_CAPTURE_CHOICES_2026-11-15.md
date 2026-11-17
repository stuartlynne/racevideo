# Elite finish: capture choice and fragmented motion preview

November 17, 2026. Investigated on whiskey's writable clone of the November 15
recordings. Protected import backup and laptop originals were not changed.

## Actual footage

| Expected rider | Capture | Frames | Visual check |
| --- | --- | --- | --- |
| 6 | 1968 | 55 | Foreground rider in green; frameplate 6 |
| 5 | 1969 | 54 | Separate rider in black; frameplate 5 |
| 2 | 1970 | 52 | Later rider in red |

Capture 1969 starts about 5.14 seconds after 1968. CrossMgr's reads for 6 and 5
are about 4.39 seconds apart. These are different timing reference points; no
camera/reader clock offset or finish time was calibrated by this fix.

## Why 5 opened on 6

When no bib observation matched a CrossMgr passing, comparison prepended every
nearby indexed motion/bike candidate before unindexed clips. Capture 1968 had
cached motion candidates; 1969 had not yet been indexed. The broad match window
included both, so 5 opened on the indexed previous rider instead of its own clip.

Candidate ranking now compares indexed and unindexed clips together. It
penalizes a clip more than 250 ms nearer another scored CrossMgr passing, then
uses clip interval distance and subject quality/time. Explicit matches to another
rider are also deprioritized. All alternatives remain available. A clip covering
multiple close CrossMgr times remains eligible for each, rather than being
allocated exclusively to one rider. This is review positioning, not identity
recognition or proof of a finish time; nothing becomes confirmed from proximity.

## Why two question marks showed the same rider

Motion analysis 274 split 6 into two tracks: frames 12–20 and 31–34. The
silhouette disappeared briefly around the median background reference, then
reappeared too far from its previous position for the old nearest-position gate.
Constant-velocity prediction bridges this brief loss. New reports are tagged
`motion-preview-v2`; cached v1 reports and old audit identifiers are retained.
Static/inconclusive v1 and v2 reports remain cached, avoiding repeated scans.

Only captures 1968 and 1969 were reindexed in the working copy, using CPU/Pillow
motion analysis, after checking for bib decisions, visual decisions, undo history
and concurrent jobs. Neither had protected decisions. Old reports remain in
`bike_analyses`; one v2 passage now covers 6, and a separate v2 passage covers 5.
No JPEGs, OCR observations, human identity reviews or CrossMgr reads were changed.
The local window was reopened on display :0 with CM bib 5 selected, capture 1969,
zero-based frame 22 (display frame 23), and the visible plate checked.

Initially the same unassigned visual candidate was displayed twice: as the
CM row's first review suggestion and as a separate `?`. Unique primary,
non-uncertain unknown candidates are now grouped under that CM suggestion by
default. The CM row stays missing/yellow, unconfirmed, with zero identity matches.
The sidebar's Show grouped candidates toggle exposes the raw row. Shared or
ambiguous suggestions, uncertain/secondary tracks, named observations and
separate extra subjects remain visible. No identity is inferred from grouping.

## Validation

220 unit tests pass, including new regressions for indexed-previous versus
unindexed-next clips, a shared group capture, and a briefly lost silhouette.
Existing left/right passage, separate successive riders, static caching and
cancellation tests pass. The real derived-data proposal order is now 1968 for 6,
1969 for 5, and 1970 for 2. The actual display :0 window was checked on plate 5.
Contact sheet, corrected screenshot and data-change audit are under
`/raid4tb/sl/racevideo/tests/2026-11-15/finish-*` (not tracked raw race data).

Display grouping validation: 223 unit tests pass. A dedicated GUI smoke verifies
that the raw candidate can be shown/hidden, a distinct extra subject stays visible
and no identity decision is recorded. Grouping changes no database observations.

## Two riders in one clip: Lap 8

Capture 1954 contains both 6 and 5. Its original motion report 268 correctly has
two subjects: zero-based frames 17 and 27 (display frames 18 and 28). Both camera
representative times fall after both CM reads, so independent nearest-time
selection offered the first subject for both expected riders. This also made the
raw rows look like unassociated extras. This is not the fragmented-track case.

For a shared clip with equal counts of expected unconfirmed riders and clear
primary unknown subjects, review proposals now follow chronological one-to-one
order. Each chosen subject must already be an eligible capture choice for that
CM row. Tied times, missing choices, uncertain tracks, or unequal counts do not
force an ordered pairing. Raw alternatives remain available and no identity is
confirmed by this display ordering.

The real Lap 8 proposal is now 6 at frame 18 and 5 at frame 28, both in 1954;
the raw `?` rows are grouped behind Show grouped candidates. No detector reports,
images, manual decisions or race times were changed for this fix. The local GUI
was reopened on display :0 with 5 at frame 28 and its visible plate checked.
225 unit tests and the shared-capture and original grouping GUI smokes pass.
