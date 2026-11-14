# Experimental DIN-label recognizer fine-tuning

First experiment started November 5, 2026 on zbook9. The production recorder,
GUI and Tesseract worker are unchanged. Baseline Paddle inference remains cached
and unchanged; all training assets/checkpoints are in `data/training/`.

## Data and leakage boundaries

`tools/make_training_corpus.py` calls the actual qllabels bib renderer with its
preferred TGL 0-1451 Engschrift font. It obtains the digit-area dimensions from
the Frame and Body renderer functions, preserving their different stretching
proportions. Source and font SHA-256 values are recorded in the corpus manifest.
See LABEL_RENDERING.md for the checkout/deployment provenance distinction.

The fixed string split contains 808 training numbers and 192 validation numbers.
Four deterministic augmented images per training number yield 3,232 images;
two per validation number yield 384. All values retain three characters, including
leading zeroes. A hash-based split keeps entire numeric strings disjoint. 235 and 469
are explicitly assigned to validation and are absent from training. Real-video
images, labels and OCR outputs are not used in training.

Augmentation includes both printed digit-area aspect ratios, apparent camera size,
padding, mild perspective and rotation, moderate horizontal/vertical blur,
defocus, darker illumination, shading, noise and JPEG compression. It does not
rotate labels 180 degrees and force a unique number through an inherently ambiguous
609/906 presentation. Arbitrary orientation remains a pipeline requirement.

Validation uses independent numeric strings and augmentation seeds, but shares
the same synthetic generator. Its accuracy alone is not field accuracy. Existing
real crop, background and sequence diagnostics remain separate checks. Those real
examples have already been used during pipeline development, so they are a
held-out training check, not a pristine final race test set. Sunday field footage
will provide a more independent evaluation.

## Training configuration

- Official PaddleOCR source tag v3.3.2 and matching PP-OCRv5 mobile recognition
  pretrained training checkpoint; source checkout lives under data/training.
- Separate Python 3.12 environment `.venv-ocr-train`, PaddlePaddle GPU 3.2.2/CUDA 12.6.
- Original character dictionary and both CTC/NRTR heads retained. No new
  three-digit classification head and no restriction to known race numbers.
- All model layers fine-tuned with Adam, low initial learning rate 1e-5 and a
  cosine schedule; two epochs, batch 4, AMP O1.
- Two logical CPU affinity slots, zero data-loader child processes. Training
  uses the GPU independently of capture and GUI processes.
- Checkpoint selection by synthetic validation, not by real-video test outcomes.
  Original checkpoint/baseline are retained for comparison and rollback.

The generated YAML, data manifest, source revision, logs and evaluation reports
are the authoritative run records. The generator is seeded; this does not claim
bit-identical GPU training across hardware/runtime versions.

## Reproduce the data and configuration

From the whiskey checkout, which can import qllabels and its rendering dependencies:

```sh
.venv/bin/python tools/make_training_corpus.py \
  --qllabels-root /home/sl/work25/qlmux/qllabels \
  --output data/training/din-v1 --variants 4
```

Use a fresh output directory; the generator refuses to overwrite an old corpus.
Copy that directory to zbook9, then use `tools/configure_din_training.py` with
explicit upstream, data, checkpoint and output paths. The first job runs as the
transient user unit `racevideo-din-training-v1.service`; its output log is
`/home/sl/racevideo/data/training/din-v1-train.log`. This unit is independent of
`racevideo-mcp.service` and the recorder unit.

After training, export the selected checkpoint through upstream tools/export_model.py.
The benchmark and best-view tools accept `--recognizer-model-dir` to compare an
exported copy while retaining their default upstream recognizer. No production
engine switch occurs merely because training or export succeeds.

## First-run outcome

Two epochs completed in about 4.6 minutes, 1,616 optimization steps, on the RTX A1000.
The log reports approximately 1,277 MiB maximum allocated training tensors and
1,366 MiB reserved; driver/display/context memory is additional. The recorder
remained recording with no reported dropped clips or errors at the checks made.
This is a training-feasibility result, not sustained race-load validation.

| Recognition-only held-out synthetic evaluation | Exact numbers |
|---|---|
| Existing cached Paddle baseline |383/384 (99.74%)|
| Export of unmodified training checkpoint |383/384 (99.74%)|
| Best ordinary fine-tuned checkpoint |361/384 (94.01%)|
| Fine-tuned weights with original BatchNorm running statistics restored |383/384 (99.74%)|

The first training/export validation is around 93.49% versus 94.01% through the
PaddleX inference API; preprocessing/inference paths differ, so the direct
baseline/exported comparisons above use the same evaluator for all models.
The unmodified checkpoint export was checked to rule out a starting-model/export
mismatch. The synthetic regression is largely attributable to shifted BatchNorm
running statistics from small-batch training. A separate diagnostic copy restores
302 mean/variance tensors from the original checkpoint while retaining other
fine-tuned weights. It does not overwrite either checkpoint or the baseline.

Neither trained variant demonstrated a field-recognition improvement on the
existing diagnostic recordings. In raw sampled search regions of clip 71, the
baseline produced469 in 5 frames and 235 in 6; ordinary tuning produced469 in 1 and 235 in 3;
restored-statistics tuning produced469 in 2 and 235 in 5. Wrong three-digit alternatives
remain. These are frame-level candidates, not encounter accuracy or passing counts.
The dimmer/slower clip 81 retained the same four repeated-candidate encounters in
both trained variants. Some individual crop readings regressed, including the
operator-selected 235 crop for ordinary tuning.

**Decision: retain the original Paddle baseline.** The trained copies are available
only through explicit model-directory arguments; production OCR is unchanged.
No successful training run is treated as grounds to deploy a worse recognizer.

## Retained artifacts

On zbook9, under `/home/sl/racevideo/data/training/`:

- `din-v1/`: generated data, fixed train/validation lists, manifest and samples.
- `PaddleOCR/`: pinned upstream source (commit recorded in model-hashes.json).
- `PP-OCRv5_mobile_rec_pretrained.pdparams`: unchanged initial training weights.
- `din-v1-model.yml`, `din-v1-train.log`, `din-v1-model/`: configuration, log,
  selected checkpoint, latest checkpoint and optimizer/state artifacts.
- `din-v1-export/`: ordinary tuned inference model.
- `din-v1-initial-export/`: unmodified checkpoint export for comparison.
- `din-v1-bn-reset.pdparams`, matching JSON and `din-v1-bn-reset-export/`:
  the diagnostic normalization-statistics copy and its provenance.
- `*-synthetic-val.json`, `*-real-fixture.json`, `*-real-sequence.json`,
  `tuned-encounters/`, `bn-reset-encounters/`, `baseline-encounters/`:
  evaluation outputs with text, scores and source evidence.

The normalization-restored inference model was also copied to this checkout's
`data/training/din-v1-bn-reset-export/`. Dataset audits, model hashes, configuration,
training log and evaluation JSONs are retained under
`docs/evidence/zbook9/elp/training/`; large checkpoints and generated corpus images
remain outside source control. 56 unit tests passed, including seeded augmentation,
leading-zero preservation and explicit train/validation string separation.

## Next useful experiment

Collect manually labelled outdoor crop/encounter examples with unreadable and
background controls, keeping complete recordings/events separate across training
and evaluation. Start with the original checkpoint, freeze normalization running
statistics during small-batch training, and mix realistic synthetic and real
examples. Include labelled side text, partial labels and other negative cases
rather than rewarding a three-digit answer on every input. Maintain the full
vocabulary initially; do not mistake rising confidence for improved correctness.
Re-evaluate both recognition and per-encounter evidence before promotion.
