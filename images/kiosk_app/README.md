# Lab Component Kiosk

Touch-screen kiosk for issuing and returning lab components. A student logs in with their ID
card number, places parts in the tray, the RF-DETR model counts them, and the issue/return is
saved to a database together with a photo of the tray.

## How it works on the Pi

Everything runs on the Raspberry Pi 4. Nothing needs the internet.

```
 ┌──────────── Raspberry Pi 4 ────────────────────────────────────────┐
 │                                                                    │
 │  Chromium (full-screen kiosk mode)  ◄──── HDMI monitor / touch     │
 │        │  http://127.0.0.1:5000                                    │
 │        ▼                                                           │
 │  app.py  (Flask + waitress, started by systemd at boot)            │
 │    ├── camera.py    Pi Camera → 1920x1080 frame of the tray        │
 │    ├── detector.py  RF-DETR (ONNX Runtime) → counts per part       │
 │    └── db.py        SQLite: data/kiosk.db + data/snapshots/*.jpg   │
 └────────────────────────────────────────────────────────────────────┘
```

* The **server** (`app.py`) loads the model once at startup and keeps it in memory, so each
  scan only pays for one inference.
* The **interface** is a web page. Chromium opens it full-screen at login, so the Pi looks like
  a dedicated kiosk with no desktop visible. The same page works on the 7" screen later.
* **Login**: the card-number box accepts typing. Most USB RFID readers (125 kHz/EM4100) act as a
  keyboard: they type the card number and press Enter. When you plug one in, it will just work
  with no code change.

### Kiosk flow
1. **Login**: enter the card number on the keypad (or tap a card later).
2. **Dashboard**: shows the parts you currently hold and your recent activity, with buttons for
   *Issue* and *Return*.
3. **Scan**: live camera view → *Scan tray* → photo with boxes + counts. Counts can be corrected
   with −/+ (the database keeps both the model's count and the confirmed count).
4. **Confirm**: saved to the database, stock updated. The kiosk logs out automatically
   after 8 s, or after 90 s with no touches on any screen.

Admin page at `/admin` (PIN printed when the server starts, see Settings below): register cards, set stock, see who
has what, browse every transaction with its tray photo, and export a CSV.

---

## 1. Try it on your laptop first

```bash
py -m pip install flask waitress numpy pillow onnxruntime
py app.py
```
Open http://localhost:5000 and log in with demo card **1001**. With no model or camera, it uses
mock detections and cycles through `../test_frames/test1` as a fake camera. The grey line at the
bottom of the login screen shows which model and camera are in use.

## 2. Convert the trained model to ONNX (on the laptop)

ONNX Runtime is much lighter to install on the Pi than PyTorch, and faster on its CPU.

```bash
py -m pip install "rfdetr[onnxexport]" onnxruntime
py export_onnx.py --weights path\to\checkpoint_best_total.pth
```
This writes `models/inference_model.onnx` and prints the PyTorch vs ONNX counts on a few test frames.
They should match. Run `py app.py` again; the login screen should now say `Model: onnx`.

If you trained a size other than nano, pass `--size small`, and so on.

## 3. Move it to the Pi

Use **Raspberry Pi OS 64-bit (Bookworm or newer, with desktop)**. Copy the whole `kiosk_app`
folder, including `models/`, to the Pi (USB stick, or `scp -r kiosk_app pi@<pi-ip>:~/`). Then on the Pi:

```bash
cd ~/kiosk_app
bash deploy/install.sh
sudo reboot
```
`install.sh` does the following:
* installs `python3-picamera2` (apt) and makes a venv that can see it, plus Flask, waitress and onnxruntime
* creates the `lab-kiosk` systemd service, so the server starts at boot and restarts if it crashes
* adds `deploy/start_browser.sh` to desktop autostart, so Chromium opens full-screen once the server is up
* turns on desktop auto-login and turns off screen blanking

Useful commands on the Pi:
```bash
systemctl status lab-kiosk          # is the server running?
journalctl -u lab-kiosk -f          # live log (camera/model messages, errors)
sudo systemctl restart lab-kiosk    # after changing config.py or the model
```
To leave kiosk mode: plug in a keyboard and press **Alt+F4**.

## Settings (`config.py`)

| Setting | Default | Notes |
|---|---|---|
| `WEIGHTS` | `models/inference_model.onnx` | `.onnx`, `.pth`, or `mock` |
| `THRESHOLD` | `0.5` | lower it if parts are missed, raise it if there are false boxes |
| `CLASS_NAMES` | `components, arduino_mega, …` | id order from the Roboflow COCO export (or set `COCO_JSON`) |
| `CAMERA` | `auto` | `picamera2`, `opencv` (USB webcam), or `folder` |
| `HOST` | `127.0.0.1` | set to `0.0.0.0` to open `/admin` from a laptop on the same Wi-Fi |
| `ADMIN_PIN` | *(none)* | set `KIOSK_ADMIN_PIN`, or a random 6-digit PIN is created on first start, saved in `data/admin_pin` and printed in the log (`journalctl -u lab-kiosk`) |
| `IDLE_LOGOUT_SECONDS` | `90` | |

Any setting can also be overridden with an environment variable, e.g. `KIOSK_THRESHOLD=0.4`.

## Notes
* **Speed**: the scan screen shows how long inference took. Expect roughly 1–3 s per scan for
  RF-DETR nano on the Pi 4 CPU. Give the Pi a heatsink or fan, because it throttles when hot.
* **Lighting and background**: the model was trained on 1920x1080 Pi Camera frames of parts on a
  white background, so the tray should look the same: white base, even lighting, camera at the same height.
* **Database**: `data/kiosk.db` (SQLite). To back up, copy the `data/` folder. Open it with
  [DB Browser for SQLite](https://sqlitebrowser.org/) to inspect it.
* **RC522 reader (SPI) instead of USB**: the RC522 doesn't act as a keyboard. Add a small
  thread that reads the card and logs the kiosk in. Ask if you go that route.
