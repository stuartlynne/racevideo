# November 8 race footage: OCR and operator review

Updated November 9, 2026. Use NVIDIA on zbook9. AMD trials are suspended after
the operator reported Plasma6/X instability; no display-driver work is needed.

## Stores and evidence

- Protected original here: `data/imports/zbook9/2026-11-09/racevideo-20261109.sqlite3`,
  mode 0444, 175,081,676,800 bytes. SHA256:
  `46818cab16a6edeef2ced6d000bc9485a6dcd1eb9f315bf15fb729d85bf44140`.
- Writable test copy: `data/field-tests/2026-11-08/racevideo.sqlite3`.
- All 877 clips / 97,535 original frames were copied. The November 8 scan covers
  clips 92–877: **786 clips / 90,679 frames**. Earlier test clips are retained.
- GPU input: `/home/sl/racevideo/data/exports/2026-11-09/racevideo-20261109.sqlite3`
  on zbook9, opened read-only by the batch worker.
- Reports here: `data/field-tests/2026-11-08/full-day-results/`.
- Reports on zbook9: `/home/sl/racevideo/data/analysis-20261109/full-day/`.
- Supplemental CPU reports here: `data/field-tests/2026-11-08/cpu-supplement/`.
- Batch ID: `ea6f07339595e86b7f5aca4b`.

The full-day process writes neither original video store. Imports only update
the writable local test copy. Each clip report includes all source-frame
identities/timestamps and is verified before one atomic import transaction.
Completed imports are idempotent. Operator reviews are separate and survive
reruns. No human confirmations were manufactured in the actual field-test store.

## Pipeline and interpretation

All original JPEGs are decoded; this run does not skip frames. Generic small
person/bicycle proposals feed text detection and the original Paddle mobile
recognizer. Detection tries two orientations, recognition four. The search region
is normalized `[0.05, 0.40, 0.98, 0.90]`. Geometry links views into encounters;
at least three qualifying frames and movement are required for an encounter.
Original three-digit reads and alternative hypotheses are retained.

This is a review aid, not automatic race scoring. Upside-down pairs such as
826/978 can both survive. Close riders can be merged into one geometry track;
the review UI allows confirming both. Blur/focus/occlusion and weak proposals
can produce no candidates even where a human sees a plate. CrossMgr start lists
and RFID context have not yet been fetched. Source receipt times require clock
alignment before any precise RFID/crossing comparison.

## Review

This all-frame sweep is an offline recognition-quality experiment. One 90-frame
app validation met the proposed 10–30 second latency, but that does not establish
sustained throughput for dense continuous race footage within two CPU cores.
Selective best-view recognition, model residency and explicit bounded backlog
handling still need workload validation before enabling automatic continuous OCR.
The normal app worker enforces its two-physical-core limit; the bulk analysis
uses more cores separately to reduce elapsed time.

Operator-confirmed source frames/crops can support a later training dataset.
Bib-presence confirmation alone is not a complete detector-box annotation or a
timing/identity ground truth, especially for manually added partially obscured bibs.

Run `racevideo-field-review` here, or select **RaceVideo — 2026-11-08 review**
in the application menu. This opens the writable test store, selects a November 8
clip and leaves capture stopped. Use **Review bibs…** to confirm/reject/correct
individual observations or add a missed bib at the displayed original frame.
The thumbnail filter uses effective reviewed evidence. See [REVIEW.md](REVIEW.md).

The launcher sets a per-process Vancouver timezone file copied from zbook9,
because the two hosts had different tzdata revisions for BC's 2026 offset.
Stored UTC nanoseconds and system timezone configuration are unchanged.

Local MCP store `field-review` points to this test copy; the original default
store remains available. `clips.info` exposes effective matches, machine matches
and current review rows. No CrossMgr/RaceDB/Impinj service has been changed.

## Progress and recovery

The local transient user unit `racevideo-field-sync-20261108.service` pulls small
atomic JSON reports every 20 seconds, then imports completed clips. It inherits
the active SSH agent socket and exits successfully after all 786 are imported.
Progress is `full-day-results/import-progress.json`; diagnostics are `import.log`.
The UI shows **Day scan N/786**. Completed clips can be reviewed during the sweep.
All clips in an active batch are protected from date cleanup until it completes.

