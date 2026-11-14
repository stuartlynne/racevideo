"""Geometry association and conservative consensus for neural OCR evidence."""
from collections import defaultdict
from datetime import datetime,timezone
import re
import cv2
import numpy as np
from .plate_selection import ViewTracker,consensus,iou

def numeric_proposals(frame, minimum_score):
    groups = {}
    for reading in frame['readings']:
        if not re.fullmatch('[0-9]{1,3}', reading['text']) or reading['score'] < minimum_score:
            continue
        key = tuple(np.asarray(reading['quad']).ravel())
        if key not in groups:
            groups[key] = dict(ordinal=frame['ordinal'], received_ns=frame['received_ns'],
                               monotonic_ns=frame['monotonic_ns'], quad=reading['quad'],
                               quality=dict(score=reading['detector_score'],
                                            area=abs(cv2.contourArea(np.asarray(reading['quad'], np.float32)))),
                               readings=[])
        groups[key]['readings'].append(dict(reading, ordinal=frame['ordinal']))
    merged = []
    for proposal in sorted(groups.values(), key=lambda p: -p['quality']['score']):
        duplicate = next((old for old in merged if iou(old['quad'], proposal['quad']) > .45), None)
        if duplicate is None:
            merged.append(proposal)
        else:
            duplicate['readings'].extend(proposal['readings'])
    return merged


def summarize(rows, minimum_score=.85, minimum_frames=3, minimum_motion=1., maximum_gap=3, image_size=None):
    clips = defaultdict(list)
    for row in rows:
        clips[(row['clip'], row['method'])].append(row)
    encounters = []
    for (clip, method), frames in sorted(clips.items()):
        tracker = ViewTracker(max_gap=maximum_gap, region_size=image_size, initial_distance_scale=2.5)
        for frame in sorted(frames, key=lambda r: r['ordinal']):
            tracker.update(frame['ordinal'], numeric_proposals(frame, minimum_score))
        for track in tracker.tracks:
            centers = np.array([np.mean(v['quad'], axis=0) for v in track.views])
            travel = float(np.linalg.norm(np.ptp(centers, axis=0)))
            sizes = [max(np.ptp(np.asarray(v['quad']), axis=0)) for v in track.views]
            threshold = max(20, float(np.median(sizes)) * minimum_motion)
            readings = [r for view in track.views for r in view['readings']]
            vote = consensus(readings, minimum_score=minimum_score)
            # Repeated competing orientations remain ambiguous even if one has more votes.
            repeated = [a for a in vote['alternatives'] if a['frame_count'] >= 2]
            if len(repeated) > 1:
                vote.update(status='ambiguous', number=None)
            if len(track.views) < minimum_frames or travel < threshold:
                continue
            if len(track.views) >= minimum_frames and vote['status'] == 'candidate':
                vote['status'] = 'insufficient_agreement'
            first, last = track.views[0], track.views[-1]
            encounters.append(dict(clip=clip, method=method, track=track.id,
                                   first_ordinal=first['ordinal'], last_ordinal=last['ordinal'],
                                   first_received_ns=first['received_ns'], last_received_ns=last['received_ns'],
                                   first_observed_utc=datetime.fromtimestamp(first['received_ns'] / 1e9, timezone.utc).isoformat(),
                                   frames=len(track.views), travel_pixels=travel,
                                   consensus=vote, views=track.views))
    return sorted(encounters, key=lambda e: (e['first_received_ns'], e['clip'], e['track']))
