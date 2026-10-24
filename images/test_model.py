"""Run a trained RF-DETR model on a folder of frames.

Saves each frame with labelled boxes drawn on it and prints how often each class was found.

Usage:
    py test_model.py --weights checkpoint_best_total.pth --images test_frames/test1
    py test_model.py --weights checkpoint_best_total.pth --images test_frames/test1 --threshold 0.4 --size small
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import rfdetr
import supervision as sv
from PIL import Image

MODEL_CLASSES = {"nano": "RFDETRNano", "small": "RFDETRSmall", "medium": "RFDETRMedium", "base": "RFDETRBase"}

# Roboflow's COCO export puts a parent class at id 0, so the parts start at 1.
DEFAULT_NAMES = ["components", "diode", "disk_cap", "esp32", "mosfet", "transistor"]

parser = argparse.ArgumentParser()
parser.add_argument("--weights", required=True, help="trained .pth file")
parser.add_argument("--images", required=True, help="folder of .jpg frames")
parser.add_argument("--out", default=None, help="where annotated frames go (default: <images>_results)")
parser.add_argument("--size", default="nano", choices=MODEL_CLASSES, help="model size you trained")
parser.add_argument("--threshold", type=float, default=0.5, help="minimum confidence to keep a box")
parser.add_argument("--coco-json", default=None,
                    help="_annotations.coco.json from your export, to read class names exactly")
args = parser.parse_args()

names = DEFAULT_NAMES
if args.coco_json:
    cats = json.loads(Path(args.coco_json).read_text())["categories"]
    names = {c["id"]: c["name"] for c in cats}


def name_of(class_id):
    try:
        return names[class_id]
    except (IndexError, KeyError):
        return f"class_{class_id}"


model = getattr(rfdetr, MODEL_CLASSES[args.size])(pretrain_weights=args.weights)

images = sorted(Path(args.images).glob("*.jpg"))
out_dir = Path(args.out) if args.out else Path(args.images).with_name(Path(args.images).name + "_results")
out_dir.mkdir(parents=True, exist_ok=True)

box_drawer = sv.BoxAnnotator()
label_drawer = sv.LabelAnnotator()
frames_with = Counter()   # how many frames each class appeared in
total_boxes = Counter()
confidences = {}

for path in images:
    image = Image.open(path).convert("RGB")
    det = model.predict(image, threshold=args.threshold)
    labels = [f"{name_of(c)} {p:.2f}" for c, p in zip(det.class_id, det.confidence)]

    annotated = box_drawer.annotate(image.copy(), det)
    annotated = label_drawer.annotate(annotated, det, labels=labels)
    annotated.save(out_dir / path.name)

    found = [name_of(c) for c in det.class_id]
    for n in set(found):
        frames_with[n] += 1
    for n, p in zip(found, det.confidence):
        total_boxes[n] += 1
        confidences.setdefault(n, []).append(float(p))
    print(f"{path.name}: {', '.join(labels) or 'nothing'}")

print(f"\n{len(images)} frames, threshold {args.threshold}")
print(f"{'class':<12}{'frames':>8}{'boxes':>8}{'avg conf':>10}")
for n in sorted(total_boxes):
    avg = sum(confidences[n]) / len(confidences[n])
    print(f"{n:<12}{frames_with[n]:>8}{total_boxes[n]:>8}{avg:>10.2f}")
print(f"\nAnnotated frames saved to {out_dir}")
