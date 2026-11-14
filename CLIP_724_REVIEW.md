# Capture 724: grouped short bibs and a following partial passing

Operator reference: first rider **4**, second **1**, later rider **589** with a
vertical smudged plate. The latest retained OCR has 599, 665 and 539 alternatives
for the late track; the early two bikes have no retained observations.

The stored capture has 95 frames over 3.132 s. A contact sheet and source examples
are under `data/validation/clip724-contact.jpg`, `clip724-frame22.jpg` and
`clip724-frame95.jpg`. Frame 22 visibly shows the leading bike's 4 on the left
and the following bike's 1 on the right. They travel right to left. The late
589 identity is operator-supplied; this note does not establish a new OCR success.

The metadata shows a two-second post-roll. The first pair clear the image at
approximately 1.3 s; most of the remaining tail is empty until the next rider
begins entering near the capture's end. This is not a minutes-long stalled motion
event. It illustrates that a bike outside the central motion ROI can appear at a
tail boundary without renewing that event. Review neighboring footage when
evaluating a partial rider; capture chunks are not independent race passings.

## Implemented response

- Manual entries can now carry a normalized bike rectangle, exact source
  ordinal/time and operator-verified order within the capture. Multiple bikes in
  one frame remain separate entries, with source highlighting and audit history.
- A shorter quiet-close limit is available for future recorder starts, default
  1.0 s. `--quiet-close 0` or the Maintenance setting restores full post-roll.
  Existing capture 724 is not split or rewritten. Smaller quiet tails reduce
  this kind of partial following-rider inclusion but do not prove the full scene
  is bike-free; the detector still monitors its configured ROI.
- No original frames or raw OCR were removed. The supplied reference labels are
  documentation; no automatic race-result writes or app confirmations were made.

Next OCR evaluation: short labels 4/1, overlapping rider geometry, rotated/smudged
589 and cross-capture association of a partial return. Keep raw alternatives and
do not inflate one physical passing into several riders or laps.