The remote batch initially ran two workers, then was safely resumed with three
workers, each pinned to a distinct physical CPU core (0, 2, 4). Completed reports
were reused. This offline configuration is separate from the normal app worker,
which caps itself at two physical CPU cores. App production-path validation on
zbook9 processed real clip 508 (90 frames) in 15.1 seconds wall time while the
background batch was running, producing 826 and 978 as alternatives.

If interrupted, resume the frozen batch staging code on zbook9, not a newly
edited copy of the master repository:

```sh
cd /home/sl/racevideo/data/analysis-20261109/code
nohup /home/sl/racevideo/.venv-ocr-paddle/bin/python -m tools.field_ocr_batch \
  /home/sl/racevideo/data/exports/2026-11-09/racevideo-20261109.sqlite3 \
  --models /home/sl/.paddlex/official_models \
  --output /home/sl/racevideo/data/analysis-20261109/full-day \
  --cpu-sets 0 2 4 \
  >> /home/sl/racevideo/data/analysis-20261109/full-day.log 2>&1 < /dev/null &
```

A lock prevents duplicate controllers. Workers skip matching completed reports
and retry unfinished clips. A remote `complete.json` plus 786 imported clips
establishes completion; an active process alone does not. Local sync can be
restarted with `systemctl --user restart racevideo-field-sync-20261108` while its
transient definition exists. After reboot recreate it with the same Python module,
database/report paths and SSH_AUTH_SOCK environment; see `tools/sync_field_ocr.py`.

### CPU assistance for this offline sweep

To reduce elapsed time, a separate CPU-only pass on whiskey processes the same
manifest newest-first with 16 low-priority workers, each pinned to a distinct physical core
(4, 6, 8, 10, 12, 14, 16–25), leaving two P-cores and additional E-cores free. It uses the already validated `.venv-ocr-cpu`, the protected source
in read-only mode and the same model weights/parameters. SHA256 hashes of all three model weight
files match across hosts (`model-provenance.json`). Reports record device
`cpu`; there is no AMD/Vulkan use. This is offline throughput work, not the normal
two-core app budget.

Unit `racevideo-field-cpu-20261108.service` runs the master batch tool with
`--device cpu --reverse --completed-directory` pointing to the published reports.
It skips reports already supplied by zbook9. The sync unit's `--supplement` points
to `cpu-supplement`; it links only complete atomic reports that have not already
been published. rsync does not overwrite a published clip report, but continues
refreshing worker progress. The importer validates the source identity exactly
and records the original device, so CPU/GPU provenance remains distinguishable.

For this combined sweep, completion is **786 verified imports**, even if neither
individual host processed every clip itself. Stop any remaining redundant
workers after all reports have been imported; retain both original report
directories and the final combined import summary for provenance.

Completed CPU reports were also copied back to zbook9's analysis output using
`rsync --ignore-existing`, allowing its remaining workers to reuse them. Existing
reports were never replaced. That output directory therefore contains reports
from both devices, rather than exclusively CUDA reports.

## Validation boundary

78 unit tests pass locally; the deployed laptop test set passes 57 tests,
including the new review/import tests. Real Tk/Xvfb tests exercised source selection, correction,
rejection, manual additions, resets and no Tk callback exceptions. Real-video
CPU and NVIDIA runs exercised the new app worker/import path. HTTP MCP and
reverse GUI integration passed. These checks used disposable validation stores;
they do not establish recognition accuracy for the full event or physical-camera
performance under race conditions. The final full-day counts are recorded below
once the sweep completes.

A further 12-second Tk/Xvfb check opened the actual 175 GB writable test copy
during concurrent import/analysis, selected capture 412 and displayed 22 review
rows without making operator decisions. Callback-work p95 was 14.1 ms (maximum
22.9 ms); the bib-table update was 0.34 ms. No Tk callback exceptions occurred.
This checks short-run saved-video review responsiveness, not sustained live
camera latency. Artifacts: `data/validation/field-review/gui-check.json` and
`capture412.png`. Polling updates existing table rows incrementally so it does
not reset selection, scrolling or a correction being typed.

