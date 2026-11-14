"""Check real AMD Vulkan neural inference against a known FP32 CPU/numpy result.

This is a tiny convolution smoke test, not an OCR model or performance benchmark.
Run in the separate .venv-ocr-vulkan environment. No recording database is opened.
"""
import argparse
import importlib.metadata
import json
from pathlib import Path
import struct
import tempfile
import time
import ncnn
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--device', type=int, default=0)
    args = parser.parse_args()
    if args.device >= ncnn.get_gpu_count():
        raise RuntimeError('Requested Vulkan GPU is unavailable')
    info = ncnn.get_gpu_device(args.device).info()
    name = info.device_name()
    if 'AMD' not in name or info.type() != 0:
        raise RuntimeError(f'Expected a discrete AMD GPU, got {name}')
    image = np.random.default_rng(42).uniform(-1, 1, (8, 128, 128)).astype(np.float32)
    padded = np.pad(image, ((0, 0), (1, 1), (1, 1)))
    expected = sum(padded[:, y:y+128, x:x+128].sum(axis=0) for y in range(3) for x in range(3)) / 72
    expected = np.repeat(np.maximum(expected, 0)[None], 3, axis=0)
    weights = np.full((3, 8, 3, 3), 1 / 72, dtype=np.float32)
    parameter = '''7767517
3 3
Input input 0 1 data 0=128 1=128 2=8
Convolution average 1 1 data conv 0=3 1=3 3=1 4=1 5=0 6=216
ReLU relu 1 1 conv output
'''
    results = {}
    with tempfile.TemporaryDirectory() as folder:
        model = Path(folder) / 'convolution.bin'
        model.write_bytes(struct.pack('<I', 0) + weights.tobytes())
        for gpu in (False, True):
            net = ncnn.Net()
            net.opt.num_threads = 2
            net.opt.use_vulkan_compute = gpu
            net.opt.use_fp16_packed = False
            net.opt.use_fp16_storage = False
            net.opt.use_fp16_arithmetic = False
            if gpu:
                net.set_vulkan_device(args.device)
            if net.load_param_mem(parameter) != 0 or net.load_model(str(model)) != 0:
                raise RuntimeError('Cannot load convolution test model')
            layers = net.layers() if callable(net.layers) else net.layers
            details = [dict(name=layer.name, type=layer.type,
                            supports_vulkan=bool(layer.support_vulkan)) for layer in layers]
            if gpu and not any(layer['type'] == 'Convolution' and layer['supports_vulkan'] for layer in details):
                raise RuntimeError('Convolution did not load as a Vulkan-capable layer')
            extractor = net.create_extractor()
            started = time.perf_counter()
            # Mat(numpy) borrows storage; retain an owned native input through extract.
            native_input = ncnn.Mat(image).clone()
            if extractor.input('data', native_input) != 0:
                raise RuntimeError('Cannot submit input')
            code, output = extractor.extract('output')
            if code != 0:
                raise RuntimeError('Inference failed')
            array = output.numpy().copy()
            np.testing.assert_allclose(array, expected, rtol=1e-4, atol=1e-6)
            results['vulkan' if gpu else 'cpu'] = dict(
                shape=list(array.shape), max_abs_error=float(np.max(np.abs(array - expected))),
                seconds_including_first_inference=time.perf_counter() - started,
                layers=details)
    report = dict(device=name, device_index=args.device,
                  ncnn_version=importlib.metadata.version('ncnn'), fp16=False,
                  test='Known 3x3 convolution + ReLU; not OCR or a performance benchmark',
                  recording_database_opened=False, results=results, passed=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
