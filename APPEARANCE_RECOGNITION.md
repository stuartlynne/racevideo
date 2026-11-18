# First rider appearance experiment: Sunday Elite

Implemented November 18, 2026. CPU-only, event-scoped suggestions. No model
training or automatic identity/timing writes. The video/OCR database is opened
read-only; descriptors, images and suggestions are separate local files.

## Implementation

- OpenVINO `person-reidentification-retail-0288`, an OSNet-based 256-value image
  embedding, a regional HSV colour baseline, and a fixed 70/30 combination.
- Up to three consistent person views per passage. The centre-frame view anchors
  the descriptor; poor appearance agreement excludes neighbouring-rider views.
  Recognized numeric text patches are masked. This does not prove that every
  visible numeral was masked. Colour region descriptions are approximate geometric
  helmet/torso/shorts regions, not semantic segmentation.
- Galleries use existing manual confirmations or unambiguous repeated OCR matching
  a CM passing. Predictions never become gallery labels. Whole query captures are
  excluded from references. Conflicting label evidence is flagged for review.
- The sidebar shows advisory top-three bibs. Its Appearance button opens an image
  report at the selected track, with source capture/frame, ranking and alternatives.
  No table order, bib, matching state, confirmation or race time is changed.

**Evaluation always uses earlier reference captures**, taking the earliest reliable
sighting per bib. Post-race review can use earlier or later references, excluding
the query capture. The completed Elite race is published with this second policy,
so late confirmation of 6 can help identify an earlier unknown. No appearance-based
merging of tracks or participants is performed in this pass.

## Measured local results

Elite event 11, November 15. 170 candidate stops plus two standalone manual
reference frames were considered. Suitable crops were extracted for 162 tracked
passages and the two references; eight candidates had no suitable person crop.
309 views contributed. Analysis took about 83 seconds on two physical CPU cores;
neither AMD nor NVIDIA GPU runtimes were used.

| Method | Manual-only gallery: manual repeat top 1 | Supported gallery: OCR proxy top 1 | OCR proxy top 3 |
| --- | --- | --- | --- |
| Regional colour | 5/5 | 13/23 | 17/23 |
| Learned embedding | 5/5 | 22/23 | 22/23 |
| Fixed 70/30 combination | 5/5 | 22/23 | 23/23 |

Five manual repeats are the independent checks against saved human labels. Five
is much too few for general accuracy claims; colour alone also passed those five.
OCR-labelled checks are proxy consistency checks, not verified accuracy. With
the supported gallery, six manual repeats were eligible and all six ranked
correctly using embedding/combination. Queries with no earlier reference for
their recorded bib are counted separately, not included in these fractions.
High-similarity wrong and unseen-identity suggestions are audited at an explicit
experimental threshold (score >=0.9, margin >=0.05). Similarities are not calibrated
probabilities; the app never automatically accepts a suggestion.

Chronological retrieval ranks Lap 2's unread fourth rider as 1. Post-race retrieval
ranks clip 1872's five primary stops as 5, 6, 2, 1, 60; the 6/300 comparison is
close and needs review. The final-lap captures 1968/1969/1970 rank 6/5/2 first.
This is not a road-pack or multi-camera validation.

**Reference conflict:** clip 1861 is saved as manually confirmed 301, while the
visible plate and 22-frame OCR consensus indicate 300. That sighting is excluded
from reference seeding/evaluation and flagged in the report. The review remains
unchanged. A later supported 301 sighting can still serve as a reference.
Human review/history hashes match the pre-experiment baseline. No video, OCR or
CrossMgr records were changed.

## Files, setup and operation

Local output: `/raid4tb/sl/racevideo/tests/2026-11-15/appearance-elite-v1/`.
`report.html` contains image comparisons; `results.json` records sources, rankings
and metrics; `descriptors.npz` stores vectors; `images/` holds original review
crops. Browser brightness is cosmetic. `verification.json` records digest checks.

App sidecar: `racevideo.sqlite3.appearance-11.json`, beside the local test DB.
Review/source fingerprints invalidate suggestions after label changes; rerun to
refresh them. The old image report remains available. This is an offline CLI
experiment, not an automatic live ReID worker. OpenVINO stays outside Tk/capture;
optional sidecar loading runs on the background passings worker. Base installations
do not need inference dependencies.

Setup from the repository root, using a separate Python 3.12 worker:

```sh
python3.12 -m venv .venv-reid
.venv-reid/bin/python -m pip install -r tools/requirements-appearance.txt
.venv-reid/bin/python -m tools.fetch_appearance_model
```

Run only the local Elite experiment:

```sh
.venv-reid/bin/python -m tools.rider_appearance \
  --db /raid4tb/sl/racevideo/tests/2026-11-15/racevideo.sqlite3 \
  --event 11 \
  --results /raid4tb/sl/racevideo/tests/2026-11-15/ocr-local-cpu \
  --model data/models/person-reidentification-retail-0288/person-reidentification-retail-0288.xml \
  --output /raid4tb/sl/racevideo/tests/2026-11-15/appearance-elite-v1 \
  --review-gallery all --publish
```

Omit `--publish` to leave app suggestions unchanged. `--review-gallery past` also
restricts displayed suggestions to earlier references. Evaluation is always
chronological regardless of this switch. Model/runtime/reports have not been
deployed to zbook9.

The downloader verifies official Open Model Zoo SHA384 checksums. Weights are not
committed to Git. Sources: [model documentation](https://github.com/openvinotoolkit/open_model_zoo/blob/master/models/intel/person-reidentification-retail-0288/README.md),
[manifest/checksums](https://github.com/openvinotoolkit/open_model_zoo/blob/master/models/intel/person-reidentification-retail-0288/model.yml),
[OpenVINO inference](https://docs.openvino.ai/2025/openvino-workflow/running-inference/inference-request.html).
The model documents upright-person coverage; cycling is an untrained domain shift.

Next: expand independently confirmed holdouts, inspect crop integrity and same-team
confusions, add uncertainty/unknown handling, then measure whether appearance
reduces operator work before allowing it to influence track association.
