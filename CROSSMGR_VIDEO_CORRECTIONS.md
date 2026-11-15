# Visual-only passings and CrossMgr corrections

November 14, 2026. This is a contract review and implementation plan, not an
announcement of a write-back button. RaceVideo's CrossMgr client remains read-only.
No competition files or running CrossMgr race were edited during this work.

## PartyCross Elite discrepancy

The November 8 derived review database has 14 unmatched `?` candidates from
capture 764 in Lap 4. They come from detector analysis 3, a `recall-v2` report
containing 28 raw tracks over this 143-frame clip. The 14 candidates are centred
at zero-based frames 65–85. Nine are marked uncertain; several contain just one
to three supporting frames. Full/partial bicycle boxes overlap in time and
fragment as the rider enters and exits. Frames 66, 75 and 86 (one-based) show one
rider traversing this interval. This is detector fragmentation, not evidence of
14 additional entrants. The clip contains other activity outside that interval.
A contact sheet is retained at `data/validation/clip764-fragmentation.jpg`.

The screenshot's Lap 8 `?` has the same visual-only semantics, but that exact
candidate is not present in this local derived snapshot. The number/date of
completed bike analyses or operator decisions can differ between laptop and
whiskey. Do not invent a bib or assume all visual-only observations are false.

The shared layout reserves numbered positions for CrossMgr passings with an
assigned lap. Visual-only evidence (including named bibs) occupies separate
unnumbered rows. Raw CrossMgr reads without an assigned lap remain in the cached
source evidence but are omitted from the review tables and do not consume video
matches. Other columns leave visual-only rows blank, preserving rank alignment
across laps. Numbered order uses CrossMgr time, not the frame selected for visual
review. Both compact and pop-out tables and keyboard navigation share this layout.

Delete/keypad Delete now performs the same audited Ignore decision as minus and
advances to the next entry. This hides a candidate from the table, preserves the
video, and can be undone with Ctrl+Z. Entry/Text controls keep normal Delete
editing behavior. It is not capture deletion. No existing candidates were
silently merged or discarded: false negatives remain harder to recover than
false positives. A later tracker improvement should stitch compatible fragments
with spatial/velocity evidence, preserve raw tracks and not merge two close riders.

## Existing CrossMgr MCP contracts inspected

Source: `crossmgr_mcp/operations.py`, `server.py`, and CrossMgr `mcp_bridge.py`.
Endpoints are available in the current local source; verify capabilities on the
actual race host before proposing an edit.

| Situation | Existing operation | Limitation |
| --- | --- | --- |
| Completed CMN, rider already exists in native race model | `race.correction.preview(path, edits, reason, trusted_pickle=True)` then `correction.apply(id, approved=True)` | Writes a separate corrected CMN in service state; original is not replaced or adopted automatically. |
| Active/completed GUI, existing native rider | `rider.edit.preview(bib, edits, reason, instance)` then `rider.edit.apply(id, approved=True)` | Requires enabled bridge writes, exact GUI instance/race, revision validation and operator approval. Applies on GUI thread. |
| Existing native rider explicitly marked NP | Batch `status=Finisher` and `add_estimate` | Adding a time alone does not change the rider status. Other sporting statuses must not be overwritten automatically. |
| Bib only in workbook/registration roster, absent from `race.riders` | Not supported by these edit tools | Both paths reject an absent native rider, even if registration is known. |
| Bib not registered in the selected event | Separate registration/event decision needed | Do not manufacture a rider identity or silently choose a different event. |

For an existing NP rider the edit batch can be:

```json
[
  {"operation":"status","bib":24,"status":"Finisher"},
  {"operation":"add_estimate","bib":24,"seconds":123.456,
   "coordinate":"rider_elapsed","provenance":"Add"}
]
```

This is a manual/video correction (`Add`, or explicitly `Split`), not an RFID
read. There is no need to synthesize an EPC or send a fake hardware tag message.
The API currently calls the coordinate `rider_elapsed` but passes it straight to
native `rider.addTime`: for a mass-start race it is **seconds since the race's
start**, including any category start delay. Do not subtract a category offset
again. TT coordinates need separate treatment; RaceVideo currently refuses TT
imports rather than guessing that conversion.

Approval requirements belong in a concrete operator preview, not an implicit
side effect of confirming a bib. A confirmation establishes identity evidence;
it must not silently create a CrossMgr timing read.

## Functionality still needed

1. Add a registration-aware passing operation shared by saved/live paths. It
   should permit creation of a native rider only after verifying exact bib
   membership in the selected event's linked registration roster. Reuse native
   CrossMgr rider creation, and capture category/workbook/model revisions.
2. Require a positive explicit race timestamp, source/provenance and private
   reason. Make the command idempotent and detect duplicate/nearby existing reads.
   Do not automatically change DNS/DNF/DQ/Pulled policy.
3. Live: keep GUI-thread application, expected instance/race and stale-preview
   checks, durable command IDs and unknown-outcome reconciliation.
4. Offline: stage and reopen a corrected CMN as now. Provide an explicit workflow
   for adopting that file and refreshing RaceVideo's cached event source; simply
   creating a corrected copy does not update a GUI open on the original file.
5. RaceVideo: an operator-only "Prepare CrossMgr passing" action after bib
   confirmation and finish-time review. Show bib/name, event/category, existing
   reads/status, proposed time and uncertainty. Choose saved or GUI target from
   provenance, not from an unrelated current race on that host.
6. Use the estimated front-wheel/finish-line crossing time, with explicit camera
   clock offset/calibration and frame interval uncertainty. `cell.at_ns` may be
   the CrossMgr suggestion itself, or merely a candidate's representative frame;
   neither is proof of the wheel crossing. Do not feed a prediction back as
   independent video evidence. Preserve the evidence frame/clip and conversion.
7. After approved application, re-read native results and refresh the event
   cache. Keep visual review/audit history independent of CrossMgr corrections.

## Validation in this change

- RaceVideo unit suite: 204 tests passed (including new layout invariants).
- A new GUI smoke covers unnumbered candidate rows, Delete from the main video,
  automatic next candidate selection, undo, unchanged saved frames and pop-out.
- Disposable CrossMgr native NP rider: status+Add succeeds; absent model rider
  is refused. No source file was involved.
- Existing offline staged-correction/reopen/SeriesMgr test passed on disposable
  fixtures; existing running GUI rider-edit/preview/apply test also passed in its
  isolated Xvfb instance. These validate existing primitives, not the proposed
  registration-aware operation or a RaceVideo write-back integration.
