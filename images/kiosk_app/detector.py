"""Loads the trained RF-DETR model once and counts the parts in a tray photo.

Backends, picked from the weights file extension:
  .onnx -> onnxruntime   (use this on the Pi; export with export_onnx.py on your laptop)
  .pth  -> rfdetr        (PyTorch; works on the Pi too, just slower and a much bigger install)
  mock  -> random boxes  (UI work without a model)
"""
import json
import random
import threading
import time
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config

PALETTE = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#469990"]
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def load_class_names():
    if config.COCO_JSON:
        cats = json.loads(Path(config.COCO_JSON).read_text())["categories"]
        return {c["id"]: c["name"] for c in cats}
    return dict(enumerate(config.CLASS_NAMES))


class OnnxBackend:
    def __init__(self, path):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4            # Pi 4 has 4 cores
        self.session = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        self.size = (inp.shape[3], inp.shape[2])  # (w, h), e.g. 384x384 for nano

    def predict(self, image, threshold):
        w, h = image.size
        x = np.asarray(image.resize(self.size, Image.BILINEAR), dtype=np.float32) / 255.0
        x = ((x - MEAN) / STD).transpose(2, 0, 1)[None]
        outputs = self.session.run(None, {self.input_name: x})
        boxes = next(o for o in outputs if o.shape[-1] == 4)[0]          # (queries, 4) cx,cy,w,h in 0-1
        logits = next(o for o in outputs if o.shape[-1] != 4)[0]         # (queries, classes)

        # Same post-processing as rfdetr: top 300 (query, class) pairs by sigmoid score.
        prob = 1 / (1 + np.exp(-logits))
        n_cls = prob.shape[1]
        flat = prob.ravel()
        top = np.argsort(-flat)[:300]
        scores, queries, classes = flat[top], top // n_cls, top % n_cls
        keep = scores >= threshold
        cx, cy, bw, bh = boxes[queries[keep]].T
        xyxy = np.stack([(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h], axis=1)
        return xyxy, classes[keep], scores[keep]


class TorchBackend:
    def __init__(self, path):
        import rfdetr
        cls = {"nano": "RFDETRNano", "small": "RFDETRSmall", "medium": "RFDETRMedium", "base": "RFDETRBase"}
        self.model = getattr(rfdetr, cls[config.MODEL_SIZE])(pretrain_weights=path)
        try:
            self.model.optimize_for_inference()
        except Exception:
            pass

    def predict(self, image, threshold):
        det = self.model.predict(image, threshold=threshold)
        return det.xyxy, det.class_id, det.confidence


class MockBackend:
    """Puts a few random boxes on the image so the screens can be tested without a model."""
    def predict(self, image, threshold):
        w, h = image.size
        n = random.randint(1, 5)
        boxes, classes = [], []
        for _ in range(n):
            x, y = random.uniform(0.05, 0.8) * w, random.uniform(0.05, 0.75) * h
            boxes.append([x, y, x + w * 0.12, y + h * 0.18])
            classes.append(random.randint(1, len(config.CLASS_NAMES) - 1))
        return np.array(boxes), np.array(classes), np.random.uniform(threshold, 0.99, n)


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0


class Detector:
    def __init__(self):
        self.names = load_class_names()
        weights = config.WEIGHTS
        if weights == "mock":
            self.backend, self.kind = MockBackend(), "mock"
        elif not Path(weights).exists():
            print(f"[detector] weights not found at {weights} - using MOCK detections")
            self.backend, self.kind = MockBackend(), "mock"
        elif weights.endswith(".onnx"):
            self.backend, self.kind = OnnxBackend(weights), "onnx"
        else:
            self.backend, self.kind = TorchBackend(weights), "rfdetr"
        self.lock = threading.Lock()          # one inference at a time
        print(f"[detector] backend: {self.kind}")

    def detect(self, image, threshold=None):
        """Returns (counts {class: n}, detections [...], annotated PIL image, seconds)."""
        threshold = config.THRESHOLD if threshold is None else threshold
        start = time.perf_counter()
        with self.lock:
            xyxy, class_ids, scores = self.backend.predict(image, threshold)
        elapsed = time.perf_counter() - start

        dets = sorted(({"box": [float(v) for v in b], "class": self.names.get(int(c), f"class_{c}"),
                        "conf": float(s)} for b, c, s in zip(xyxy, class_ids, scores)),
                      key=lambda d: -d["conf"])
        # DETR rarely duplicates, but one part labelled as two classes would be counted twice.
        kept = []
        for d in dets:
            if d["class"] == self.names.get(0) or d["class"] not in config.COMPONENTS:
                continue                       # skip the parent "components" class / unknown ids
            if all(_iou(d["box"], k["box"]) < 0.7 for k in kept):
                kept.append(d)

        counts = Counter(d["class"] for d in kept)
        return dict(counts), kept, self.annotate(image, kept), elapsed

    def annotate(self, image, dets):
        out = image.copy()
        draw = ImageDraw.Draw(out)
        line = max(3, image.width // 400)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(18, image.width // 60))
        except OSError:
            try:
                font = ImageFont.truetype("arialbd.ttf", max(18, image.width // 60))
            except OSError:
                font = ImageFont.load_default()
        classes = list(config.COMPONENTS)
        for d in dets:
            color = PALETTE[classes.index(d["class"]) % len(PALETTE)]
            x0, y0, x1, y1 = d["box"]
            draw.rectangle([x0, y0, x1, y1], outline=color, width=line)
            text = f"{config.COMPONENTS[d['class']][0]} {d['conf']:.2f}"
            tb = draw.textbbox((x0, y0), text, font=font)
            ty = y0 - (tb[3] - tb[1]) - 8 if y0 > (tb[3] - tb[1]) + 8 else y0
            draw.rectangle([x0, ty, x0 + tb[2] - tb[0] + 10, ty + tb[3] - tb[1] + 8], fill=color)
            draw.text((x0 + 5, ty + 2 - (tb[1] - y0)), text, fill="white", font=font)
        return out
