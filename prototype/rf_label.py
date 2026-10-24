"""Labeller that uses OUR trained RF-DETR model on Roboflow (instead of Groq / Gemini).

Same command line as gem.py, so pi_scan.py can use it:   python rf_label.py photo.jpg
Prints JSON on stdout - the gem.py fields plus counts and boxes:
  {"components": ["Resistor", "LED"], "counts": {"Resistor": 3, "LED": 1},
   "detections": [{"name": "Resistor", "confidence": 0.91, "box": [x0, y0, x1, y1]}, ...]}
Box corners are fractions of the image width/height (0-1), so they fit any resized copy.

Needs ROBOFLOW_API_KEY (Roboflow -> Settings -> API Keys -> Private API Key) and ROBOFLOW_MODEL,
the model ID shown on the model's page (setup_pi.sh works out which form Roboflow accepts). Standard library + Pillow only.
"""
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

API_KEY = os.environ["ROBOFLOW_API_KEY"]
MODEL = os.environ.get("ROBOFLOW_MODEL", "dataset_v3-qogn5/1")
API_URL = os.environ.get("ROBOFLOW_API_URL", "https://serverless.roboflow.com")
THRESHOLD = float(os.environ.get("ROBOFLOW_THRESHOLD", 0.5))     # minimum confidence kept (0-1)
SEND_SIZE = 1280                                                 # photo is shrunk to this before upload

# Model class -> name shown on the admin page
NAMES = {
    "arduino_mega": "Arduino Mega", "arduino_uno": "Arduino Uno", "esp32": "ESP32",
    "resistor": "Resistor", "electrolytic_cap": "Electrolytic Capacitor", "disk_cap": "Disk Capacitor",
    "diode": "Diode", "led": "LED", "mosfet": "MOSFET", "transistor": "Transistor",
}


def analyze(path):
    start = time.perf_counter()

    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((SEND_SIZE, SEND_SIZE))
        width, height = im.size
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)

    url = f"{API_URL}/{MODEL}?" + urllib.parse.urlencode({"api_key": API_KEY})
    req = urllib.request.Request(url, data=base64.b64encode(buf.getvalue()), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            reply = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            body = json.loads(detail)
            detail = body.get("message") or body.get("error") or detail
        except ValueError:
            pass
        sys.exit(f"Roboflow error {e.code}: {' '.join(str(detail).split())[:200]}")   # one line, for pi_scan

    detections, counts = [], {}
    for p in reply.get("predictions", []):
        if p.get("confidence", 0) < THRESHOLD:
            continue
        name = NAMES.get(p["class"], p["class"])
        x, y, w, h = p["x"], p["y"], p["width"], p["height"]          # centre + size, in sent-image pixels
        detections.append({"name": name, "confidence": round(p["confidence"], 3),
                           "box": [round((x - w / 2) / width, 4), round((y - h / 2) / height, 4),
                                   round((x + w / 2) / width, 4), round((y + h / 2) / height, 4)]})
        counts[name] = counts.get(name, 0) + 1

    print(json.dumps({"components": list(counts), "counts": counts, "detections": detections}))
    print(f"Time: {time.perf_counter() - start:.2f}s", file=sys.stderr)


if __name__ == "__main__":
    analyze(sys.argv[1])
