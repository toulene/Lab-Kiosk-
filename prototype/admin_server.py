"""Prototype admin website - runs on the LAPTOP.

Receives tray scans from the Pi (photo + components found by gem.py) and shows them live.

    py -m pip install flask waitress
    py admin_server.py                 then open http://localhost:5050

The Pi sends to http://<this laptop's IP>:5050/api/scan - the IP is printed at startup.
Scans are kept in prototype/data/ (scans.json + the photos), so they survive a restart.
"""
import base64
import json
import os
import secrets
import socket
import threading
import time
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

PORT = int(os.environ.get("PROTO_PORT", 5050))
TOKEN = os.environ.get("PROTO_TOKEN", "")          # optional: if set, the Pi must send the same value
DATA_DIR = Path(__file__).resolve().parent / "data"
PHOTO_DIR = DATA_DIR / "scans"
LOG_FILE = DATA_DIR / "scans.json"
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
lock = threading.Lock()
scans = json.loads(LOG_FILE.read_text()) if LOG_FILE.exists() else []


def save_log():
    tmp = LOG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(scans, indent=1))
    tmp.replace(LOG_FILE)


@app.post("/api/scan")
def receive_scan():
    if TOKEN and request.headers.get("X-Token") != TOKEN:
        abort(401)
    body = request.get_json(force=True)
    scan_id = time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
    photo = f"{scan_id}.jpg"
    (PHOTO_DIR / photo).write_bytes(base64.b64decode(body["image_b64"]))
    scan = {
        "id": scan_id,
        "received_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "captured_at": body.get("captured_at", ""),
        "device": body.get("device", ""),
        "components": [str(c) for c in body.get("components", [])],
        "counts": {str(k): int(v) for k, v in (body.get("counts") or {}).items()},   # only from rf_label.py
        "seconds": body.get("seconds"),
        "error": body.get("error", ""),
        "photo": photo,
    }
    with lock:
        scans.append(scan)
        save_log()
    print(f"[scan] {scan_id} from {scan['device']}: {', '.join(scan['components']) or scan['error'] or 'nothing found'}")
    return jsonify(ok=True, id=scan_id)


@app.get("/api/scans")
def list_scans():
    with lock:
        return jsonify(list(reversed(scans[-200:])))


@app.get("/photos/<name>")
def photo(name):
    return send_from_directory(PHOTO_DIR, name)


@app.get("/")
def dashboard():
    return PAGE


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lab Kiosk - Admin</title>
<style>
  :root { --bg:#f4f5f7; --card:#fff; --ink:#1d2330; --muted:#6b7280; --line:#e3e6eb; --accent:#4f46e5; --bad:#b42318; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.45 system-ui, sans-serif; background:var(--bg); color:var(--ink); }
  header { display:flex; align-items:center; justify-content:space-between; padding:14px 24px; background:var(--card); border-bottom:1px solid var(--line); }
  header h1 { font-size:18px; margin:0; }
  #status { font-size:13px; color:var(--muted); }
  #status.live::before { content:""; display:inline-block; width:8px; height:8px; border-radius:50%; background:#16a34a; margin-right:6px; }
  main { max-width:1150px; margin:0 auto; padding:20px 24px; }
  .latest { display:grid; grid-template-columns:minmax(0,3fr) minmax(0,2fr); gap:20px; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }
  .latest img { width:100%; border-radius:6px; background:#ddd; }
  .latest h2 { margin:0 0 4px; font-size:16px; }
  .meta { color:var(--muted); font-size:13px; margin-bottom:12px; }
  .chips { display:flex; flex-wrap:wrap; gap:8px; }
  .chip { padding:6px 12px; border-radius:999px; background:#eef0ff; color:var(--accent); font-weight:600; }
  .err { color:var(--bad); font-weight:600; }
  .flash { animation:flash 1.2s ease-out; }
  @keyframes flash { from { box-shadow:0 0 0 4px var(--accent); } to { box-shadow:0 0 0 0 transparent; } }
  h3 { margin:26px 0 10px; font-size:15px; }
  table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  th, td { text-align:left; padding:8px 12px; border-bottom:1px solid var(--line); vertical-align:middle; font-size:14px; }
  th { background:#fafbfc; color:var(--muted); font-weight:600; }
  td img { width:96px; border-radius:4px; display:block; cursor:pointer; }
  .empty { padding:40px; text-align:center; color:var(--muted); background:var(--card); border:1px dashed var(--line); border-radius:10px; }
  @media (max-width:760px) { .latest { grid-template-columns:1fr; } td img { width:64px; } }
</style></head>
<body>
<header><h1>Lab Kiosk &middot; Admin</h1><span id="status">connecting&hellip;</span></header>
<main>
  <div id="latest" class="empty">Waiting for the first scan from the kiosk&hellip;</div>
  <h3>Scan history</h3>
  <table><thead><tr><th>Photo</th><th>Time</th><th>Components</th><th>Kiosk</th><th>Took</th></tr></thead>
  <tbody id="rows"></tbody></table>
</main>
<script>
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const chips = s => s.error ? `<span class="err">${esc(s.error)}</span>`
  : s.components.length ? `<div class="chips">${s.components.map(c =>
      `<span class="chip">${esc(c)}${s.counts && s.counts[c] ? ` &times; ${esc(s.counts[c])}` : ""}</span>`).join("")}</div>`
  : `<span class="meta">No components found</span>`;
const total = s => {
  const n = Object.values(s.counts || {}).reduce((a, b) => a + b, 0);
  return n ? `<div class="meta" style="margin-top:12px">${n} item${n === 1 ? "" : "s"} on the tray</div>` : "";
};
let shownId = null;
async function refresh() {
  try {
    const list = await (await fetch("/api/scans", {cache:"no-store"})).json();
    document.getElementById("status").textContent = `live · ${list.length} scan${list.length === 1 ? "" : "s"}`;
    document.getElementById("status").className = "live";
    if (!list.length) return;
    const s = list[0];
    if (s.id !== shownId) {
      const box = document.getElementById("latest");
      box.className = "latest" + (shownId ? " flash" : "");
      box.innerHTML = `<a href="/photos/${esc(s.photo)}" target="_blank"><img src="/photos/${esc(s.photo)}" alt="tray photo"></a>
        <div><h2>Latest scan</h2>
        <div class="meta">${esc(s.received_at)} · ${esc(s.device)}${s.seconds ? ` · labelled in ${esc(s.seconds)} s` : ""}</div>
        ${chips(s)}${total(s)}</div>`;
      shownId = s.id;
    }
    document.getElementById("rows").innerHTML = list.map(s => `<tr>
      <td><a href="/photos/${esc(s.photo)}" target="_blank"><img src="/photos/${esc(s.photo)}" alt=""></a></td>
      <td>${esc(s.received_at)}</td><td>${chips(s)}</td><td>${esc(s.device)}</td>
      <td>${s.seconds ? esc(s.seconds) + " s" : ""}</td></tr>`).join("");
  } catch (e) {
    document.getElementById("status").textContent = "server not reachable - retrying";
    document.getElementById("status").className = "";
  }
}
refresh(); setInterval(refresh, 2000);
</script>
</body></html>"""


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))          # no packet is sent; just picks the outgoing interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    print(f"Admin page:      http://localhost:{PORT}")
    print(f"Pi sends to:     http://{lan_ip()}:{PORT}/api/scan")
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=PORT, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=PORT, threaded=True)
