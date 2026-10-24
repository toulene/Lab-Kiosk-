"""One camera shared by the live preview and the tray scan.

  picamera2 -> Raspberry Pi Camera Module (what the training videos were shot with)
  opencv    -> USB webcam
  folder    -> cycles through .jpg files, for running the demo on a laptop with no camera
"""
import io
import itertools
import threading
import time

from PIL import Image

import config


class PiCamera:
    def __init__(self):
        from picamera2 import Picamera2
        self.cam = Picamera2()
        # "RGB888" in libcamera terms is B,G,R byte order in the numpy array.
        cfg = self.cam.create_video_configuration(main={"size": config.CAPTURE_SIZE, "format": "RGB888"})
        self.cam.configure(cfg)
        self.cam.start()
        time.sleep(1)  # let auto-exposure / white balance settle

    def read(self):
        return Image.fromarray(self.cam.capture_array()[:, :, ::-1])


class UsbCamera:
    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(config.CAMERA_INDEX)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAPTURE_SIZE[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAPTURE_SIZE[1])
        ok, _ = self.cap.read()
        if not ok:
            raise RuntimeError(f"no webcam at index {config.CAMERA_INDEX}")

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("webcam read failed")
        return Image.fromarray(self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB))


class FolderCamera:
    def __init__(self):
        files = sorted(config.CAMERA_FOLDER.glob("*.jpg"))
        if not files:
            raise RuntimeError(f"no .jpg files in {config.CAMERA_FOLDER}")
        self.files = itertools.cycle(files)
        self.current = Image.open(next(self.files)).convert("RGB")
        self.changed = time.monotonic()

    def read(self):
        if time.monotonic() - self.changed > 2:        # show a new frame every 2 s
            self.current = Image.open(next(self.files)).convert("RGB")
            self.changed = time.monotonic()
        return self.current


class Camera:
    def __init__(self):
        order = {"auto": [PiCamera, UsbCamera, FolderCamera], "picamera2": [PiCamera],
                 "opencv": [UsbCamera], "folder": [FolderCamera]}[config.CAMERA]
        self.source, errors = None, []
        for kind in order:
            try:
                self.source = kind()
                break
            except Exception as e:
                errors.append(f"{kind.__name__}: {e}")
        self.kind = type(self.source).__name__ if self.source else "none"
        self.error = None if self.source else "; ".join(errors)
        print(f"[camera] {self.kind}" + (f" ({self.error})" if self.error else ""))
        self.lock = threading.Lock()

    def capture(self):
        if not self.source:
            raise RuntimeError(f"No camera available - {self.error}")
        with self.lock:
            return self.source.read()

    def preview_jpeg(self):
        img = self.capture()
        h = round(img.height * config.PREVIEW_WIDTH / img.width)
        buf = io.BytesIO()
        img.resize((config.PREVIEW_WIDTH, h)).save(buf, "JPEG", quality=70)
        return buf.getvalue()
