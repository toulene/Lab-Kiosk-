"""Lab component kiosk - web server.

Runs the model, talks to the camera and the database, and serves the touch-screen UI that
Chromium shows full-screen on the Pi's monitor.

    python app.py            then open http://localhost:5000        (admin: /admin)
"""
import csv
import io
import secrets
import shutil
import time
from functools import wraps

from flask import Flask, Response, jsonify, render_template, request, send_from_directory, session

import config
import db
from camera import Camera
from detector import Detector

db.init()
PENDING_DIR = config.SNAPSHOT_DIR / "pending"
PENDING_DIR.mkdir(parents=True, exist_ok=True)
for old in PENDING_DIR.glob("*.jpg"):      # scans nobody confirmed before the last shutdown
    old.unlink(missing_ok=True)

key_file = config.DATA_DIR / "secret_key"
if not key_file.exists():
    key_file.write_text(secrets.token_hex(32))

# No PIN is built into the code: set KIOSK_ADMIN_PIN, or one is generated once and kept in data/admin_pin.
if not config.ADMIN_PIN:
    pin_file = config.DATA_DIR / "admin_pin"
    if not pin_file.exists():
        pin_file.write_text(f"{secrets.randbelow(10**6):06d}")
    config.ADMIN_PIN = pin_file.read_text().strip()
    print(f"[admin] PIN is {config.ADMIN_PIN}  (stored in {pin_file}; set KIOSK_ADMIN_PIN to choose your own)")

app = Flask(__name__)
app.secret_key = key_file.read_text()
detector = Detector()
camera = Camera()
pending_scans = {}     # scan_id -> {card_id, counts}; confirmed scans move into the database


