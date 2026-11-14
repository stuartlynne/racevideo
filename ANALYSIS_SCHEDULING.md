# Analysis scheduling and operator review priorities

Operator policy, November 11, 2026. Shared ordering is implemented in
`racevideo/analysis_priority.py`; it is advisory analysis scheduling, never a
race read, finisher confirmation, DNF decision or modification of CrossMgr.

## Priority rules

1. An operator-selected review is foreground work. Wheel analysis follows the
   latest selection after the current bounded wheel job finishes; do not build
   an obsolete backlog of selections the operator has already left.
2. During racing, ordinary pending work goes newest first: latest identified
   rider/capture, then backwards through earlier sightings. The existing bike
   indexer works at clip granularity, so a group capture is one job.
3. When a category starts finishing, its final passages take priority over
   ordinary lap footage. Keep category/wave start offsets and lap targets
   separate. The overall race leader's last lap is not everybody's last lap.
4. Process leading finishers in category result order. The category whose leader
   finishes first gets the first turn. Give it the first five places, then give
   other finishing categories their leading five before returning to places
   6–10, then 11–15, etc. Five is the initial configurable policy quantum, not a
   requirement to wait for five arrivals. If only three have arrived, process
   those three and work on another available category; never idle for a rider.
5. Recompute choices between jobs from all current facts, including already
   processed leaders. A newly finishing category's leaders outrank another
   category's tail. Riders from several categories can arrive interleaved.
6. Deduplicate shared clips. One clip can contain several riders/categories;
   processing it benefits all of them. Retain separate per-bike timing targets.
7. After priority finishes, remaining earlier footage is processed newest first.
   Unknown riders and ambiguous finish candidates remain reviewable. Priority
   classification is not proof of identity or finish status.

## Facts and safeguards

The cached CrossMgr payload retains wave and component category memberships,
category lap counts, start offsets, observed passings, calculated-lap flags,
result positions and race state. Component categories use their wave's timing
and lap context; umbrella wave results are not duplicated as another category
when component results exist for the same rider.

For a running race, status `Finisher` alone is insufficient: CrossMgr can use it
before that rider has finished. A scheduled final observed lap or an observed
crossing after that wave's leader finish provides a *priority candidate*.
Projected laps do not trigger finish priority. In a finished event, the last
observed passage of a Finisher is a candidate, including lapped riders.

Use absolute cached passing times, corrected against camera time with the
configured offset. Do not add category start offsets a second time. The
comparison window defaults to three seconds, matching ordinary passing review;
a candidate capture is not a confirmed match. Among candidate clips for one
finisher, prefer the nearer interval. Retain all plausible footage for review.

The category leader's first observed target-lap crossing anchors its finish
priority; subsequent/cooldown reads must not move that anchor forward. Category
rank is used for the top-five turns, with observed crossing order as fallback.
An explicit selected clip can override the normal planner's order.

## Current integration and remaining boundaries

`Index event bikes` now queues clips in this order. Before each next queued clip,
the worker recomputes priority using the latest cached event source. Cancelled
and completed jobs stay out of the pending queue. The detector remains loaded
for the batch, and the GUI/capture processes do not do its analysis work.

The current batch is a finite set of queued clips. This change does not start a
batch automatically, add newly arriving captures to an active batch, or poll
CrossMgr MCP for live data. A later coordinator must enqueue new work and
refresh that source. The current wheel-review worker remains selected-rider
first and reuses cached measurements. Automatic event-wide OCR/wheel prefetch
queues should use the same planner; those queues do not yet exist. No large
historical analysis run was started while implementing this policy.

A job already processing finishes its bounded work; priorities are applied at
job boundaries. Shared CPU/GPU budget arbitration across OCR, indexing and wheel
workers remains a coordinator concern. Do not multiply workers just to improve
priority, at the expense of capture or operator latency.

## Validation

Tests cover newest-first order, explicit selection, interleaved categories,
five-place turns, late-arriving category leaders, independent start offsets and
lap counts, projected-lap exclusion, new cached race facts, completed/cancelled
jobs and existing batch stop/failure behavior.

The saved PartyCross Elite preview places Women (six laps, two-minute offset)
first, Masters (seven laps, one-minute offset) next, then Open/U19 (nine laps),
with each category's leading five before the earlier groups' tails.
`data/validation/elite-analysis-priority.json` on zbook9 is the read-only preview.

Preview without running analysis:

```sh
python -m racevideo.analysis_priority --db STORE.sqlite3 --event EVENT_ID --offset 0
```
