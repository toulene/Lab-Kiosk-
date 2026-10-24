"""Prototype tray scanner - runs on the RASPBERRY PI.

Takes a photo of the tray, labels it by running a labeller script on it, then sends the photo
+ components to the admin website on the laptop. Labellers (all print JSON, keys stay on the Pi):
    gem.py         Groq, unchanged          - component types        (GROQ_API_KEY)
    rf_label.py    our trained RF-DETR model - counts + boxes drawn   (ROBOFLOW_API_KEY, ROBOFLOW_MODEL)
    gem_gemini.py  Google Gemini            - component types        (GEMINI_API_KEY)

    python3 pi_scan.py --server http://<laptop-ip>:5050 --gem ~/kiosk-proto/rf_label.py
    python3 pi_scan.py --server http://<laptop-ip>:5050 --gem ~/kiosk-proto/rf_label.py --image test.jpg --once

Press Enter to scan the tray, q + Enter to quit.
"""
import argparse
import base64
import io
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent


def capture(out_path, size):
    """Photo of the tray: picamera2 if available, else the rpicam/libcamera command-line tools."""
    try:
        from picamera2 import Picamera2
        cam = Picamera2()
        cam.configure(cam.create_still_configuration(main={"size": size}))
        cam.start()
        time.sleep(1.5)                     # let auto-exposure and white balance settle
        cam.capture_file(str(out_path))
        cam.close()
        return
    except ImportError:
        pass
    for tool in ("rpicam-still", "libcamera-still"):
        if shutil.which(tool):
            subprocess.run([tool, "-n", "-t", "1500", "--width", str(size[0]), "--height", str(size[1]),
                            "-o", str(out_path)], check=True, capture_output=True)
            return
    raise RuntimeError("No camera: install python3-picamera2 or rpicam-apps, or pass --image")


def label(gem, photo, timeout):
    """Run the labeller (gem.py exactly as it is, or rf_label.py / gem_gemini.py) and read its JSON:
    always {"components": [...]}; rf_label.py adds "counts" and "detections" (boxes)."""
    result = {"components": [], "counts": {}, "detections": [], "seconds": 0, "error": ""}
    start = time.perf_counter()
    run = subprocess.run([sys.executable, str(gem), str(photo)], capture_output=True, text=True, timeout=timeout)
    result["seconds"] = round(time.perf_counter() - start, 2)
    if run.returncode != 0:
        last = (run.stderr.strip().splitlines() or [f"{gem.name} failed"])[-1]
        result["error"] = f"Labelling failed: {last}"
        return result
    match = re.search(r"\{.*\}", run.stdout, re.S)       # tolerate stray text around the JSON
    if not match:
        result["error"] = f"Labelling gave no JSON: {run.stdout.strip()[:120]}"
        return result
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        result["error"] = f"Labelling gave bad JSON: {match.group(0)[:120]}"
        return result
    for c in data.get("components", []):                  # tidy + de-duplicate, keep order
        c = str(c).strip()
        if c and c.lower() not in (n.lower() for n in result["components"]):
            result["components"].append(c)
    result["counts"] = {str(k): int(v) for k, v in (data.get("counts") or {}).items()}
    result["detections"] = data.get("detections") or []
    return result


def draw_boxes(im, detections):
    """Outline each detection on the photo with its name, so the admin sees what was counted."""
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(im)
    w, h = im.size
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(14, w // 60))
    except OSError:
        font = ImageFont.load_default()
    colours = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6", "#9a6324", "#000075", "#808000"]
    order = []
    for d in detections:
        if d["name"] not in order:
            order.append(d["name"])
        colour = colours[order.index(d["name"]) % len(colours)]
        x0, y0, x1, y1 = d["box"][0] * w, d["box"][1] * h, d["box"][2] * w, d["box"][3] * h
        draw.rectangle([x0, y0, x1, y1], outline=colour, width=max(2, w // 400))
        text = f"{d['name']} {d.get('confidence', 0):.0%}"
        tx0, ty0, tx1, ty1 = draw.textbbox((x0, y0), text, font=font)
        top = max(0, y0 - (ty1 - ty0) - 4)
        draw.rectangle([x0, top, x0 + (tx1 - tx0) + 6, top + (ty1 - ty0) + 4], fill=colour)
        draw.text((x0 + 3, top + 1), text, fill="white", font=font)


def send(server, token, photo, result, captured_at):
    with Image.open(photo) as im:                         # smaller copy for the network, the original stays on the Pi
        im = im.convert("RGB")
        im.thumbnail((1280, 1280))
        if result["detections"]:
            draw_boxes(im, result["detections"])
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    body = json.dumps({
        "image_b64": base64.b64encode(buf.getvalue()).decode(),
        "components": result["components"], "counts": result["counts"],
        "seconds": result["seconds"], "error": result["error"],
        "captured_at": captured_at, "device": socket.gethostname(),
    }).encode()
    req = urllib.request.Request(server.rstrip("/") + "/api/scan", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Token": token})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["id"]


def scan_once(args):
    captured_at = time.strftime("%Y-%m-%d %H:%M:%S")
    if args.image:
        photo = Path(args.image)
    else:
        photo = args.out / f"tray_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
        print("  capturing...", flush=True)
        capture(photo, (args.width, args.height))
    print(f"  labelling with {args.gem.name}...", flush=True)
    result = label(args.gem, photo, args.timeout)
    if result["error"]:
        print(f"  {result['error']}")
    else:
        found = [f"{c} x{result['counts'][c]}" if c in result["counts"] else c for c in result["components"]]
        print(f"  found ({result['seconds']}s): {', '.join(found) or 'nothing'}")
    try:
        scan_id = send(args.server, args.token, photo, result, captured_at)
        print(f"  sent to admin as {scan_id}")
    except (urllib.error.URLError, OSError) as e:
        print(f"  could not reach the admin laptop at {args.server}: {e}  (photo kept at {photo})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", required=True, help="admin laptop, e.g. http://<laptop-ip>:5050")
    p.add_argument("--gem", type=Path, default=HERE / "gem.py",
                   help="labeller script: gem.py (Groq), rf_label.py (our Roboflow model) or gem_gemini.py")
    p.add_argument("--image", help="use this photo instead of the camera (testing)")
    p.add_argument("--once", action="store_true", help="scan once and exit instead of waiting for Enter")
    p.add_argument("--out", type=Path, default=HERE / "captures", help="where tray photos are saved")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--timeout", type=int, default=60, help="seconds to wait for gem.py")
    p.add_argument("--token", default="", help="must match PROTO_TOKEN on the laptop, if that is set")
    args = p.parse_args()

    args.gem = args.gem.expanduser()
    if not args.gem.exists():
        sys.exit(f"gem.py not found at {args.gem} - pass --gem /path/to/gem.py")
    args.out.mkdir(parents=True, exist_ok=True)

    if args.once:
        scan_once(args)
        return
    print(f"Kiosk ready. Sending scans to {args.server}")
    while True:
        cmd = input("\nPlace components on the tray, then press Enter to scan (q to quit): ").strip().lower()
        if cmd == "q":
            break
        try:
            scan_once(args)
        except Exception as e:
            print(f"  scan failed: {e}")


if __name__ == "__main__":
    main()
