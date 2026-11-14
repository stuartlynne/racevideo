# Variable-length bibs and recurring-rider context

Updated November 9, 2026, after the operator identified bib 24 in capture 877.

## Implemented: one through three digits

The neural recognizer already recognizes general text. The original code applied
an exact three-digit filter **after recognition**, so it could discard a perfectly
good `24` result. OCR filtering, encounter consensus, import, GUI review/correction,
manual additions, bib queries and tuning start-list validation now accept ASCII
strings of one to three digits. Leading zeroes are preserved: `24` and `024` remain
different evidence strings until an event-specific mapping explicitly resolves them.

Schema v11 broadens the operator-review CHECK constraint atomically, preserving
review IDs, source observations, decision history, video and effective matches.
Metadata backups were taken before migration, alongside the retained full original
video snapshots. The source sensor images have not been changed.

New neural runs use `paddle-v5-rider-native-v2`, with `number_lengths=[1,2,3]` in
job parameters. New Tesseract runs use v5. The model weights are unchanged; this
is a filtering/validation correction, not new neural training. The legacy
Tesseract proposal heuristics remain primarily designed for grouped digits;
the neural backend is the validated path for the real two-digit example.

Capture 877, GUI frame 13, visibly contains **24**. A new all-frame CUDA scan
recognized it on eight distinct source frames (GUI frames 14, 15, 18, 19,
21–24), producing one repeated-candidate encounter. The standard application OCR
worker has also run on this clip in both normal review databases. Original
three-digit-only OCR runs are retained as history.

The previous shutter-yield report applies to **three-digit-only output**.
Different bib lengths between race groups are an additional confound. Selected
correct examples at exposure setting 4 still establish that the setting was usable;
the old percentages do not measure performance across every bib length. In the
limited new diagnostic, early captures 110 and 160 still had no qualified
candidates after allowing short numbers; the filter is not the only limitation.

## Running: full-day rescan with the corrected rule

Batch `5f06c57afcde6d0645ffb86d` covers the same 786 November 8 race clips and
90,679 original frames. It uses the protected zbook9 export read-only, two CUDA
workers and one physical CPU core per worker (0 and 2). This pass does not use
AMD inference. A frozen copy of its analysis code is in
`/home/sl/racevideo/data/analysis-20261109/short-day-code` on zbook9.

- GPU job: `racevideo-day-ocr-20261108-v2.service` on zbook9.
- Reports: `data/analysis-20261109/short-day/` on zbook9.
- Laptop importer: `racevideo-day-import-20261108-v2.service`, writing the normal
  `~/.local/share/racevideo/racevideo.sqlite3`; cache/log under `short-day-import`.
- Whiskey importer: same unit name on whiskey, writing the existing local test
  copy; reports are `data/field-tests/2026-11-08/short-day-results/`.

Importers pull and validate atomic clip reports every 20 seconds. They exit when
all 786 are imported. Previous completed evidence remains visible while each
replacement scan is queued; operator decisions/history are preserved. This is an
explicit new pass, so the Day OCR counter running again is expected. Resuming the
same frozen batch command/output directory skips completed reports. Do not reuse
the original v1 output directory for this different number policy.

## Planned: use previous sightings as supporting context

The operator supplied these short bibs as a November 8 reference list:
**1, 4, 5, 14, 16, 19, 20, 22, 23, 24, 25, 26, 27**.
They are review/evaluation hints, not per-capture confirmations or a hard filter.
Event assignment and completeness have not been established. The machine-readable
list is `data/field-tests/2026-11-08/reference-short-bibs.json` on whiskey and
`data/analysis-20261109/reference-short-bibs.json` on zbook9. The active frozen
rescan is unchanged; its raw readings remain independent of this reference list.

Previous sightings can help rank a current image's plausible readings. They are
not currently inputs to the recognizer or an implemented lap-aware ranking layer.
This should be a separate, auditable stage rather than silently rewriting raw OCR.

For example, a clear earlier **24**, several independent appearances roughly
eight minutes apart, and a new ambiguous **24/74** near the next expected lap can
support ranking 24 first. If the image provides no usable number evidence, a
schedule alone does not become a visual read. Retain the raw candidates and crop.

The useful evidence includes:

- All distinct-frame OCR hypotheses and source crops within the current encounter.
- Earlier independent encounters, with operator confirmations weighted more strongly
  than machine-only guesses. Thirty frames of one passing are one encounter, not
  thirty independent confirmations. A returning rider is a new encounter.
- Robust recent lap intervals and their variability; rider groups, lapping,
  stopping and missing observations require broad timing windows.
- Event-scoped start lists, category/wave and expected crossings from CrossMgr.
- Independently received RFID/EPC reads and their clock-alignment uncertainty.

Use an explicit event or operator-selected time window before accumulating a
roster. A whole day's seen-number list can mix races and people: the same rider
can change bibs and a bib can be reused. A rolling recent window can supply weak,
expiring hints when no event source is connected, but cannot establish identity.

One early wrong read must not repeatedly reinforce itself. Cap machine-only
history influence, preserve competing hypotheses, permit first-time/new numbers,
and treat operator rejections/corrections as separate reviewed evidence. A valid
start-list number is not proof that the printed pixels show that number.

The current Paddle API returns its chosen text and score. We can rank hypotheses
already observed across frames/orientations downstream. Making a known-number
dictionary influence the underlying character decoder would require a suitable
decoder interface and validation, not simply passing a list to `predict()`.

Store any future contextual ranking separately from raw OCR scores, with event
scope, supporting encounter/read IDs, source revisions and ranking version. The
Saved CrossMgr CMN/MCP caching and the passings review chart are now implemented;
see `PASSINGS_REVIEW.md`. Feeding that event context into OCR ranking remains a
separate next step; see `INTEGRATION.md`.

Geometry can merge adjacent riders. A ranking must permit multiple real bibs in
one capture or unresolved geometry group, rather than impose one winner per video.

## Validation

89 local and 75 laptop unit tests pass, including v10-to-v11 migration with
existing corrections/history, one-/two-digit manual entries and queries, short
read imports, and repeated short numbers forming separate encounters. Real
Tk/Xvfb review tests include correction to 24 and manual additions of 24 and 7;
HTTP MCP/reverse-GUI integration also passes. The local and laptop review windows
were reloaded with their current clip/frame retained. The full new batch is still
running; its completion must be read from the importer progress files.

## Time interpretation

The operator describes the new local zone as PCT/PDT8. Analysis retains the actual
capture-date offset from the laptop timezone data (UTC−7 for these November 8
timestamps), not an inferred offset from a short label. Stored UTC timestamps
are unchanged. The copied laptop TZif remains the basis for whiskey's review
launcher and the hourly report, avoiding its older timezone database's offset.
