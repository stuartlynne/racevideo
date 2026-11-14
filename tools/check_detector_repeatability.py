"""Check CPU detection after alternating image shapes; never changes source frames."""
import os
os.environ.setdefault('DISABLE_MODEL_SOURCE_CHECK', 'True')
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
os.environ.setdefault('OMP_NUM_THREADS', '2')

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import cv2
import numpy as np
from paddleocr import TextDetection
from tools.field_ocr_probe import result_dict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('store', type=Path)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--clip', type=int, required=True)
    parser.add_argument('--ordinal', type=int, required=True)
    parser.add_argument('--roi', type=float, nargs=4, default=[.05, .4, .98, .9])
    parser.add_argument('--mkldnn', action='store_true')
    args = parser.parse_args()
    connection = sqlite3.connect(args.store.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        jpeg = connection.execute('SELECT jpeg FROM frames WHERE clip_id=? AND ordinal=?',
                                  (args.clip, args.ordinal)).fetchone()[0]
    finally:
        connection.close()
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    h, w = image.shape[:2]
    left, top, right, bottom = [round(v * s) for v, s in zip(args.roi, (w, h, w, h))]
    image = image[top:bottom, left:right]
    model = TextDetection(model_name='PP-OCRv5_mobile_det',
                          model_dir=str(args.models / 'PP-OCRv5_mobile_det'),
                          device='cpu', cpu_threads=2, enable_mkldnn=args.mkldnn)
    previous = {}
    cases = [(960, image), (1536, image), (960, image[:640, :960])]
    for step, (size, view) in enumerate(cases * 3):
        before = hashlib.sha256(view.tobytes()).hexdigest()
        result = result_dict(list(model.predict(input=view, limit_side_len=size, limit_type='max'))[0])
        if before != hashlib.sha256(view.tobytes()).hexdigest():
            raise RuntimeError('Predictor mutated source pixels')
        digest = hashlib.sha256(json.dumps(result['dt_polys']).encode()).hexdigest()
        key = (before, size)
        if key in previous and previous[key] != digest:
            raise RuntimeError('Identical input/scale produced different detection polygons')
        previous[key] = digest
        print(step, size, view.shape, 'detections', len(result['dt_polys']), 'hash', digest[:12], flush=True)


if __name__ == '__main__':
    main()
