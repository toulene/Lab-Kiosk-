"""Run on your LAPTOP (where rfdetr + PyTorch are installed), not on the Pi.

Converts the trained .pth to ONNX, then runs both on a few test frames and prints the counts
side by side, so you know the ONNX file behaves the same before copying it to the Pi.

    py -m pip install "rfdetr[onnxexport]" onnxruntime
    py export_onnx.py --weights checkpoint_best_total.pth
    py export_onnx.py --weights checkpoint_best_total.pth --size small --images ..\\test_frames\\test1

Output: models/inference_model.onnx  (the path config.py expects)
"""
import argparse
import shutil
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--weights", required=True)
parser.add_argument("--size", default="nano", choices=["nano", "small", "medium", "base"])
parser.add_argument("--images", default=str(Path(__file__).parent.parent / "test_frames" / "test1"))
parser.add_argument("--threshold", type=float, default=0.5)
args = parser.parse_args()

import rfdetr
from PIL import Image

here = Path(__file__).parent
out_dir = here / "models"
out_dir.mkdir(exist_ok=True)

cls = {"nano": "RFDETRNano", "small": "RFDETRSmall", "medium": "RFDETRMedium", "base": "RFDETRBase"}[args.size]
model = getattr(rfdetr, cls)(pretrain_weights=args.weights)
model.export(output_dir=str(out_dir / "export"))
shutil.copy(out_dir / "export" / "inference_model.onnx", out_dir / "inference_model.onnx")
print(f"\nSaved {out_dir / 'inference_model.onnx'}")

# --- compare PyTorch vs ONNX on a few frames ---
sys.path.insert(0, str(here))
import config
from detector import OnnxBackend, load_class_names

names = load_class_names()
onnx = OnnxBackend(str(out_dir / "inference_model.onnx"))
files = sorted(Path(args.images).glob("*.jpg"))
images = files[::max(1, len(files) // 8)][:8]       # 8 frames spread across the folder


def summary(class_ids):
    counts = {}
    for c in class_ids:
        counts[names.get(int(c), c)] = counts.get(names.get(int(c), c), 0) + 1
    return ", ".join(f"{n}:{k}" for n, k in sorted(counts.items())) or "nothing"


print(f"\n{'frame':<20}{'pytorch':<40}onnx")
same = 0
for p in images:
    img = Image.open(p).convert("RGB")
    a = summary(model.predict(img, threshold=args.threshold).class_id)
    b = summary(onnx.predict(img, args.threshold)[1])
    same += a == b
    print(f"{p.name:<20}{a:<40}{b}")
print(f"\n{same}/{len(images)} frames give identical counts.")
