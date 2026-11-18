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

## Lap 8, 60 and the walking bystander

Capture 1958 has two real moving subjects: a bystander (motion:1, frame 5)
and the cyclist (motion:2, frame 20). The generic motion preview cannot classify
bicycles. Its first subject was nearer the CM time, so the review opened on the
walker and showed the cyclist separately as `?`.

The saved trigger is at frame 16, with the cyclist inside the recorded capture
ROI and the walker outside it. This supports the cyclist, rather than the
walker, triggering this particular capture; the exact contributing pixel mask
was not stored, so this is not proof of the sole trigger cause.

Comparison now uses observed track centres and the saved capture ROI as a soft
review preference. A subject observed inside that zone ranks ahead of outside
motion within the same candidate clip. Missing/invalid geometry adds no bias.
Outside-zone candidates are not discarded or grouped as clear CM suggestions;
walkers or other subjects inside the zone still require operator judgment.
Generic motion rows are labelled Unidentified moving subject, not detected bikes.

The real proposal is now 60 at frame 20; the walker remains separately reviewable
at frame 5. No images, detector IDs, operator decisions or CM data were edited.
228 tests and a finish-zone GUI smoke pass. The local :0 review was reopened
on 60's cyclist candidate. This is geometric ranking, not a semantic bike detector.

## Completed Sunday OCR exposed detector-track proliferation

The local batch covered all 828 Sunday clips and 51,873 frames without failures.
It produced 1,187 OCR observations in 420 clips; these are candidate counts, not
accuracy or participant totals. Full-frame object detections were saved alongside
OCR, permitting tracking to be rebuilt without another neural inference run.

Recall-v2 treated every bicycle box down to confidence 0.15 as a possible track.
Overlapping boxes on bicycle parts and stationary background objects generated
many independent tracks. Clip 1850 alone had 75 raw tracks; Elite had 2,260 `?`
rows. The earlier primary-stop heuristic affected navigation, but did not prevent
all those low-quality tracks from becoming independent table rows.

Passage-v3 tracks confidence >=0.4 bicycle proposals after suppressing nested
boxes, uses sustained moving trajectories as primary stops, and groups the weak
raw tracks for optional inspection. Original analysis IDs and raw track keys are
retained. Weak-only temporal intervals still get an unresolved stop. Two close
riders and an exit followed by a later return are explicitly tested. Weak OCR
cannot independently mark a CrossMgr passing matched; human reviews stay visible.

All 828 local derived bike reports were rebuilt with `tools/rebuild_bike_tracks.py`.
Elite now has 215 default rows, including 53 unknowns (previously 2,435 / 2,260).
All 19 confirmed table entries were retained; hashes of the five human review and
history tables were unchanged. Before/after derived reports and summary live in
`/raid4tb/sl/racevideo/tests/2026-11-15/tracking-v3-applied/`. The protected original,
images, OCR observations, CrossMgr cache and operator decisions were untouched.

Real checks: clip 1954 retains two primary riders at ordinals 17 and 27; clips
1958, 1968, 1969 and 1970 each have one primary stop. Clip 1850 has six proposed
primary tracks rather than 75 default rows; its overview shows multiple close
riders. The remaining proposals are not asserted to be perfectly deduplicated.
Occluded riders and detector dropouts remain uncertain, and raw evidence can be
expanded using Show grouped / weak candidates.

## Lap 2 regression: five riders in one long capture (1872)

The v3 row reduction alone was inadequate. Seven strong tracks still included
exit-only fragments of the first two riders, and 5/6 OCR was missing from the
table despite repeated high-confidence raw reads. The label tracker tried to
follow tiny glyphs moving much farther between frames than their own dimensions.

V4 uses trajectories crossing or approaching the centre as primary stops. Boxes
first detected moving away beyond the line stay in raw evidence; a return after
exiting and approaching riders at a clip boundary remain separate review targets.
Physical rider trajectories now associate repeated OCR patches instead of relying
on glyph continuity. Qualification requires at least three different frames and
non-stationary patches. Multiple rotations of one frame are not multiple votes;
6/9 and 60/09 alternatives remain ambiguous rather than automatically resolved.

For clip 1872, actual primary review ordinals are 20, 24, 42, 55, 79 (display
21, 25, 43, 56, 80), corresponding to 5, 6, 2, 1, 60. Table positions retain CM
order. Rider 1 remains an unconfirmed suggested identity: only one strong raw 1
read exists, on a different trajectory, so no repeated 1 OCR is manufactured.
5 is supported across 10 frames; 6 across 6 frames. Four independently qualified
OCR numbers now anchor the other four bikes; the remaining CM row offers the
fourth physical bike instead of repeating the first bike's frame.

The real saved per-frame detections are now a regression fixture. The integration
test asserts the five table rows in the expected order, distinct review positions,
no extra unknowns, and no automatic manual confirmation. Display defaults for
unconfirmed matches now use the physical centre frame; the underlying best OCR
evidence frame and crop are retained.

828 derived reports were rebuilt locally; 77 newly supported observations were
appended to their original OCR runs, leaving old observations intact. Audit and
preimages are in `tracking-v4-applied/`. All five human-review/history table hashes
are unchanged. Elite currently has 201 default rows, including 34 unknowns, with
all 19 confirmed cells still present. These aggregate counts are operational
checks, not an assertion that every remaining track/identity is correct.

## OCR 9 duplicated the 60 review proposal in laps 6 and 8

OCR observations 3158 (clip 1927, 3 supported frames) and 3171 (1958, 5 frames)
read a small partial/rotated patch as 9. Both belong to the exact primary physical
tracks already offered under CM 60 in their respective laps. There is no scored
9 in this event. The prior grouping policy handled unread `?` proposals but left
named outside-roster OCR as a separate visual-only rider, duplicating the passage.

Grouping now includes outside-roster alternatives on a unique, clear primary
proposal for the same track and lap. The original 9 values/crops remain untouched
and inspectable through Show grouped / weak candidates. Parent 60 stays yellow,
missing and unconfirmed, with a visible OCR conflict warning. No automatic
replacement, confirmation, appearance training or timing update occurs.

An outside-roster rider on another track, a shared/ambiguous proposal, an accepted
human extra, or a mixed alternative containing an actual roster bib is not hidden
by this rule. Source roster exclusion alone is insufficient to group a row.
Unconfirmed extra review frames also use the physical centre, with the original
best OCR ordinal retained separately, avoiding a centre-frame box over a later
OCR frame. Real 1927/1958 checks give display frame 20 for each proposal and no
separate default 9 rows; raw and manual/history tables are unchanged.