def logged_in(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        card_id, last = session.get("card_id"), session.get("last_seen", 0)
        if not card_id or time.time() - last > config.IDLE_LOGOUT_SECONDS:
            session.pop("card_id", None)
            return jsonify(error="Session expired - please scan your card again."), 401
        session["last_seen"] = time.time()
        return view(card_id, *args, **kwargs)
    return wrapper


def admin_only(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return jsonify(error="Admin PIN required"), 401
        return view(*args, **kwargs)
    return wrapper


# ---------- pages ----------

@app.get("/")
def kiosk():
    return render_template("kiosk.html", idle_seconds=config.IDLE_LOGOUT_SECONDS)


@app.get("/admin")
def admin():
    return render_template("admin.html")


@app.get("/snapshots/<path:name>")
def snapshot(name):
    return send_from_directory(config.SNAPSHOT_DIR, name)


@app.get("/preview.jpg")
def preview():
    """One small frame of the tray; the page reloads it in a loop as a live view."""
    try:
        return Response(camera.preview_jpeg(), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})
    except Exception as e:
        return Response(str(e), status=503)


@app.get("/api/status")
def status():
    return jsonify(detector=detector.kind, camera=camera.kind, camera_error=camera.error)


# ---------- kiosk user ----------

@app.post("/api/login")
def login():
    card_id = str(request.json.get("card_id", "")).strip()
    user = db.get_user(card_id)
    if not user:
        return jsonify(error=f"Card {card_id or '(blank)'} is not registered. Please contact the lab in-charge."), 404
    session.clear()
    session.update(card_id=card_id, last_seen=time.time())
    return jsonify(user=user)


@app.post("/api/logout")
def logout():
    session.pop("card_id", None)
    return jsonify(ok=True)


@app.get("/api/me")
@logged_in
def me(card_id):
    return jsonify(user=db.get_user(card_id), holdings=db.holdings(card_id),
                   history=db.history(card_id, limit=10), components=db.components())


@app.post("/api/scan")
@logged_in
def scan(card_id):
    try:
        image = camera.capture()
    except Exception as e:
        return jsonify(error=str(e)), 503
    counts, dets, annotated, seconds = detector.detect(image)
    scan_id = secrets.token_hex(8)
    annotated.save(PENDING_DIR / f"{scan_id}.jpg", quality=85)
    pending_scans[scan_id] = {"card_id": card_id, "counts": counts}
    return jsonify(scan_id=scan_id, counts=counts, detections=len(dets), seconds=round(seconds, 2),
                   image=f"/snapshots/pending/{scan_id}.jpg", components=db.components(),
                   holdings={h["component"]: h["qty"] for h in db.holdings(card_id)})


@app.post("/api/confirm")
@logged_in
def confirm(card_id):
    body = request.json
    action, scan = body.get("action"), pending_scans.get(body.get("scan_id"))
    if action not in ("issue", "return"):
        return jsonify(error="Bad action"), 400
    if not scan or scan["card_id"] != card_id:
        return jsonify(error="Scan expired - please scan the tray again."), 400
    items = {comp: (int(qty), scan["counts"].get(comp, 0)) for comp, qty in body.get("items", {}).items()}
    image = f"{time.strftime('%Y%m%d_%H%M%S')}_{action}_{card_id}.jpg"
    try:
        tx_id = db.record(card_id, action, items, image)
    except db.StockError as e:
        return jsonify(error=str(e)), 409
    shutil.move(PENDING_DIR / f"{body['scan_id']}.jpg", config.SNAPSHOT_DIR / image)
    pending_scans.pop(body["scan_id"], None)
    return jsonify(ok=True, transaction_id=tx_id)


# ---------- admin ----------

@app.post("/api/admin/login")
def admin_login():
    if request.json.get("pin") != config.ADMIN_PIN:
        return jsonify(error="Wrong PIN"), 401
    session["admin"] = True
    return jsonify(ok=True)


@app.get("/api/admin/summary")
@admin_only
def admin_summary():
    return jsonify(users=db.rows("SELECT * FROM users ORDER BY name"), components=db.components(),
                   holdings=db.holdings(), history=db.history(limit=200))


@app.post("/api/admin/users")
@admin_only
def add_user():
    u = request.json
    if not u.get("card_id", "").strip() or not u.get("name", "").strip():
        return jsonify(error="Card number and name are required"), 400
    with db.session() as c:
        c.execute("""INSERT INTO users (card_id, name, roll_no, department) VALUES (?, ?, ?, ?)
                     ON CONFLICT(card_id) DO UPDATE SET name=excluded.name, roll_no=excluded.roll_no,
                     department=excluded.department""",
                  (u["card_id"].strip(), u["name"].strip(), u.get("roll_no", ""), u.get("department", "")))
    return jsonify(ok=True)


@app.delete("/api/admin/users/<card_id>")
@admin_only
def delete_user(card_id):
    if db.rows("SELECT 1 FROM transactions WHERE card_id = ? LIMIT 1", card_id):
        return jsonify(error="This user has issue/return records, so they can't be deleted."), 409
    with db.session() as c:
        c.execute("DELETE FROM users WHERE card_id = ?", (card_id,))
    return jsonify(ok=True)


@app.post("/api/admin/stock")
@admin_only
def set_stock():
    with db.session() as c:
        c.execute("UPDATE components SET stock = ? WHERE name = ?",
                  (max(0, int(request.json["stock"])), request.json["name"]))
    return jsonify(ok=True)


@app.get("/api/admin/export.csv")
@admin_only
def export_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["transaction", "time", "card_id", "name", "action", "component", "qty", "detected_qty", "image"])
    for tx in db.history(limit=1_000_000):
        for it in tx["items"]:
            w.writerow([tx["id"], tx["created_at"], tx["card_id"], tx["user_name"], tx["action"],
                        it["component"], it["qty"], it["detected_qty"], tx["image"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=kiosk_transactions.csv"})


if __name__ == "__main__":
    print(f"Kiosk on http://{config.HOST}:{config.PORT}  (admin: /admin)")
    try:
        from waitress import serve
        serve(app, host=config.HOST, port=config.PORT, threads=8)
    except ImportError:
        app.run(host=config.HOST, port=config.PORT, threaded=True)
