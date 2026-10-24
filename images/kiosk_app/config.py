"""Kiosk settings. Every value can be overridden with an environment variable of the same name
prefixed with KIOSK_, e.g.  KIOSK_THRESHOLD=0.4  or  KIOSK_CAMERA=folder."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _env(name, default, cast=str):
    value = os.environ.get("KIOSK_" + name)
    return default if value is None else cast(value)


# --- web server ---
# 127.0.0.1 = only the Pi's own browser can open the kiosk. Use 0.0.0.0 to reach /admin from a laptop.
HOST = _env("HOST", "127.0.0.1")
PORT = _env("PORT", 5000, int)
ADMIN_PIN = _env("ADMIN_PIN", "")              # empty = app.py makes a random PIN on first start (data/admin_pin)
IDLE_LOGOUT_SECONDS = _env("IDLE_LOGOUT_SECONDS", 90, int)

# --- storage ---
DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "data")))
DB_PATH = DATA_DIR / "kiosk.db"
SNAPSHOT_DIR = DATA_DIR / "snapshots"           # tray photo saved with every issue/return

# --- model ---
# .onnx  -> onnxruntime (recommended on the Pi: smaller install, ~2x faster than PyTorch on CPU)
# .pth   -> rfdetr package (PyTorch)
# "mock" -> fake detections, for working on the UI without a model
WEIGHTS = _env("WEIGHTS", str(BASE_DIR / "models" / "inference_model.onnx"))
MODEL_SIZE = _env("MODEL_SIZE", "nano")         # only used for .pth: nano / small / medium / base
THRESHOLD = _env("THRESHOLD", 0.5, float)
# Roboflow's COCO export puts the parent class "components" at id 0, then the parts A-Z.
CLASS_NAMES = _env("CLASS_NAMES", "components,arduino_mega,diode,disk_cap,electrolytic_cap,esp32,mosfet,transistor").split(",")
COCO_JSON = _env("COCO_JSON", "")               # optional: read class names from _annotations.coco.json instead

# --- camera ---
# auto      -> Pi Camera (picamera2) if present, else USB webcam (OpenCV), else image folder
# picamera2 / opencv / folder -> force one
CAMERA = _env("CAMERA", "auto")
CAMERA_INDEX = _env("CAMERA_INDEX", 0, int)     # USB webcam number for OpenCV
CAPTURE_SIZE = (1920, 1080)                     # same as the training frames
PREVIEW_WIDTH = 640                             # live preview is downscaled to keep the Pi cool
# For CAMERA=folder: cycles through these images instead of a real camera (demo on a laptop)
CAMERA_FOLDER = Path(_env("CAMERA_FOLDER", str(BASE_DIR.parent / "test_frames" / "test1")))

# Display names and starting stock, used the first time the database is created.
COMPONENTS = {
    "arduino_mega":     ("Arduino Mega", 5),
    "diode":            ("Diode", 50),
    "disk_cap":         ("Disk Capacitor", 50),
    "electrolytic_cap": ("Electrolytic Capacitor", 50),
    "esp32":            ("ESP32", 10),
    "mosfet":           ("MOSFET", 30),
    "transistor":       ("Transistor", 50),
}
