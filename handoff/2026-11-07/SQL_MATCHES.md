# Bib-to-video matches

Schema v8 adds **`video_tag_matches`**, a persistent many-to-many lookup:

| Column | Meaning |
|---|---|
| `tag_id` | OCR bib/plate string, retaining leading zeroes such as `042` |
| `video_set_id` | Saved segment ID, referencing `clips.id` |
| `ocr_run_id` | Completed OCR run supplying the candidate evidence |
| `first_seen_ns`, `last_seen_ns` | Earliest/latest encounter receipt timestamps, Unix UTC nanoseconds |
| `encounter_count` | Number of OCR observation tracks for this bib in this segment |
| `max_confidence` | Highest underlying OCR score; not a probability |

The primary key is `(tag_id, video_set_id)`. One group segment can therefore have
rows for `123`, `456`, and `789`. Each number can also point to any number of other
segments. A second index supports listing all numbers for a video.

This table summarizes candidates from the **latest completed OCR run per clip**.
A queued, running or failed rerun leaves the previous completed matches available.
A newly completed rerun atomically replaces that clip's match set, including an
empty set if nothing was found. SQLite triggers maintain the table when OCR runs
or observations are inserted, edited or deleted, including through SQL imports.
Migration backfills existing completed runs without rescanning or changing video.
Clip cleanup removes dependent matches. Original observations and raw reads remain
the detailed evidence/history; this table does not replace them.

`video_set_id` currently means one saved clip/segment, not a rider-specific crop
or a collection of laps. Motion events split into chunks can have multiple clip
IDs linked by their existing event metadata. `tag_id` here is an OCR plate/bib,
not an RFID EPC. An association is candidate evidence, not a confirmed passing.
Multiple observation tracks inside a segment are not necessarily distinct laps.

## Today's videos for one bib

`today_video_tag_matches` is a convenience SQL view using the host's local day
and the segment's start timestamp, consistent with the date browser.

```sql
SELECT video_set_id
FROM today_video_tag_matches
WHERE tag_id = '123'
ORDER BY video_set_id;
```

## Today's videos for any of several bibs

Return each video once, even when it contains both requested riders:

```sql
SELECT DISTINCT video_set_id
FROM today_video_tag_matches
WHERE tag_id IN ('123', '456')
ORDER BY video_set_id;
```

To return clip metadata in time order without duplicate rows:

```sql
SELECT c.id AS video_set_id, c.started_ns, c.ended_ns, c.frame_count
FROM clips AS c
WHERE EXISTS (
    SELECT 1 FROM today_video_tag_matches AS m
    WHERE m.video_set_id = c.id
      AND m.tag_id IN ('123', '456')
)
ORDER BY c.started_ns, c.id;
```

## An explicit event date

For indexed date ranges, calculate local-midnight boundaries with
`racevideo.storage.local_day_bounds('2026-11-03')` and bind those nanoseconds:

```sql
SELECT c.id AS video_set_id, c.started_ns, c.ended_ns
FROM clips AS c
WHERE c.started_ns >= :start_ns AND c.started_ns < :end_ns
  AND EXISTS (
      SELECT 1 FROM video_tag_matches AS m
      WHERE m.video_set_id = c.id AND m.tag_id IN (:tag1, :tag2)
  )
ORDER BY c.started_ns, c.id;
```

## All riders in one segment

```sql
SELECT tag_id, encounter_count, first_seen_ns, last_seen_ns, ocr_run_id
FROM video_tag_matches
WHERE video_set_id = :video_set_id
ORDER BY first_seen_ns, tag_id;
```

GUI bib filters and MCP `clips.list` now use this table. Existing API requests
such as `{"day":"2026-11-03","bibs":["123","456"]}` match any supplied bib
and return each clip once. MCP `clips.info` includes `tag_matches`; `bibs.sightings`
still returns the individual timestamped observations/source frames.

## Future event identity

Day/bib queries retrieve raw evidence and must not be treated as person identity:
the same date can contain multiple events and a person can have a different bib
for each. Current `tag_id` is an OCR bib token, not an RFID EPC. Future event-entry
resolution and OCR/RFID corroboration are described in
[INTEGRATION.md](INTEGRATION.md); they will be added alongside these raw matches.
