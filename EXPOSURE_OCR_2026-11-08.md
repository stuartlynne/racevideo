# November 8: OCR candidates versus exposure

**Later correction:** this completed batch retained only three-digit strings.
The operator subsequently identified valid one- and two-digit bibs (24 in capture
877). Those were excluded by the original filter, adding a race-group/bib-length
confound to the exposure comparison. The correct examples at setting 4 remain
valid, but the yields below are not all-bib performance. A new 1–3 digit pass is
running; see [CONTEXTUAL_OCR.md](CONTEXTUAL_OCR.md).

Analyzed all 786 race-day captures / 90,679 frames using the completed all-frame neural batch. The database was opened read-only; no OCR rerun, camera change or review decision was performed.

**Candidate yield is not recognition accuracy.** A positive capture has at least one qualified OCR observation, including wrong or ambiguous alternatives. Some captures may contain no visible readable plate. There are no saved operator reviews in this copy, so rider-level recall and correctness cannot be calculated.

Exposure is the driver value saved at the motion trigger, in 0.1 ms units. All 786 report manual mode (1) and gain 190. A setting of 4 is 0.4 ms, nominally 1/2500 second. Manual focus/iris and any mid-clip setting changes are not recoverable from this snapshot.

| Setting | Duration (ms) | Approximate speed | Captures | With candidates | Yield | With a repeated candidate* |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.1 | 1/10000 s | 2 | 0 | 0.0% | 0 |
| 4 | 0.4 | 1/2500 s | 503 | 273 | 54.3% | 191 |
| 6 | 0.6 | 1/1667 s | 5 | 0 | 0.0% | 0 |
| 7 | 0.7 | 1/1429 s | 1 | 0 | 0.0% | 0 |
| 8 | 0.8 | 1/1250 s | 32 | 10 | 31.2% | 8 |
| 10 | 1 | 1/1000 s | 54 | 11 | 20.4% | 8 |
| 12 | 1.2 | 1/833 s | 6 | 0 | 0.0% | 0 |
| 20 | 2 | 1/500 s | 10 | 1 | 10.0% | 1 |
| 21 | 2.1 | 1/476 s | 25 | 0 | 0.0% | 0 |
| 22 | 2.2 | 1/455 s | 2 | 1 | 50.0% | 1 |
| 25 | 2.5 | 1/400 s | 19 | 2 | 10.5% | 1 |
| 30 | 3 | 1/333 s | 8 | 0 | 0.0% | 0 |
| 34 | 3.4 | 1/294 s | 11 | 0 | 0.0% | 0 |
| 40 | 4 | 1/250 s | 39 | 0 | 0.0% | 0 |
| 43 | 4.3 | 1/233 s | 69 | 0 | 0.0% | 0 |

*Repeated means at least one observation has the algorithm status `repeated`; it is not a human-confirmed passing. Ambiguous competing observations can still contain the correct number.

## Interpretation

- Setting **4 / 1/2500 s** was the most productive setting in this dataset: **273/503 captures (54.3%)**, accounting for 273 of the 298 candidate-bearing captures.
- Setting **8 / 1/1250 s** produced candidates in **10/32 (31.3%)**; setting **10 / 1/1000 s** in **11/54 (20.4%)**.
- Settings **40–43 / approximately 1/250–1/233 s** produced **0/108 qualified candidate captures**. Raw numeric reads existed in some, but none passed the encounter filter.
- There are **no setting-2 / 1/5000 s captures** in this race-day dataset. Setting 1 / 1/10000 s appears in only two captures, neither positive; that is too little evidence to judge it.
- Time of day, lighting, rider groups, occlusion, framing, focus/iris and brightness/contrast settings changed. Therefore these results do not isolate exposure as the cause of the improvement.

## Same exposure, different hours

At setting 4 throughout, yield still changed substantially. Hours below use the laptop timezone file (UTC−7), preserving the original timestamps.

| Hour | Captures at setting 4 | With candidates | Yield |
|---|---:|---:|---:|
| 11:00 | 1 | 0 | 0.0% |
| 12:00 | 152 | 51 | 33.6% |
| 13:00 | 125 | 96 | 76.8% |
| 14:00 | 151 | 95 | 62.9% |
| 15:00 | 74 | 31 | 41.9% |

This is observational evidence for keeping setting 4 as a practical baseline to compare under matched conditions, not proof that it is optimal. A same-scene comparison at 8, 4 and 2 would distinguish motion sharpness from insufficient light more directly.

## Previously visually checked correct examples

These selected examples were verified during the earlier field investigation, rather than counted as operator reviews. They are not a random accuracy sample. Each correct number is also present among the full-day batch hypotheses.

| Capture | Correct number | Exposure setting | Speed | Batch ambiguity |
|---:|---|---:|---|---|
| 212 | 155 | 8 | 1/1250 s | Also proposes 755 |
| 508 | 826 | 4 | 1/2500 s | Also proposes inverted 978 |
| 670 | 730 | 4 | 1/2500 s | Repeated 730 |
| 800 | 480 | 4 | 1/2500 s | Also proposes inverted 087 |

Example provenance and original frame hashes: `docs/evidence/field-2026-11-08/verified-examples.json`. Full per-exposure/per-clip data: `data/field-tests/2026-11-08/exposure-ocr.json`. Reproduce with `tools/exposure_ocr_report.py`, using batch `ea6f07339595e86b7f5aca4b` and the same Vancouver TZif for local-hour grouping.