`tools/field_ocr_summary.py` reads the imported batch without writing the database
and produces `coverage.json`, including completed source frames, candidate counts,
device provenance and hourly coverage. These are coverage/candidate statistics,
not measured recognition accuracy; no ground-truth labels have been supplied.

## Completed sweep — November 9, 20:13 UTC

- **786/786 clips, 90,679/90,679 original frames** processed and imported.
- 15,084 raw numeric readings; 733 observation alternatives across 450 qualified
  geometry encounters. These are not unique riders or verified passings.
- **298 clips have candidates**. The other 488 have no qualified candidates;
  this does not mean no visible riders/plates were present.
- Published reports came from CUDA for 617 clips and CPU for 169 clips. All three
  model weight hashes match across hosts. No AMD inference was run.
- All three remote workers completed without errors and wrote `complete.json`.
  The local importer exited successfully; redundant local CPU work was stopped.
- The complete store still has 877 clips and 97,535 original frames. SQLite
  foreign-key checks passed. Fifteen sampled source JPEGs (first/middle/last
  frames in five clips) are byte-identical to the protected original.
- The original snapshot remains 175,081,676,800 bytes and mode 0444. It was not
  rewritten. There are zero fabricated operator decisions in the field store.

Artifacts: `data/field-tests/2026-11-08/coverage.json`, `final-validation.json`,
`model-provenance.json`, and the per-clip JSON reports. The writable database is
ready for review through `racevideo-field-review`.

Candidate yield changed markedly over the day, consistent with the operator's
report that setup and lighting improved. These counts do not isolate the effects
of lighting, focus, settings, field of view or the different race groups:

| Local hour (UTC−7) | Captures scanned | Captures with candidates |
|---|---:|---:|
| 10:00 | 106 | 0 |
| 11:00 | 111 | 13 |
| 12:00 | 219 | 63 |
| 13:00 | 125 | 96 |
| 14:00 | 151 | 95 |
| 15:00 | 74 | 31 |

No accuracy percentage can be claimed from these counts without operator labels.

## Post-launch thumbnail refresh fix

The operator noticed the app appeared to be scanning the day again. All 830 OCR
runs in the copy (786 field runs plus 44 earlier runs) were complete, and no OCR
workers were active. The GUI reader accidentally reused its thumbnail-browser
signature variable when polling selected-clip bib rows. That caused repeated
thumbnail loads during ordinary review. The short original UI measurement did
not catch this longer-running refresh error.

Bib polling now uses its own signature. A regression test first reproduced the
duplicate thumbnail emissions, then passed with the fix: unchanged clips are
loaded once while bib/status polling continues. The complete local suite passes
79 tests, the reader regression passes on zbook9, and the real Tk review workflow
still passes. The local window was restarted with the fix, and the change was
deployed to zbook9. The completed batch label now explicitly says **Day OCR
complete · 786 clips**. No OCR evidence or operator reviews were changed.

## Results published into the normal zbook9 database

At the operator's later request, the exact whiskey-published report set was copied
to zbook9's `data/analysis-20261109/review-published/` and imported into
`~/.local/share/racevideo/racevideo.sqlite3`. Existing GPU/CPU analysis reports
were retained separately; no inference rerun was necessary.

All 786 clips / 90,679 frames passed importer source-identity checks. Results
match whiskey: 15,084 raw numeric reads, 733 observations and 298 clips with
candidates. Original video totals remain 877 clips / 97,535 frames; the 91 older
setup/test clips were retained. The laptop's 46 prior OCR runs were retained,
and 786 new batch runs were appended. There were no operator reviews to replace.
The final foreign-key check passed. Choose **2026-11-08** in the normal laptop
app's Date selector to review the imported results.

The full original video snapshot remains at
`data/exports/2026-11-09/racevideo-20261109.sqlite3` on zbook9, alongside the
protected whiskey copy. Before publication, current non-frame metadata was backed
up under `data/analysis-20261109/pre-import-20261109-170201/`; its manifest records
the full video snapshot required alongside that metadata-only backup. Import
validation is `review-published/laptop-import-validation.json`.
