# Sunday field trial — November 8, 2026

Purpose: determine whether race-video evidence and OCR are useful in an actual
cyclocross setting. It will not supply race scoring or provisional CrossMgr reads.
A Codex session running locally on zbook9, using LTE for agent connectivity,
can run diagnostics and inspect selected frames;
recording must continue locally if that connection drops. There is no scheduled
or unattended remote session configured by this document.

## Conditions and placement

- Cyclocross: generally slower riders, but fall light may be weak. Measure actual
  outdoor exposure and moving-plate quality rather than reusing workshop tuning.
- Reader/antenna cases offer physical protection. Table placement is also possible:
  nearest frameplate approximately 1.2 m from the camera, with 3–4 m of road to cover.
  Compare the available placements before racing; check near and far plates.
- Lens focus, zoom and iris are manual. A person at the site makes those changes;
  the remote session can inspect results and change supported electronic controls.
- Future March–June road events will have different light and much faster finishes.
  A successful cyclocross test does not establish road-finish performance.

## Initial setup before riders arrive

1. Confirm camera identity, negotiated mode, recording, timestamps and free space.
   Prefer the physically verified 4K/30 baseline initially. Confirm local recordings
   continue while the GUI reviews an older segment.
2. Replace the workshop top-wheel OCR area and motion rectangle with race-specific
   regions covering the expected plate paths, including both sides of the road.
   Confirm motion detection actually catches a passing rider/plate; in a dim scene,
   a recording ending quiet does not prove that all useful motion was captured.
3. Put a real plate at near, middle and far positions. Adjust zoom/focus/iris and
   inspect original-resolution crops, not just a small preview. Keep settings and
   crops from each attempted configuration for later comparison.
4. Establish the short-exposure baseline using a moving plate/rider. Try nominal
   1/1000 s; if too dark, compare 1/500 s and choose from actual blur/recognition results.
   Adjust iris/gain with readback where applicable. Do not let auto exposure silently
   substitute a longer shutter. An operator-display brightness adjustment, if added,
   must not be confused with exposure or written into the original recordings.
5. The saved upright-only wheel setting is not a race-wide assumption. Existing
   Tesseract can try 0/180; the experimental Paddle best-view tool currently only
   tests upright crops. Vertical/upside-down coverage is not yet implemented in
   that tool. Record these label orientations when reviewing misses.

## During the trial

Keep original JPEG frames, source timestamps and segment metadata on zbook9.
Use LTE for commands, status, small crops/contact sheets and selected exports;
continuous 4K video transfer is unnecessary. Use the existing authenticated service
through the established access path; no public MCP listener is needed.

Run one isolated GPU analysis job at a time. The current best-view prototype is
invoked from the checkout, for explicitly chosen clip IDs:

```sh
.venv-ocr-paddle/bin/python -m tools.best_frame_ocr \
  /home/sl/.local/share/racevideo/racevideo.sqlite3 \
  --clips CLIP_ID --roi 0 0 1 1 --output data/sunday-trial/RUN_NAME --cpu-cores 2
```

**Pass the actual field ROI explicitly.** The full-frame coordinates above are
only a diagnostic example: the tool otherwise defaults to the old top-wheel ROI,
and does not read changes to the GUI area automatically. See CODEX_HANDOFF.md
for the current state, NVIDIA monitoring issue and prototype limitations.

Use a new output directory for each settings comparison. The tool reads SQLite
in read-only mode and produces candidate encounters and source crops; GUI Read
plates still uses the existing Tesseract path. GPU models are already cached on
the tested laptop; confirm their availability before going to the venue.

Inspect every identified plate through its visible traversal, selecting several
clearer images. If that plate leaves and returns, create a separate encounter
with independent evidence, even if its bib is unchanged. Preserve adjacent
recording-chunk links; a storage split alone is not another rider passing.

Watch recorder continuity, live-display responsiveness, bad packets, dropped
clips, analysis latency and CPU/GPU use. If analysis becomes intrusive, stop that
analysis job and retain the recordings for later processing. Do not restart the
recorder just to update OCR experiments or review crops.

## What to learn

Review a small, manually labelled set spanning near/far riders, singles/groups,
slower/faster riders, different label angles and changing light. Preserve unreadable
and missed examples as well as successes. Count actual visible encounters first;
then distinguish missed capture, missed detection, poor selection and wrong OCR.

Measure correct, missed and wrong candidate encounters and end-to-end analysis
latency. Do not count successive frames, contrast variants or fragmentation as
additional rider passings. Keep ambiguous alternatives available for review.

An actionable outcome is a set of field recordings, settings, source crops and
measured limits that explains what to improve before the spring road series.
