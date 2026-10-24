#!/bin/bash
# One-time setup of the tray-scanner prototype on the Raspberry Pi 4 (Raspberry Pi OS).
# Put pi_scan.py, the labeller scripts (rf_label.py / gem.py / gem_gemini.py) and this file in one
# folder on the Pi, then run:
#     bash setup_pi.sh http://<laptop-ip>:5050
# Afterwards start the scanner with:   ./scan.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER="${1:-}"

for f in pi_scan.py; do
    [ -f "$DIR/$f" ] || { echo "Missing $DIR/$f - copy it here first."; exit 1; }
done

echo "== System packages (camera + Python)"
sudo apt update
sudo apt install -y python3-venv python3-picamera2 python3-pil curl
sudo apt install -y rpicam-apps || sudo apt install -y libcamera-apps || true   # camera command-line tools

echo "== Python environment (sees the apt picamera2 package)"
python3 -m venv --system-site-packages "$DIR/venv"
"$DIR/venv/bin/pip" install --upgrade pip
"$DIR/venv/bin/pip" install groq

echo "== Settings (saved in $DIR/.env - keys already there are kept)"
umask 077                                   # .env readable by this user only
ENV="$DIR/.env"; touch "$ENV"; chmod 600 "$ENV"
get() { grep "^$1=." "$ENV" | tail -1 | cut -d= -f2-; }                    # newest saved value
put() { { grep -v "^$1=" "$ENV" || true; echo "$1=$2"; } > "$ENV.tmp"; mv "$ENV.tmp" "$ENV"; }

[ -n "$SERVER" ] || SERVER="$(get KIOSK_SERVER)"
[ -n "$SERVER" ] || read -rp "Admin laptop address (e.g. http://<laptop-ip>:5050): " SERVER
put KIOSK_SERVER "$SERVER"

if [ -z "$(get ROBOFLOW_API_KEY)" ]; then
    read -rsp "Paste your Roboflow API key (typing is hidden, Enter to skip): " K; echo
    [ -n "$K" ] && put ROBOFLOW_API_KEY "$K"
    unset K
fi
if [ -n "$(get ROBOFLOW_API_KEY)" ] && [ -z "$(get ROBOFLOW_MODEL)" ]; then
    read -rp "Roboflow model ID [dataset_v3-qogn5/1]: " M
    put ROBOFLOW_MODEL "${M:-dataset_v3-qogn5/1}"
fi

# Which labeller scan.sh runs: our Roboflow model if its key is saved, else Groq (gem.py), else Gemini.
if [ -n "$(get ROBOFLOW_API_KEY)" ]; then LAB=rf_label.py
elif [ -n "$(get GROQ_API_KEY)" ]; then LAB=gem.py
elif [ -n "$(get GEMINI_API_KEY)" ]; then LAB=gem_gemini.py
else LAB=gem.py; echo "No API key saved yet - rerun this script to add one."; fi
put KIOSK_LABELLER "$LAB"
echo "Labeller: $LAB"

cat > "$DIR/scan.sh" <<'EOF'
#!/bin/bash
# Start the tray scanner. Extra arguments go to pi_scan.py, e.g.
#   ./scan.sh --image test.jpg --once
#   ./scan.sh --server http://<new-laptop-ip>:5050      (laptop moved to another network)
#   ./scan.sh --gem ~/kiosk-proto/gem.py              (use Groq for this run)
DIR="$(cd "$(dirname "$0")" && pwd)"
set -a; . "$DIR/.env"; set +a
exec "$DIR/venv/bin/python" "$DIR/pi_scan.py" --server "$KIOSK_SERVER" --gem "$DIR/${KIOSK_LABELLER:-gem.py}" "$@"
EOF
chmod 755 "$DIR/scan.sh"

echo "== Checks"
set +e
if command -v rpicam-still >/dev/null; then CAM=rpicam-still; else CAM=libcamera-still; fi
if $CAM -n -t 1000 -o "$DIR/camera_test.jpg" >/dev/null 2>&1; then
    echo "Camera:        OK (saved $DIR/camera_test.jpg)"
else
    echo "Camera:        NOT working - check the ribbon cable, then: $CAM -o test.jpg"
fi
if [ "$LAB" = rf_label.py ]; then
    [ -f "$DIR/camera_test.jpg" ] || "$DIR/venv/bin/python" -c "from PIL import Image; Image.new('RGB', (64, 64)).save('$DIR/camera_test.jpg')"
    # The model ID can be written several ways (workspace/model, model, project/version) and
    # Roboflow only accepts one - try each and save the first that answers.
    CANDIDATES="$("$DIR/venv/bin/python" - "$(get ROBOFLOW_MODEL)" <<'PY'
import re, sys
m = re.sub(r"^https?://[^/]+/", "", sys.argv[1].strip()).strip("/")
first, _, rest = m.partition("/")
tail = rest if rest and not rest.isdigit() else m              # drop a leading workspace name
ids = [m, tail]
v = re.match(r"(.+?)-(\d+)-rf-?detr", tail.split("/")[-1])      # dataset_v3-qogn5-1-rfdetr-... -> dataset_v3-qogn5/1
if v:
    ids.append(f"{v.group(1)}/{v.group(2)}")
print("\n".join(dict.fromkeys(ids)))
PY
)"
    OK=""
    for CAND in $CANDIDATES; do
        if OUT="$( (set -a; . "$ENV"; set +a; ROBOFLOW_MODEL="$CAND" "$DIR/venv/bin/python" "$DIR/rf_label.py" "$DIR/camera_test.jpg") 2>&1 >/dev/null)"; then
            OK="$CAND"; break
        fi
        echo "  tried $CAND: $(echo "$OUT" | tail -1)"
    done
    if [ -n "$OK" ]; then
        put ROBOFLOW_MODEL "$OK"
        echo "Roboflow:      OK (model $OK answered - saved)"
    else
        echo "Roboflow:      FAILED - see the reasons above (401 = wrong key, 402 = no credits / credit cap, 404 = wrong model ID)"
    fi
else
    "$DIR/venv/bin/python" -c "import groq" 2>/dev/null && echo "groq package:  OK" || echo "groq package:  MISSING"
fi
if curl -s -m 5 "$SERVER/api/scans" >/dev/null; then
    echo "Admin laptop:  reachable at $SERVER"
else
    echo "Admin laptop:  NOT reachable at $SERVER - is admin_server.py running, and are both on the same Wi-Fi/hotspot?"
fi
echo
echo "Done. Start the scanner with:  $DIR/scan.sh"
