"""Geometry-only association of offline OCR candidates, with conflicting reads retained.

This produces review candidates, not race results or calibrated finish times.
Recognized values never enter association; three-digit form only selects proposals.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import cv2
import numpy as np
from racevideo.plate_selection import ViewTracker, consensus, iou


from racevideo.encounters import numeric_proposals, summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--minimum-score', type=float, default=.85)
    parser.add_argument('--minimum-frames', type=int, default=3)
    parser.add_argument('--minimum-motion', type=float, default=1., help='Travel in median text-box widths')
    parser.add_argument('--maximum-gap', type=int, default=3, help='Maximum gap between numeric proposals in source frames')
    parser.add_argument('--image-size', type=int, nargs=2, help='Native width height; close tracks on predicted exits')
    args = parser.parse_args()
    raw = json.loads(args.input.read_text())
    encounters = summarize(raw['results'], args.minimum_score, args.minimum_frames, args.minimum_motion,
                           args.maximum_gap, args.image_size)
    report = dict(input=str(args.input.resolve()), confirmed_passings=False,
                  notes=['Selected by numeric form; values do not enter geometric association.',
                         'Alternatives and repeated orientation conflicts are retained.',
                         'Timestamps describe visible evidence, not calibrated finish-line crossings.',
                         'Separate methods must never count as separate riders.'],
                  parameters=vars(args) | dict(input=str(args.input), output=str(args.output)),
                  encounters=encounters)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    for e in encounters:
        print(e['clip'], e['first_ordinal'], e['last_ordinal'], e['frames'],
              e['consensus']['status'],
              [(r['number'], r['frame_count']) for r in e['consensus']['alternatives']])


if __name__ == '__main__':
    main()
